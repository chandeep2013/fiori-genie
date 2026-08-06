"""Tests for LLM output normalization and multi-service EDMX compile."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from fiori_genie.compile import check_annotations, find_cds
from fiori_genie.ir import AppModel
from fiori_genie.normalize import normalize_model
from fiori_genie.prompts import build_repair_prompt
from fiori_genie.render import render_project

FIXTURE = Path(__file__).parent / "fixtures" / "travel-expense.json"


def _travel_with_bogus_entities_service() -> dict:
    raw = json.loads(FIXTURE.read_text())
    raw["services"].append(
        {
            "name": "entities",
            "path": "entities",
            "entities": [
                {
                    "entity": "CostCentres",
                    "draftEnabled": False,
                    "readonly": True,
                }
            ],
        }
    )
    return raw


class TestNormalizeServices:
    def test_drops_bogus_entities_service(self):
        model = AppModel.model_validate(_travel_with_bogus_entities_service())
        assert len(model.services) == 2

        fixed = normalize_model(model)
        assert [s.name for s in fixed.services] == ["TravelService"]

    def test_merges_extra_real_service_into_app_service(self):
        raw = json.loads(FIXTURE.read_text())
        raw["services"].append(
            {
                "name": "LookupService",
                "path": "lookups",
                "entities": [
                    {
                        "entity": "CostCentres",
                        "as": "CostCentreCodes",
                        "draftEnabled": False,
                        "readonly": True,
                    }
                ],
            }
        )
        fixed = normalize_model(AppModel.model_validate(raw))
        assert len(fixed.services) == 1
        assert fixed.services[0].name == "TravelService"
        exposed = {e.exposed_name for e in fixed.services[0].entities}
        assert "CostCentreCodes" in exposed


class TestEdmxMultiService:
    def test_check_annotations_accepts_multiple_services(self, tmp_path: Path):
        try:
            find_cds()
        except Exception:
            pytest.skip("cds not available")

        raw = _travel_with_bogus_entities_service()
        # Bypass normalize so we still render two services — the compile
        # helper itself must tolerate that with `-s all`.
        model = AppModel.model_validate(raw)
        render_project(model, tmp_path)
        ok, diagnostics = check_annotations(tmp_path)
        assert ok, diagnostics


class TestRepairPrompt:
    def test_mentions_entities_service_when_multi_service_error(self):
        text = build_repair_prompt(
            ["Found multiple service definitions in given model(s)."],
            "compile",
        )
        assert "entities" in text
        assert "exactly one OData service" in text
