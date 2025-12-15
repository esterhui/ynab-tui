"""Category filter modal using FuzzySelectModal base."""

from dataclasses import dataclass

from .fuzzy_select import FuzzySelectModal


@dataclass
class CategoryFilterResult:
    """Result of category filter selection."""

    category_id: str
    category_name: str


class CategoryFilterModal(FuzzySelectModal[CategoryFilterResult]):
    """Fuzzy search modal for filtering transactions by category.

    Shows categories with group names: [Group] Category Name
    Returns CategoryFilterResult with id and name, or None on cancel.
    """

    def __init__(self, categories: list[dict], **kwargs) -> None:
        """Initialize the category filter modal.

        Args:
            categories: List of category dicts with id, name, group_name keys.
        """
        super().__init__(
            items=categories,
            display_fn=self._format_category,
            search_fn=self._search_text,
            result_fn=self._make_result,
            placeholder="Filter by category...",
            title="Select Category Filter",
            **kwargs,
        )

    @staticmethod
    def _format_category(cat: dict) -> str:
        """Format category for display: [Group] Name."""
        group = cat.get("group_name", "")
        name = cat["name"]
        if group:
            return f"[dim]\\[{group}][/dim] {name}"
        return name

    @staticmethod
    def _search_text(cat: dict) -> str:
        """Extract searchable text from category."""
        group = cat.get("group_name", "")
        name = cat["name"]
        return f"{group} {name}"

    @staticmethod
    def _make_result(cat: dict) -> CategoryFilterResult:
        """Create result from selected category."""
        return CategoryFilterResult(
            category_id=cat["id"],
            category_name=cat["name"],
        )
