"""Generates three layers of tests for the produced CAP application.

- `cds.test` service tests: no browser, fast, and the layer most likely to catch
  a structurally broken generated model. Runs in CI as-is.
- OPA5 journeys: Fiori elements page objects for list report and object page.
- wdi5 e2e: a browser smoke test, generated as a starting point.
"""

from __future__ import annotations

import json
from typing import List

from ..ir import AppModel, Cardinality, FioriApp, Service
from .cds import service_path


def service_test(model: AppModel) -> str:
    """A cds.test suite asserting every exposed entity is reachable and populated."""
    blocks: List[str] = []
    needs_auth = any(s.requires for s in model.services)

    # Services declaring `requires` reject anonymous calls, so the suite runs as
    # one of CAP's mocked development users.
    opts = ", opts" if needs_auth else ""

    for service in model.services:
        path = service_path(service)
        service_blocks: List[str] = [
            f"""    it('serves $metadata', async () => {{
      const {{ status, data }} = await GET('/odata/v4/{path}/$metadata'{opts})
      expect(status).to.equal(200)
      expect(data).to.include('EntityContainer')
    }})"""
        ]

        if any(e.draft_enabled for e in service.entities):
            service_blocks.append(
                f"""    it('exposes draft-enabled entities', async () => {{
      const {{ data }} = await GET('/odata/v4/{path}/$metadata'{opts})
      expect(data).to.include('IsActiveEntity')
    }})"""
            )

        for exposed in service.entities:
            if model.entity(exposed.entity) is None:
                continue

            name = exposed.exposed_name
            has_data = bool(model.sample_data.get(exposed.entity))

            entity_tests = [
                f"""      it('is queryable', async () => {{
        const {{ status, data }} = await GET('/odata/v4/{path}/{name}'{opts})
        expect(status).to.equal(200)
        expect(data.value).to.be.an('array')
      }})"""
            ]

            if has_data:
                entity_tests.append(
                    f"""      it('has its sample data loaded', async () => {{
        const {{ data }} = await GET('/odata/v4/{path}/{name}'{opts})
        expect(data.value.length).to.be.greaterThan(0)
      }})"""
                )

            service_blocks.append(
                f"    describe('{name}', () => {{\n"
                + "\n\n".join(entity_tests)
                + "\n    })"
            )

        blocks.append(
            f"  describe('{service.name}', () => {{\n"
            + "\n\n".join(service_blocks)
            + "\n  })"
        )

    auth_line = (
        "\n// CAP's mocked users are available in development profiles.\n"
        "const opts = { auth: { username: 'alice', password: '' } }\n"
        if needs_auth
        else ""
    )

    return f"""const cds = require('@sap/cds')
const {{ expect, GET }} = cds.test(__dirname + '/..')
{auth_line}
describe('{model.project_name} service', () => {{
{chr(10).join(blocks)}
}})
"""


def _list_page(app: FioriApp) -> str:
    return f"""sap.ui.define(['sap/fe/test/ListReport'], function (ListReport) {{
    'use strict';

    return new ListReport({{
        appId: '{app.id}',
        componentId: '{app.main_entity}List',
        entitySet: '{app.main_entity}'
    }});
}});
"""


def _object_page(app: FioriApp) -> str:
    return f"""sap.ui.define(['sap/fe/test/ObjectPage'], function (ObjectPage) {{
    'use strict';

    return new ObjectPage({{
        appId: '{app.id}',
        componentId: '{app.main_entity}ObjectPage',
        entitySet: '{app.main_entity}'
    }});
}});
"""


def _journey(app: FioriApp) -> str:
    return f"""sap.ui.define([], function () {{
    'use strict';

    return {{
        run: function () {{
            QUnit.module('{app.title} journey');

            opaTest('Application starts and the list page is shown', function (Given, When, Then) {{
                Given.iStartMyApp();
                Then.onTheListPage.iSeeThisPage();
            }});

            opaTest('Searching returns rows', function (Given, When, Then) {{
                When.onTheListPage.onFilterBar().iExecuteSearch();
                Then.onTheListPage.onTable().iCheckRows();
            }});

            opaTest('Selecting a row opens the object page', function (Given, When, Then) {{
                When.onTheListPage.onTable().iPressRow(0);
                Then.onTheObjectPage.iSeeThisPage();
            }});

            opaTest('Teardown', function (Given, When, Then) {{
                Given.iTearDownMyApp();
            }});
        }}
    }};
}});
"""


