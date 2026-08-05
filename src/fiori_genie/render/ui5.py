"""Generates the Fiori elements V4 application shell for an app in the IR.

The manifest is assembled as a dict and serialised with json.dumps rather than
templated, so the output is always valid JSON regardless of what labels or
entity names the model produced.
"""

from __future__ import annotations

import json
from typing import Dict

from ..ir import AppModel, FioriApp, Floorplan
from .cds import service_path

UI5_VERSION = "1.120.0"
MIN_UI5_VERSION = "1.120.0"

FLOORPLAN_TEMPLATE = {
    Floorplan.LIST_REPORT: "sap.fe.templates.ListReport",
    Floorplan.WORKLIST: "sap.fe.templates.ListReport",
    Floorplan.OBJECT_PAGE_ONLY: "sap.fe.templates.ObjectPage",
}


def inbound_id(app: FioriApp) -> str:
    return f"{app.id}-inbound"


def semantic_object(app: FioriApp) -> str:
    return app.main_entity


def semantic_action(model: AppModel, app: FioriApp) -> str:
    """'manage' for editable apps, 'display' for read-only ones."""
    service = next((s for s in model.services if s.name == app.service), None)
    if service is not None:
        exposed = next(
            (e for e in service.entities if e.exposed_name == app.main_entity), None
        )
        if exposed is not None and exposed.readonly:
            return "display"
    return "manage"


def _main_ui(model: AppModel, app: FioriApp):
    """The UiSpec of the app's main entity, if the model supplied one."""
    service = next((s for s in model.services if s.name == app.service), None)
    if service is None:
        return None
    exposed = next(
        (e for e in service.entities if e.exposed_name == app.main_entity), None
    )
    if exposed is None:
        return None
    entity = model.entity(exposed.entity)
    return entity.ui if entity else None


def build_manifest(model: AppModel, app: FioriApp) -> Dict:
    service = next(s for s in model.services if s.name == app.service)
    entity = app.main_entity
    ui = _main_ui(model, app)
    floorplan = ui.floorplan if ui else Floorplan.LIST_REPORT

    list_target = f"{entity}List"
    object_target = f"{entity}ObjectPage"

    routes = [
        {"pattern": ":?query:", "name": list_target, "target": list_target},
        {
            "pattern": f"{entity}({{key}}):?query:",
            "name": object_target,
            "target": object_target,
        },
    ]

    targets = {
        list_target: {
            "type": "Component",
            "id": list_target,
            "name": FLOORPLAN_TEMPLATE[floorplan],
            "options": {
                # `entitySet` rather than `contextPath`: this is the form CAP's
                # own scaffolding emits, and the one the navigation key below is
                # matched against.
                "settings": {
                    "entitySet": entity,
                    # Variant management needs UI5 flexibility services, which
                    # are not wired up when serving from `cds watch`.
                    "variantManagement": "None",
                    "initialLoad": "Enabled",
                    "navigation": {
                        entity: {"detail": {"route": object_target}}
                    },
                }
            },
        },
        object_target: {
            "type": "Component",
            "id": object_target,
            "name": "sap.fe.templates.ObjectPage",
            "options": {
                "settings": {
                    "entitySet": entity,
                    "editableHeaderContent": False,
                }
            },
        },
    }

    return {
        # Manifest schema version matching the bootstrapped UI5 line.
        "_version": "1.59.0",
        "sap.app": {
            "id": app.id,
            "type": "application",
            "i18n": "i18n/i18n.properties",
            "applicationVersion": {"version": "1.0.0"},
            "title": "{{appTitle}}",
            "description": "{{appDescription}}",
            "dataSources": {
                "mainService": {
                    "uri": f"/odata/v4/{service_path(service)}/",
                    "type": "OData",
                    "settings": {
                        "annotations": [],
                        "odataVersion": "4.0",
                    },
                }
            },
            # Registers the app with the launchpad sandbox, which is what
            # supplies the ushell services Fiori elements uses for inner app
            # state and list-to-object navigation.
            "crossNavigation": {
                "inbounds": {
                    inbound_id(app): {
                        "semanticObject": semantic_object(app),
                        "action": semantic_action(model, app),
                        "title": "{{appTitle}}",
                        "info": "{{appDescription}}",
                        "signature": {"parameters": {}, "additionalParameters": "allowed"},
                    }
                }
            },
        },
        "sap.ui": {
            "technology": "UI5",
            "icons": {},
            "deviceTypes": {"desktop": True, "tablet": True, "phone": True},
        },
        "sap.ui5": {
            "flexEnabled": False,
            "dependencies": {
                "minUI5Version": MIN_UI5_VERSION,
                "libs": {
                    "sap.m": {},
                    "sap.ui.core": {},
                    "sap.fe.templates": {},
                },
            },
            "models": {
                "i18n": {
                    "type": "sap.ui.model.resource.ResourceModel",
                    "settings": {"bundleName": f"{app.id}.i18n.i18n"},
                },
                "": {
                    "dataSource": "mainService",
                    "preload": True,
                    "settings": {
                        "operationMode": "Server",
                        "autoExpandSelect": True,
                        "earlyRequests": True,
                    },
                },
            },
            "resources": {"css": []},
            "routing": {
                "config": {},
                "routes": routes,
                "targets": targets,
            },
            "contentDensities": {"compact": True, "cozy": True},
        },
        "sap.fiori": {
            "registrationIds": [],
            "archeType": "transactional",
        },
    }


