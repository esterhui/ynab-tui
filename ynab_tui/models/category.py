"""Category models for YNAB Categorizer."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Category:
    """Represents a YNAB category."""

    id: str
    name: str
    group_id: str
    group_name: str

    # Budget info (optional)
    budgeted: Optional[float] = None
    activity: Optional[float] = None
    balance: Optional[float] = None

    # Metadata
    hidden: bool = False
    deleted: bool = False
    note: Optional[str] = None

    @property
    def full_name(self) -> str:
        """Category name with group prefix."""
        return f"{self.group_name}: {self.name}"

    @property
    def is_available(self) -> bool:
        """Check if category is usable (not hidden or deleted)."""
        return not self.hidden and not self.deleted


@dataclass
class CategoryGroup:
    """A group of related categories in YNAB."""

    id: str
    name: str
    categories: list[Category] = field(default_factory=list)
    hidden: bool = False
    deleted: bool = False

    @property
    def available_categories(self) -> list[Category]:
        """Get only available (non-hidden, non-deleted) categories."""
        return [c for c in self.categories if c.is_available]


@dataclass
class CategoryList:
    """Collection of all available YNAB categories."""

    groups: list[CategoryGroup] = field(default_factory=list)

    def all_categories(self) -> list[Category]:
        """Get all categories across all groups."""
        categories = []
        for group in self.groups:
            categories.extend(group.categories)
        return categories

    def available_categories(self) -> list[Category]:
        """Get all available (non-hidden, non-deleted) categories."""
        categories = []
        for group in self.groups:
            if not group.hidden and not group.deleted:
                categories.extend(group.available_categories)
        return categories

    def find_by_id(self, category_id: str) -> Optional[Category]:
        """Find a category by its ID."""
        for category in self.all_categories():
            if category.id == category_id:
                return category
        return None

    def find_by_name(self, name: str) -> Optional[Category]:
        """Find a category by its name (case-insensitive)."""
        name_lower = name.lower()
        for category in self.all_categories():
            if category.name.lower() == name_lower:
                return category
        return None

    def search(self, query: str) -> list[Category]:
        """Search categories by name (case-insensitive, partial match)."""
        query_lower = query.lower()
        return [
            c
            for c in self.available_categories()
            if query_lower in c.name.lower() or query_lower in c.group_name.lower()
        ]
