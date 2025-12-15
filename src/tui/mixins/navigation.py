"""Navigation mixins for vim-style list navigation."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import ListView


class ListViewNavigationMixin:
    """Mixin providing vim-style navigation for ListView widgets.

    Simpler than NavigationMixin - just delegates to ListView methods.
    Subclasses must implement _get_list_view() -> ListView | None.
    """

    def _get_list_view(self) -> "ListView | None":
        """Override in subclass to return the ListView to navigate."""
        raise NotImplementedError("Subclass must implement _get_list_view")

    def action_cursor_down(self) -> None:
        """Move cursor down."""
        if lv := self._get_list_view():
            lv.action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up."""
        if lv := self._get_list_view():
            lv.action_cursor_up()

    def action_scroll_home(self) -> None:
        """Scroll to top (vim g key)."""
        if lv := self._get_list_view():
            lv.index = 0

    def action_scroll_end(self) -> None:
        """Scroll to bottom (vim G key)."""
        if lv := self._get_list_view():
            lv.index = len(lv) - 1 if len(lv) > 0 else 0

    def action_half_page_down(self) -> None:
        """Half page down (Ctrl+d)."""
        if lv := self._get_list_view():
            lv.index = min((lv.index or 0) + 10, len(lv) - 1)

    def action_half_page_up(self) -> None:
        """Half page up (Ctrl+u)."""
        if lv := self._get_list_view():
            lv.index = max((lv.index or 0) - 10, 0)

    def action_page_down(self) -> None:
        """Full page down (Ctrl+f)."""
        if lv := self._get_list_view():
            lv.index = min((lv.index or 0) + 20, len(lv) - 1)

    def action_page_up(self) -> None:
        """Full page up (Ctrl+b)."""
        if lv := self._get_list_view():
            lv.index = max((lv.index or 0) - 20, 0)


class NavigationMixin:
    """Mixin providing vim-style navigation for list-based widgets.

    Subclasses must implement:
    - _nav_get_item_count(): Return total number of navigable items
    - _nav_get_current_index(): Return current cursor/selection index
    - _nav_set_current_index(index): Set cursor/selection index
    - _nav_on_index_changed(): Called after index changes (for refresh/scroll)
    """

    # Page navigation step sizes
    HALF_PAGE_SIZE = 10
    FULL_PAGE_SIZE = 20

    def _nav_get_item_count(self) -> int:
        """Return total number of navigable items. Override in subclass."""
        raise NotImplementedError("Subclass must implement _nav_get_item_count")

    def _nav_get_current_index(self) -> int:
        """Return current cursor/selection index. Override in subclass."""
        raise NotImplementedError("Subclass must implement _nav_get_current_index")

    def _nav_set_current_index(self, index: int) -> None:
        """Set cursor/selection index. Override in subclass."""
        raise NotImplementedError("Subclass must implement _nav_set_current_index")

    def _nav_on_index_changed(self) -> None:
        """Called after index changes to refresh display. Override in subclass."""
        raise NotImplementedError("Subclass must implement _nav_on_index_changed")

    def action_cursor_down(self) -> None:
        """Move cursor down."""
        current = self._nav_get_current_index()
        max_index = self._nav_get_item_count() - 1
        if current < max_index:
            self._nav_set_current_index(current + 1)
            self._nav_on_index_changed()

    def action_cursor_up(self) -> None:
        """Move cursor up."""
        current = self._nav_get_current_index()
        if current > 0:
            self._nav_set_current_index(current - 1)
            self._nav_on_index_changed()

    def action_scroll_home(self) -> None:
        """Scroll to top (vim g key)."""
        if self._nav_get_current_index() != 0:
            self._nav_set_current_index(0)
            self._nav_on_index_changed()

    def action_scroll_end(self) -> None:
        """Scroll to bottom (vim G key)."""
        last_index = self._nav_get_item_count() - 1
        if self._nav_get_current_index() != last_index:
            self._nav_set_current_index(last_index)
            self._nav_on_index_changed()

    def action_half_page_down(self) -> None:
        """Half page down (Ctrl+d)."""
        current = self._nav_get_current_index()
        max_index = self._nav_get_item_count() - 1
        new_index = min(current + self.HALF_PAGE_SIZE, max_index)
        if new_index != current:
            self._nav_set_current_index(new_index)
            self._nav_on_index_changed()

    def action_half_page_up(self) -> None:
        """Half page up (Ctrl+u)."""
        current = self._nav_get_current_index()
        new_index = max(current - self.HALF_PAGE_SIZE, 0)
        if new_index != current:
            self._nav_set_current_index(new_index)
            self._nav_on_index_changed()

    def action_page_down(self) -> None:
        """Full page down (Ctrl+f)."""
        current = self._nav_get_current_index()
        max_index = self._nav_get_item_count() - 1
        new_index = min(current + self.FULL_PAGE_SIZE, max_index)
        if new_index != current:
            self._nav_set_current_index(new_index)
            self._nav_on_index_changed()

    def action_page_up(self) -> None:
        """Full page up (Ctrl+b)."""
        current = self._nav_get_current_index()
        new_index = max(current - self.FULL_PAGE_SIZE, 0)
        if new_index != current:
            self._nav_set_current_index(new_index)
            self._nav_on_index_changed()
