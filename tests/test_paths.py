from pathlib import Path

from fiori_genie.paths import allocate_output_dir, slugify_project_name


def test_slugify():
    assert slugify_project_name("Travel Expense!") == "travel-expense"
    assert slugify_project_name(None) == "app"


def test_allocate_avoids_overwrite(tmp_path: Path):
    first = allocate_output_dir("travel-expense", root=tmp_path)
    first.mkdir(parents=True)
    second = allocate_output_dir("travel-expense", root=tmp_path)
    assert first != second
    assert not second.exists()
    assert second.name.startswith("travel-expense-")
