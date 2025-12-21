"""Tests for CategoryMixin database operations.

These tests use a real temporary SQLite database.
"""

from pathlib import Path

import pytest

from ynab_tui.db.database import Database


@pytest.fixture
def temp_db(tmp_path: Path) -> Database:
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


class TestCategoryMixin:
    """Tests for YNAB category operations."""

    def test_upsert_category_insert(self, temp_db: Database) -> None:
        """Can insert a new category."""
        was_inserted, was_changed = temp_db.upsert_category(
            category_id="cat-001",
            name="Groceries",
            group_id="grp-001",
            group_name="Essentials",
        )

        assert was_inserted is True
        assert was_changed is True

    def test_upsert_category_update(self, temp_db: Database) -> None:
        """Can update an existing category."""
        temp_db.upsert_category("cat-001", "Groceries", "grp-001", "Essentials")

        was_inserted, was_changed = temp_db.upsert_category(
            category_id="cat-001",
            name="Food & Groceries",
            group_id="grp-001",
            group_name="Essentials",
        )

        assert was_inserted is False
        assert was_changed is True

    def test_upsert_category_no_change(self, temp_db: Database) -> None:
        """Upserting unchanged category returns was_changed=False."""
        temp_db.upsert_category("cat-001", "Groceries", "grp-001", "Essentials")

        was_inserted, was_changed = temp_db.upsert_category(
            "cat-001", "Groceries", "grp-001", "Essentials"
        )

        assert was_inserted is False
        assert was_changed is False

    def test_upsert_category_with_hidden(self, temp_db: Database) -> None:
        """Can insert hidden category."""
        temp_db.upsert_category("cat-001", "Hidden Category", "grp-001", "Group", hidden=True)

        cat = temp_db.get_category_by_id("cat-001")
        assert cat is not None
        assert cat["hidden"] == 1

    def test_upsert_category_with_deleted(self, temp_db: Database) -> None:
        """Can insert deleted category."""
        temp_db.upsert_category("cat-001", "Deleted Category", "grp-001", "Group", deleted=True)

        cat = temp_db.get_category_by_id("cat-001")
        assert cat is not None
        assert cat["deleted"] == 1

    def test_get_category_by_id(self, temp_db: Database) -> None:
        """Can get category by ID."""
        temp_db.upsert_category("cat-001", "Groceries", "grp-001", "Essentials")

        cat = temp_db.get_category_by_id("cat-001")

        assert cat is not None
        assert cat["name"] == "Groceries"
        assert cat["group_name"] == "Essentials"

    def test_get_category_by_id_not_found(self, temp_db: Database) -> None:
        """Returns None for non-existent category."""
        cat = temp_db.get_category_by_id("nonexistent")
        assert cat is None

    def test_get_category_by_name(self, temp_db: Database) -> None:
        """Can get category by name."""
        temp_db.upsert_category("cat-001", "Groceries", "grp-001", "Essentials")

        cat = temp_db.get_category_by_name("Groceries")

        assert cat is not None
        assert cat["id"] == "cat-001"

    def test_get_category_by_name_case_insensitive(self, temp_db: Database) -> None:
        """Category name lookup is case-insensitive."""
        temp_db.upsert_category("cat-001", "Groceries", "grp-001", "Essentials")

        cat = temp_db.get_category_by_name("groceries")

        assert cat is not None
        assert cat["id"] == "cat-001"

    def test_get_category_by_name_not_found(self, temp_db: Database) -> None:
        """Returns None for non-existent category name."""
        cat = temp_db.get_category_by_name("Unknown")
        assert cat is None

    def test_get_categories_empty(self, temp_db: Database) -> None:
        """Empty database returns empty list."""
        groups = temp_db.get_categories()
        assert groups == []

    def test_get_categories(self, temp_db: Database) -> None:
        """Can get categories grouped by group."""
        temp_db.upsert_category("cat-1", "Groceries", "grp-1", "Essentials")
        temp_db.upsert_category("cat-2", "Gas", "grp-1", "Essentials")
        temp_db.upsert_category("cat-3", "Shopping", "grp-2", "Fun")

        groups = temp_db.get_categories()

        assert len(groups) == 2
        group_names = {g["name"] for g in groups}
        assert group_names == {"Essentials", "Fun"}

        essentials = next(g for g in groups if g["name"] == "Essentials")
        assert len(essentials["categories"]) == 2

    def test_get_categories_excludes_hidden(self, temp_db: Database) -> None:
        """Hidden categories excluded by default."""
        temp_db.upsert_category("cat-1", "Visible", "grp-1", "Group")
        temp_db.upsert_category("cat-2", "Hidden", "grp-1", "Group", hidden=True)

        groups = temp_db.get_categories()

        all_cats = [c for g in groups for c in g["categories"]]
        assert len(all_cats) == 1
        assert all_cats[0]["name"] == "Visible"

    def test_get_categories_include_hidden(self, temp_db: Database) -> None:
        """Can include hidden categories."""
        temp_db.upsert_category("cat-1", "Visible", "grp-1", "Group")
        temp_db.upsert_category("cat-2", "Hidden", "grp-1", "Group", hidden=True)

        groups = temp_db.get_categories(include_hidden=True)

        all_cats = [c for g in groups for c in g["categories"]]
        assert len(all_cats) == 2

    def test_get_categories_excludes_deleted(self, temp_db: Database) -> None:
        """Deleted categories excluded by default."""
        temp_db.upsert_category("cat-1", "Active", "grp-1", "Group")
        temp_db.upsert_category("cat-2", "Deleted", "grp-1", "Group", deleted=True)

        groups = temp_db.get_categories()

        all_cats = [c for g in groups for c in g["categories"]]
        assert len(all_cats) == 1
        assert all_cats[0]["name"] == "Active"

    def test_get_category_count(self, temp_db: Database) -> None:
        """Can count categories."""
        assert temp_db.get_category_count() == 0

        temp_db.upsert_category("cat-1", "Cat1", "grp-1", "Group")
        temp_db.upsert_category("cat-2", "Cat2", "grp-1", "Group")

        assert temp_db.get_category_count() == 2

    def test_get_category_count_excludes_hidden(self, temp_db: Database) -> None:
        """Count excludes hidden by default."""
        temp_db.upsert_category("cat-1", "Visible", "grp-1", "Group")
        temp_db.upsert_category("cat-2", "Hidden", "grp-1", "Group", hidden=True)

        assert temp_db.get_category_count() == 1
        assert temp_db.get_category_count(include_hidden=True) == 2
