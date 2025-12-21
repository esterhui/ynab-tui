"""Tests for TUI widget components.

These tests verify that widgets work correctly and don't crash,
using Textual's testing framework.
"""

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container

from ynab_tui.tui.widgets.category_picker import CategoryPicker


@pytest.fixture
def sample_categories():
    """Sample categories for testing."""
    return [
        {"id": "cat-1", "name": "Groceries", "group_name": "Food"},
        {"id": "cat-2", "name": "Restaurants", "group_name": "Food"},
        {"id": "cat-3", "name": "Gas", "group_name": "Transport"},
        {"id": "cat-4", "name": "Parking", "group_name": "Transport"},
        {"id": "cat-5", "name": "Rent", "group_name": "Bills"},
        {"id": "cat-6", "name": "Utilities", "group_name": "Bills"},
    ]


# Test App wrapper for widget testing
class WidgetTestApp(App):
    """Test app for mounting widgets."""

    def __init__(self, widget):
        super().__init__()
        self._widget = widget
        self._selected_result = None
        self._cancelled = False

    def compose(self) -> ComposeResult:
        with Container():
            yield self._widget

    def on_category_picker_category_selected(
        self, message: CategoryPicker.CategorySelected
    ) -> None:
        """Handle category selection."""
        self._selected_result = {
            "category_id": message.category_id,
            "category_name": message.category_name,
        }

    def on_category_picker_cancelled(self, message: CategoryPicker.Cancelled) -> None:
        """Handle cancellation."""
        self._cancelled = True


class TestCategoryPickerMessages:
    """Tests for CategoryPicker message classes."""

    def test_category_selected_message(self):
        """Test CategorySelected message creation."""
        msg = CategoryPicker.CategorySelected(
            category_id="cat-1",
            category_name="Groceries",
        )
        assert msg.category_id == "cat-1"
        assert msg.category_name == "Groceries"

    def test_cancelled_message(self):
        """Test Cancelled message creation."""
        msg = CategoryPicker.Cancelled()
        assert msg is not None


class TestCategoryPickerWidget:
    """Tests for CategoryPicker widget."""

    async def test_widget_mounts_without_crash(self, sample_categories):
        """Test widget mounts successfully."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Widget should be mounted
            assert len(app.query(CategoryPicker)) == 1

    async def test_widget_with_suggested_category(self, sample_categories):
        """Test widget highlights suggested category."""
        picker = CategoryPicker(
            categories=sample_categories,
            suggested_id="cat-3",
        )
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Selected index should be at suggested category
            assert picker._selected_index == 2  # cat-3 is third

    async def test_widget_navigation_down(self, sample_categories):
        """Test navigation down with j key."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            initial_index = picker._selected_index
            await pilot.press("j")
            await pilot.pause()
            # Index should increase (or stay if at end)
            assert picker._selected_index >= initial_index

    async def test_widget_navigation_up(self, sample_categories):
        """Test navigation up with k key doesn't crash."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Move down first
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()

            # Move up - just verify no crash
            await pilot.press("k")
            await pilot.pause()

    async def test_widget_navigation_page_down(self, sample_categories):
        """Test page down navigation."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+d")
            await pilot.pause()
            # Should have moved multiple items
            # Just verify no crash

    async def test_widget_navigation_page_up(self, sample_categories):
        """Test page up navigation."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Move down first
            await pilot.press("ctrl+d")
            await pilot.pause()
            # Then up
            await pilot.press("ctrl+u")
            await pilot.pause()
            # Just verify no crash

    async def test_widget_navigation_to_top(self, sample_categories):
        """Test navigation to top with g key."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Move down
            await pilot.press("j")
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            # Go to top
            await pilot.press("g")
            await pilot.pause()
            assert picker._selected_index == 0

    async def test_widget_navigation_to_bottom(self, sample_categories):
        """Test navigation to bottom with G key doesn't crash."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("G")
            await pilot.pause()
            # Just verify no crash

    async def test_widget_search_filter(self, sample_categories):
        """Test typing to filter categories."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Type to filter
            input_widget = picker.query_one("#search-input")
            input_widget.value = "gro"
            # Trigger the change event
            await pilot.pause()
            # Filtered should contain fewer items
            assert len(picker._filtered_categories) < len(sample_categories)

    async def test_widget_search_filter_by_group(self, sample_categories):
        """Test filtering by group name."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Filter by group name
            input_widget = picker.query_one("#search-input")
            input_widget.value = "food"
            await pilot.pause()
            # Should match Food group items
            assert len(picker._filtered_categories) == 2

    async def test_widget_select_category(self, sample_categories):
        """Test selecting a category with Enter."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Press Enter to select
            await pilot.press("enter")
            await pilot.pause()
            # Should have selected first category
            assert app._selected_result is not None
            assert app._selected_result["category_id"] == "cat-1"
            assert app._selected_result["category_name"] == "Groceries"

    async def test_widget_cancel(self, sample_categories):
        """Test cancelling with Escape."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app._cancelled is True

    async def test_widget_empty_categories(self):
        """Test widget with empty categories list."""
        picker = CategoryPicker(categories=[])
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Should show "no matching categories" message
            assert len(picker._filtered_categories) == 0

    async def test_widget_arrow_navigation(self, sample_categories):
        """Test arrow key navigation."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            idx1 = picker._selected_index
            await pilot.press("up")
            await pilot.pause()
            idx2 = picker._selected_index
            assert idx2 < idx1

    async def test_widget_get_selectable_count(self, sample_categories):
        """Test _get_selectable_count method."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            count = picker._get_selectable_count()
            assert count == len(sample_categories)

    async def test_widget_nav_methods(self, sample_categories):
        """Test NavigationMixin methods."""
        picker = CategoryPicker(categories=sample_categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Test nav methods
            assert picker._nav_get_item_count() == len(sample_categories)
            assert picker._nav_get_current_index() == 0
            picker._nav_set_current_index(2)
            assert picker._nav_get_current_index() == 2

    async def test_widget_categories_without_group(self):
        """Test categories without group_name field."""
        categories = [
            {"id": "cat-1", "name": "Category 1"},
            {"id": "cat-2", "name": "Category 2"},
        ]
        picker = CategoryPicker(categories=categories)
        app = WidgetTestApp(picker)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Should render without errors
            assert len(picker._filtered_categories) == 2