def _opa_runner(app: FioriApp) -> str:
    return f"""sap.ui.require(
    [
        'sap/fe/test/JourneyRunner',
        '{app.id}/test/integration/FirstJourney',
        '{app.id}/test/integration/pages/{app.main_entity}List',
        '{app.id}/test/integration/pages/{app.main_entity}ObjectPage'
    ],
    function (JourneyRunner, FirstJourney, ListPage, ObjectPage) {{
        'use strict';

        var runner = new JourneyRunner({{
            launchUrl: sap.ui.require.toUrl('{app.id}') + '/index.html'
        }});

        runner.run(
            {{
                pages: {{
                    onTheListPage: ListPage,
                    onTheObjectPage: ObjectPage
                }}
            }},
            FirstJourney.run
        );
    }}
);
"""


def opa_files(app: FioriApp) -> dict:
    """Relative path under the app's webapp folder -> file contents."""
    return {
        "test/integration/FirstJourney.js": _journey(app),
        f"test/integration/pages/{app.main_entity}List.js": _list_page(app),
        f"test/integration/pages/{app.main_entity}ObjectPage.js": _object_page(app),
        "test/integration/opaTests.qunit.js": _opa_runner(app),
        "test/testsuite.qunit.js": _testsuite(app),
        "test/testsuite.qunit.html": _testsuite_html(app),
    }


def _testsuite(app: FioriApp) -> str:
    return f"""window.suite = function () {{
    'use strict';

    var suite = new parent.jsUnitTestSuite();
    var contextPath = location.pathname.substring(
        0,
        location.pathname.lastIndexOf('/test/') + 1
    );

    suite.addTestPage(contextPath + 'test/integration/opaTests.qunit.html');

    return suite;
}};
"""


def _testsuite_html(app: FioriApp) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{app.title} - Test Suite</title>
    <script src="../resources/sap/ui/qunit/qunit-redirect.js"></script>
    <script src="testsuite.qunit.js"></script>
</head>
<body></body>
</html>
"""


def wdio_conf(model: AppModel) -> str:
    specs = ", ".join(f"'./test/e2e/{app.id}.test.js'" for app in model.apps)
    return f"""const {{ join }} = require('path');

exports.config = {{
    runner: 'local',
    specs: [{specs}],
    maxInstances: 1,
    capabilities: [
        {{
            browserName: 'chrome',
            'goog:chromeOptions': {{
                args: process.env.HEADLESS
                    ? ['--headless=new', '--disable-gpu', '--window-size=1600,1200']
                    : ['--window-size=1600,1200']
            }}
        }}
    ],
    logLevel: 'error',
    // Assumes `cds watch` is already serving on 4004.
    baseUrl: 'http://localhost:4004',
    waitforTimeout: 30000,
    connectionRetryTimeout: 120000,
    connectionRetryCount: 3,
    services: ['ui5'],
    framework: 'mocha',
    reporters: ['spec'],
    mochaOpts: {{
        ui: 'bdd',
        timeout: 90000
    }},
    wdi5: {{
        logLevel: 'error',
        screenshotPath: join('test', 'e2e', '__screenshots__')
    }}
}};
"""


def wdi5_test(model: AppModel, app: FioriApp) -> str:
    service = next(s for s in model.services if s.name == app.service)
    path = service_path(service)

    return f"""const {{ wdi5 }} = require('wdio-ui5-service');

describe('{app.title}', () => {{
    before(async () => {{
        await browser.goTo('/{app.id}/webapp/index.html');
    }});

    it('bootstraps the Fiori elements app', async () => {{
        const title = await browser.getTitle();
        expect(title).toContain('{app.title}');
    }});

    it('renders the list report table', async () => {{
        const table = await browser.asControl({{
            selector: {{
                controlType: 'sap.ui.mdc.Table',
                viewName: 'sap.fe.templates.ListReport.ListReport',
                id: {{ id: '{app.main_entity}List' }},
                searchOpenDialogs: false
            }}
        }});
        expect(await table.isInitialized()).toBeTruthy();
    }});

    it('serves data over OData', async () => {{
        const response = await fetch(
            `${{browser.options.baseUrl}}/odata/v4/{path}/{app.main_entity}`
        );
        expect(response.status).toBe(200);
        const body = await response.json();
        expect(Array.isArray(body.value)).toBe(true);
    }});
}});
"""
