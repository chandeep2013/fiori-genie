
from pathlib import Path
from fiori_genie.providers.demo_provider import resolve_fixture_name, DemoProvider

SPECS = Path(__file__).resolve().parents[1] / "specs"

def test_each_sample_spec_maps_to_its_fixture():
    expected = {
        "travel-expense.md": "travel-expense",
        "leave-request.md": "leave-request",
        "maintenance-notification.md": "maintenance-notification",
        "sales-quotation.md": "sales-quotation",
        "supplier-invoice.md": "supplier-invoice",
        "purchase-requisition.md": "purchase-requisition",
    }
    for name, fixture in expected.items():
        text = (SPECS / name).read_text().lower()
        assert resolve_fixture_name(text) == fixture, name

def test_demo_generate_returns_matching_entities():
    provider = DemoProvider()
    raw = provider.generate("", [{"role": "user", "content": (SPECS / "travel-expense.md").read_text()}], {})
    names = {e["name"] for e in raw["entities"]}
    assert "ExpenseClaims" in names
    assert "PurchaseRequisitions" not in names
    assert provider.model == "fixture/travel-expense"
