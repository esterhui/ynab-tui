"""Shared constants for TUI components."""

from textual.binding import Binding

# Vim-style navigation bindings used across multiple TUI components
VIM_NAVIGATION_BINDINGS = [
    Binding("j", "cursor_down", "Down", show=False),
    Binding("k", "cursor_up", "Up", show=False),
    Binding("g", "scroll_home", "Top", show=False),
    Binding("G", "scroll_end", "Bottom", show=False),
    Binding("ctrl+d", "half_page_down", "Half Page Down", show=False),
    Binding("ctrl+u", "half_page_up", "Half Page Up", show=False),
    Binding("ctrl+f", "page_down", "Page Down", show=False),
    Binding("ctrl+b", "page_up", "Page Up", show=False),
]
