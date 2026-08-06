"""Tests for the deterministic half of the pipeline: IR -> validation -> render.

No LLM is involved, so these run in CI. Several assertions pin down behaviour
that was originally wrong and is easy to regress:

- the service path must not start with a slash, or CAP drops the /odata/v4 prefix
- the manifest must use `entitySet`, matching the navigation key
- composition children must not be draft-enabled
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from fiori_genie.compile import compile_project, find_cds
from fiori_genie.ir import AppModel
from fiori_genie.render import render_project
from fiori_genie.render.cds import service_options, service_path, service_url
from fiori_genie.render.ui5 import build_manifest
from fiori_genie.validate import validate_model

FIXTURE = Path(__file__).parent / "fixtures" / "purchase-requisition.json"


@pytest.fixture(scope="module")
def model() -> AppModel:
    return AppModel.model_validate(json.loads(FIXTURE.read_text()))


@pytest.fixture(scope="module")
def rendered(model: AppModel, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("project")
    render_project(model, out)
    return out


def cds_available() -> bool:
    try:
        find_cds()
        return True
    except Exception:
        return False


class TestModel:
    def test_fixture_parses(self, model: AppModel):
        assert model.project_name == "purchase-requisition"
        assert len(model.entities) == 3

    def test_fixture_is_semantically_valid(self, model: AppModel):
        assert validate_model(model) == []


class TestValidation:
    def _mutate(self, raw: dict) -> AppModel:
        return AppModel.model_validate(raw)

    def test_rejects_unknown_relation_target(self):
        raw = json.loads(FIXTURE.read_text())
        raw["entities"][1]["relations"][0]["target"] = "Nonexistent"

        errors = validate_model(self._mutate(raw))
        assert any("does not exist" in e for e in errors)

    def test_rejects_draft_enabled_composition_child(self):
        raw = json.loads(FIXTURE.read_text())
        for exposed in raw["services"][0]["entities"]:
            if exposed["entity"] == "PurchaseRequisitionItems":
                exposed["draftEnabled"] = True

        errors = validate_model(self._mutate(raw))
        assert any("composition child" in e for e in errors)

    def test_rejects_ui_reference_to_missing_field(self):
        raw = json.loads(FIXTURE.read_text())
        raw["entities"][1]["ui"]["lineItem"].append("noSuchField")

        errors = validate_model(self._mutate(raw))
        assert any("noSuchField" in e for e in errors)

    def test_rejects_backlink_pointing_elsewhere(self):
        raw = json.loads(FIXTURE.read_text())
        raw["entities"][1]["relations"][1]["backlink"] = "position"

        errors = validate_model(self._mutate(raw))
        assert any("backlink" in e for e in errors)

    def test_rejects_sample_data_for_unknown_column(self):
        raw = json.loads(FIXTURE.read_text())
        raw["sampleData"]["Suppliers"][0]["bogusColumn"] = "x"

        errors = validate_model(self._mutate(raw))
        assert any("bogusColumn" in e for e in errors)

    def test_rejects_reserved_keyword_as_entity_name(self):
        raw = json.loads(FIXTURE.read_text())
        raw["entities"][0]["name"] = "select"

        with pytest.raises(Exception, match="reserved"):
            self._mutate(raw)

    def test_rejects_decimal_without_scale(self):
        raw = json.loads(FIXTURE.read_text())
        raw["entities"][0]["fields"][3].pop("scale")

        with pytest.raises(Exception, match="precision and scale"):
            self._mutate(raw)


class TestServiceUrls:
    def test_path_has_no_leading_slash(self, model: AppModel):
        # A leading slash makes the CDS path absolute, which silently drops the
        # /odata/v4 prefix and breaks every generated URL.
        options = service_options(model.services[0])
        assert "path: 'procurement'" in options
        assert "path: '/procurement'" not in options

    def test_url_matches_path(self, model: AppModel):
        service = model.services[0]
        assert service_path(service) == "procurement"
        assert service_url(service) == "/odata/v4/procurement"

    def test_path_derived_from_name_when_absent(self, model: AppModel):
        service = model.services[0].model_copy(update={"path": None})
        assert service_path(service) == "procurement"


class TestManifest:
    def test_uses_entity_set_not_context_path(self, model: AppModel):
        manifest = build_manifest(model, model.apps[0])
        targets = manifest["sap.ui5"]["routing"]["targets"]
        settings = targets["PurchaseRequisitionsList"]["options"]["settings"]

        assert settings["entitySet"] == "PurchaseRequisitions"
        assert "contextPath" not in settings

    def test_navigation_key_matches_entity_set(self, model: AppModel):
        manifest = build_manifest(model, model.apps[0])
        settings = manifest["sap.ui5"]["routing"]["targets"][
            "PurchaseRequisitionsList"
        ]["options"]["settings"]

        assert settings["entitySet"] in settings["navigation"]

    def test_data_source_points_at_odata_v4(self, model: AppModel):
        manifest = build_manifest(model, model.apps[0])
        uri = manifest["sap.app"]["dataSources"]["mainService"]["uri"]
        assert uri == "/odata/v4/procurement/"

    def test_declares_cross_navigation_inbound(self, model: AppModel):
        manifest = build_manifest(model, model.apps[0])
        inbounds = manifest["sap.app"]["crossNavigation"]["inbounds"]
        assert len(inbounds) == 1


class TestRenderedOutput:
    def test_writes_expected_files(self, rendered: Path):
        for expected in [
            "db/schema.cds",
            "srv/service.cds",
            "package.json",
            "app/launchpad.html",
            "app/appconfig/fioriSandboxConfig.json",
            "app/purchasereq/annotations.cds",
            "app/purchasereq/webapp/manifest.json",
            "test/service.test.js",
        ]:
            assert (rendered / expected).is_file(), f"missing {expected}"

    def test_manifest_is_valid_json(self, rendered: Path):
        json.loads((rendered / "app/purchasereq/webapp/manifest.json").read_text())

    def test_sandbox_config_is_valid_json(self, rendered: Path):
        json.loads((rendered / "app/appconfig/fioriSandboxConfig.json").read_text())

    def test_association_renders_as_readable_path(self, rendered: Path):
        annotations = (rendered / "app/purchasereq/annotations.cds").read_text()
        # Tables should show the supplier's name, never the raw foreign key.
        assert "supplier.name" in annotations
        assert "supplier_ID" not in annotations

    def test_composition_backlink_rendered(self, rendered: Path):
        schema = (rendered / "db/schema.cds").read_text()
        assert (
            "items : Composition of many PurchaseRequisitionItems "
            "on items.requisition = $self;" in schema
        )

    def test_enum_and_default_order(self, rendered: Path):
        schema = (rendered / "db/schema.cds").read_text()
        assert "enum {" in schema
        assert "} default 'DRAFT';" in schema

    def test_bare_enum_default_is_normalized(self, tmp_path: Path):
        """Gemini often emits default: DRAFT without quotes — CDS rejects that."""
        from fiori_genie.render.cds import default_expr, field_decl

        raw = json.loads(FIXTURE.read_text())
        for entity in raw["entities"]:
            for field in entity.get("fields", []):
                if field.get("name") == "status":
                    field["default"] = "DRAFT"

        model = AppModel.model_validate(raw)
        status = next(
            f for e in model.entities for f in e.fields if f.name == "status"
        )
        assert default_expr(status) == "#DRAFT"
        assert "default #DRAFT" in field_decl(status)

        render_project(model, tmp_path)
        if cds_available():
            ok, diagnostics = compile_project(tmp_path)
            assert ok, diagnostics

    def test_sample_csv_header_matches_columns(self, rendered: Path):
        csv_path = rendered / "db/data/com.acme.procurement-PurchaseRequisitions.csv"
        header = csv_path.read_text().splitlines()[0].split(",")

        assert header[0] == "ID"
        assert "supplier_ID" in header
        assert "reqNumber" in header

    def test_development_profile_disables_auth_prompt(self, rendered: Path):
        package = json.loads((rendered / "package.json").read_text())
        assert package["cds"]["requires"]["[development]"]["auth"]["kind"] == "dummy"


@pytest.mark.skipif(not cds_available(), reason="cds executable not installed")
class TestCompiles:
    def test_generated_project_compiles(self, rendered: Path):
        ok, diagnostics = compile_project(rendered)
        assert ok, "cds compile failed:\n" + "\n".join(diagnostics)

    def test_oracle_rejects_broken_schema(self, rendered: Path, tmp_path: Path):
        """The repair loop is only worth anything if this actually fails."""
        broken = tmp_path / "broken"
        shutil.copytree(rendered, broken)

        schema = broken / "db" / "schema.cds"
        schema.write_text(
            schema.read_text().replace(
                "Association to Suppliers;", "Association to DoesNotExist;"
            )
        )

        ok, diagnostics = compile_project(broken)
        assert not ok
        assert any("DoesNotExist" in d for d in diagnostics)

    def test_diagnostics_are_free_of_ansi_escapes(self, rendered: Path, tmp_path: Path):
        broken = tmp_path / "ansi"
        shutil.copytree(rendered, broken)

        schema = broken / "db" / "schema.cds"
        schema.write_text(schema.read_text().replace("String(100)", "Strin(100)"))

        _, diagnostics = compile_project(broken)
        assert diagnostics
        assert not any("\x1b[" in d for d in diagnostics)