def component_js(app: FioriApp) -> str:
    return f"""sap.ui.define(
    ["sap/fe/core/AppComponent"],
    function (AppComponent) {{
        "use strict";

        return AppComponent.extend("{app.id}.Component", {{
            metadata: {{
                manifest: "json"
            }}
        }});
    }}
);
"""


def index_html(app: FioriApp) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{app.title}</title>
    <script
        id="sap-ui-bootstrap"
        src="https://ui5.sap.com/{UI5_VERSION}/resources/sap-ui-core.js"
        data-sap-ui-theme="sap_horizon"
        data-sap-ui-libs="sap.m,sap.fe.templates"
        data-sap-ui-compat-version="edge"
        data-sap-ui-async="true"
        data-sap-ui-frame-options="trusted"
        data-sap-ui-flexibilityServices="[]"
        data-sap-ui-resource-roots='{{"{app.id}": "./"}}'
        data-sap-ui-on-init="module:sap/ui/core/ComponentSupport">
    </script>
</head>
<body class="sapUiBody sapUiSizeCompact">
    <div
        data-sap-ui-component
        data-name="{app.id}"
        data-id="container"
        data-settings='{{"id": "{app.id}"}}'
        data-height="100%">
    </div>
</body>
</html>
"""


def i18n_properties(app: FioriApp) -> str:
    description = app.description or app.title
    return f"""# Generated from the functional spec. Safe to edit.
appTitle={app.title}
appDescription={description}
"""


def ui5_yaml(app: FioriApp) -> str:
    return f"""specVersion: "3.1"
metadata:
  name: {app.id}
type: application
framework:
  name: SAPUI5
  version: "{UI5_VERSION}"
  libraries:
    - name: sap.m
    - name: sap.ui.core
    - name: sap.fe.templates
    - name: themelib_sap_horizon
"""


def manifest_json(model: AppModel, app: FioriApp) -> str:
    return json.dumps(build_manifest(model, app), indent=2) + "\n"


def launchpad_html(model: AppModel) -> str:
    """A Fiori launchpad sandbox hosting every generated app.

    Fiori elements apps depend on ushell services for cross-app navigation and
    inner app state. Served from a bare index.html those services are absent,
    which breaks navigation from the list report to the object page. The sandbox
    supplies them, so this is the intended way to run the generated apps
    locally.
    """
    title = model.description or model.project_name

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    <script>
        window["sap-ushell-config"] = {{
            defaultRenderer: "fiori2",
            renderers: {{
                fiori2: {{
                    componentData: {{
                        config: {{
                            enableSearch: false
                        }}
                    }}
                }}
            }},
            applications: {{}}
        }};
    </script>

    <script
        id="sap-ushell-bootstrap"
        src="https://ui5.sap.com/{UI5_VERSION}/test-resources/sap/ushell/bootstrap/sandbox.js">
    </script>

    <script
        id="sap-ui-bootstrap"
        src="https://ui5.sap.com/{UI5_VERSION}/resources/sap-ui-core.js"
        data-sap-ui-libs="sap.m,sap.ushell,sap.ui.layout,sap.fe.templates"
        data-sap-ui-compat-version="edge"
        data-sap-ui-theme="sap_horizon"
        data-sap-ui-async="true"
        data-sap-ui-frame-options="trusted">
    </script>

    <script>
        sap.ui.getCore().attachInit(function () {{
            sap.ushell.Container
                .createRenderer("fiori2", true)
                .then(function (renderer) {{
                    renderer.placeAt("content");
                }});
        }});
    </script>
</head>
<body class="sapUiBody" id="content"></body>
</html>
"""


def sandbox_config(model: AppModel) -> str:
    """Tile definitions and target resolution for the launchpad sandbox."""
    tiles = []
    inbounds = {}

    for app in model.apps:
        action = semantic_action(model, app)
        target_url = f"#{semantic_object(app)}-{action}"

        tiles.append(
            {
                "id": app.id,
                "tileType": "sap.ushell.ui.tile.StaticTile",
                "properties": {
                    "title": app.title,
                    "subtitle": app.description or "",
                    "targetURL": target_url,
                },
            }
        )

        inbounds[inbound_id(app)] = {
            "semanticObject": semantic_object(app),
            "action": action,
            "title": app.title,
            "signature": {"parameters": {}, "additionalParameters": "allowed"},
            "resolutionResult": {
                "applicationType": "SAPUI5",
                "additionalInformation": f"SAPUI5.Component={app.id}",
                "url": f"/{app.id}/webapp",
            },
        }

    config = {
        "services": {
            "LaunchPage": {
                "adapter": {
                    "config": {
                        "groups": [
                            {
                                "id": "generated",
                                "title": model.description or model.project_name,
                                "isPreset": True,
                                "isVisible": True,
                                "isGroupLocked": False,
                                "tiles": tiles,
                            }
                        ]
                    }
                }
            },
            "NavTargetResolution": {
                "config": {"enableClientSideTargetResolution": True}
            },
            "ClientSideTargetResolution": {
                "adapter": {"config": {"inbounds": inbounds}}
            },
        }
    }

    return json.dumps(config, indent=2) + "\n"
