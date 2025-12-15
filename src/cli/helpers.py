"""Shared CLI helpers for context management and service creation."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from click import Context

    from ..db.database import Database
    from ..services import CategorizerService
    from ..services.sync import SyncService


def format_date_for_display(date_value: str | datetime | None) -> str:
    """Convert date to YYYY-MM-DD string format.

    Args:
        date_value: Date as string, datetime, or None.

    Returns:
        Date string in YYYY-MM-DD format, or empty string if None.
    """
    if date_value is None:
        return ""
    if isinstance(date_value, str):
        return date_value[:10]
    return date_value.strftime("%Y-%m-%d")


def require_data(db: "Database", data_type: str = "transactions") -> bool:
    """Check if database has data, show message if empty.

    Args:
        db: Database instance.
        data_type: Type of data to check ("transactions" or "orders").

    Returns:
        True if data exists, False otherwise (also prints message).
    """
    count_methods = {
        "transactions": db.get_transaction_count,
        "orders": db.get_order_count,
    }
    if count_methods.get(data_type, lambda: 0)() == 0:
        click.echo(click.style(f"No {data_type} in database.", fg="yellow"))
        click.echo("Run 'pull' first to sync data.")
        return False
    return True


def display_pending_changes(pending_changes: list[dict]) -> None:
    """Display pending changes in standardized table format.

    Args:
        pending_changes: List of pending change dictionaries.
    """
    click.echo(f"\nPending changes ({len(pending_changes)}):\n")
    click.echo(f"{'Date':<12} {'Payee':<25} {'Amount':>12}  Change")
    click.echo("-" * 75)
    for change in pending_changes:
        old_cat = change.get("original_category_name") or "Uncategorized"
        new_cat = change.get("new_category_name") or "Split"
        date_str = str(change.get("date", ""))[:10]
        payee = (change.get("payee_name") or "")[:25]
        amount = change.get("amount", 0)
        click.echo(f"{date_str:<12} {payee:<25} {amount:>12.2f}  {old_cat} -> {new_cat}")


def get_categorizer(ctx: Context) -> CategorizerService:
    """Lazily create the categorizer service.

    Args:
        ctx: Click context with config and mock flags.

    Returns:
        CategorizerService instance.
    """
    from ..clients import MockYNABClient, YNABClient
    from ..db.database import Database
    from ..services import CategorizerService

    if "categorizer" not in ctx.obj:
        cfg = ctx.obj["config"]
        mock = ctx.obj.get("mock", False)

        # Use separate database for mock mode
        if mock:
            db_path = cfg.data_dir / "mock_categorizer.db"
        else:
            db_path = cfg.db_path

        db = Database(db_path)

        if mock:
            ynab = MockYNABClient()
            # Mock client needs budget_id set explicitly from config
            ynab.set_budget_id(cfg.ynab.budget_id)
        else:
            ynab = YNABClient(cfg.ynab)

        # Set budget_id on database so transactions are filtered by correct budget
        db.budget_id = ynab.get_current_budget_id()

        categorizer = CategorizerService(
            config=cfg,
            ynab_client=ynab,
            db=db,
        )
        ctx.obj["categorizer"] = categorizer
        ctx.obj["db"] = db

    return ctx.obj["categorizer"]


def get_sync_service(ctx: Context) -> SyncService:
    """Lazily create the sync service.

    Args:
        ctx: Click context with config and mock flags.

    Returns:
        SyncService instance.
    """
    from ..clients import AmazonClient, MockAmazonClient, MockYNABClient, YNABClient
    from ..db.database import Database
    from ..services.sync import SyncService

    if "sync_service" not in ctx.obj:
        cfg = ctx.obj["config"]
        mock = ctx.obj.get("mock", False)

        # Use separate database for mock mode
        if mock:
            db_path = cfg.data_dir / "mock_categorizer.db"
        else:
            db_path = cfg.db_path

        db = Database(db_path)
        ctx.obj["db"] = db

        if mock:
            ynab = MockYNABClient()
            # Mock client needs budget_id set explicitly from config
            ynab.set_budget_id(cfg.ynab.budget_id)
        else:
            ynab = YNABClient(cfg.ynab)

        amazon = None
        if mock:
            amazon = MockAmazonClient()
        elif cfg.amazon.username and cfg.amazon.password:
            amazon = AmazonClient(cfg.amazon, db)

        # Set budget_id on database so transactions are stored with correct budget
        db.budget_id = ynab.get_current_budget_id()

        ctx.obj["sync_service"] = SyncService(db=db, ynab=ynab, amazon=amazon)

    return ctx.obj["sync_service"]
