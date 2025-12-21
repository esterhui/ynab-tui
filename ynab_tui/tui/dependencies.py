"""Dependency injection for TUI app.

This module provides AppDependencies dataclass that encapsulates
all dependencies the TUI app needs, making it easy to inject
mocks for testing.
"""

from dataclasses import dataclass
from typing import Optional

from ynab_tui.services.categorizer import CategorizerService
from ynab_tui.tui.handlers import ActionHandler


@dataclass
class AppDependencies:
    """All dependencies for the TUI app - easy to mock.

    This container encapsulates all external dependencies that the
    TUI app needs, making it easy to:
    - Inject mock dependencies for testing
    - Configure different behaviors (mock mode, time limits, etc.)
    - Replace individual services without changing the app

    Attributes:
        categorizer: The main categorizer service for transaction operations.
        action_handler: Handler for TUI actions (wraps categorizer).
        is_mock: Whether running in mock mode (no real API calls).
        load_since_months: How far back to load transactions (None = all).
    """

    categorizer: CategorizerService
    action_handler: ActionHandler
    is_mock: bool = False
    load_since_months: Optional[int] = 6

    @classmethod
    def create(
        cls,
        categorizer: CategorizerService,
        is_mock: bool = False,
        load_since_months: Optional[int] = 6,
    ) -> "AppDependencies":
        """Factory method to create dependencies with default handler.

        Args:
            categorizer: The categorizer service to use.
            is_mock: Whether running in mock mode.
            load_since_months: How far back to load transactions.

        Returns:
            AppDependencies instance with action handler configured.
        """
        return cls(
            categorizer=categorizer,
            action_handler=ActionHandler(categorizer),
            is_mock=is_mock,
            load_since_months=load_since_months,
        )

    @classmethod
    def create_for_testing(
        cls,
        categorizer: Optional[CategorizerService] = None,
        action_handler: Optional[ActionHandler] = None,
    ) -> "AppDependencies":
        """Factory method for testing with optional mock components.

        Use this when you want to provide mock categorizer/handler
        for testing without real database or API calls.

        Args:
            categorizer: Mock categorizer service (or None).
            action_handler: Mock action handler (or None).

        Returns:
            AppDependencies for testing (may have None values).
        """
        if categorizer is not None and action_handler is None:
            action_handler = ActionHandler(categorizer)

        # Type ignore since we're allowing None for testing
        return cls(
            categorizer=categorizer,  # type: ignore[arg-type]
            action_handler=action_handler,  # type: ignore[arg-type]
            is_mock=True,
            load_since_months=None,
        )
