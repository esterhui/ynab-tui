"""Main entry point for YNAB Categorizer.

Provides both TUI and CLI interfaces for transaction categorization.
"""

import os
from pathlib import Path

import click

from . import __version__
from .cli import (
    display_amazon_match_results,
    display_pending_changes,
    format_date_for_display,
    get_categorizer,
    get_sync_service,
    require_data,
)
from .clients import AmazonClient
from .config import load_config
from .services import CategorizerService
from .utils import is_amazon_payee

# Template for config.toml created by 'ynab-tui init'
CONFIG_TEMPLATE = """\
# YNAB TUI Configuration
# Documentation: https://github.com/esterhui/ynab-tui

[ynab]
# Get your API token from https://app.ynab.com/settings/developer
api_token = ""  # or set YNAB_API_TOKEN environment variable
budget_id = "last-used"

[amazon]
# Amazon credentials for order history scraping (optional)
username = ""  # or set AMAZON_USERNAME environment variable
password = ""  # or set AMAZON_PASSWORD environment variable
otp_secret = ""  # TOTP secret for 2FA (optional)

# For all configuration options, see:
# https://github.com/esterhui/ynab-tui/blob/main/config.example.toml
"""


def _has_credentials_configured(cfg) -> bool:
    """Check if any credentials are configured (config file or env vars)."""
    return bool(cfg.ynab.api_token)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="ynab-tui")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to config.toml")
@click.option("--budget", "-b", type=str, help="Budget name to use (default: last-used)")
@click.option("--mock", is_flag=True, help="Use mock mode (mock DB, YNAB, Amazon clients)")
@click.option("--mouse", is_flag=True, help="Enable mouse support in TUI (default: keyboard-only)")
@click.option(
    "--load-since-months",
    type=int,
    default=6,
    help="Load transactions from the last N months (default: 6, use 0 for all)",
)
@click.pass_context
def main(ctx, config, budget, mock, mouse, load_since_months):
    """YNAB TUI - transaction categorization with Amazon order matching.

    Categorize YNAB transactions using Amazon order history for intelligent matching.
    """
    config_path = Path(config) if config else None
    cfg = load_config(config_path)

    # Override budget from command line if specified
    budget_specified = budget is not None
    if budget:
        cfg.ynab.budget_id = budget

    # Store in context for subcommands (lazy initialization)
    ctx.ensure_object(dict)
    ctx.obj["config"] = cfg
    ctx.obj["mock"] = mock
    ctx.obj["budget_specified"] = budget_specified  # Track if --budget was explicitly used

    # If no subcommand, launch TUI
    if ctx.invoked_subcommand is None:
        # Show first-run guidance if no credentials configured and not in mock mode
        if not mock and not _has_credentials_configured(cfg):
            config_file = cfg.data_dir / "config.toml"
            click.echo(click.style("No YNAB credentials configured.", fg="yellow"))
            click.echo()
            if not config_file.exists():
                click.echo("To get started:")
                click.echo("  1. Run: ynab-tui init")
                click.echo(f"  2. Edit {config_file} with your YNAB API token")
            else:
                click.echo(f"Edit {config_file} to add your YNAB API token")
                click.echo("Or set the YNAB_API_TOKEN environment variable")
            click.echo()
            click.echo("Get your API token from: https://app.ynab.com/settings/developer")
            click.echo()
            click.echo("To try without credentials: ynab-tui --mock")
            return

        categorizer = get_categorizer(ctx)
        from .tui.app import YNABCategorizerApp

        # Convert load_since_months=0 to None (load all transactions)
        months = load_since_months if load_since_months > 0 else None
        app = YNABCategorizerApp(categorizer, is_mock=mock, load_since_months=months)
        app.run(mouse=mouse)


def _set_secure_permissions(path: Path) -> None:
    """Set file permissions to owner read/write only (600)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows doesn't support chmod the same way


@main.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing config file")
@click.pass_context
def init_config(ctx, force):
    """Initialize configuration file and database.

    Creates ~/.config/ynab-tui/config.toml with a template configuration
    and initializes the database files with secure permissions.

    \b
    Examples:
        ynab-tui init           # Create config file and databases
        ynab-tui init --force   # Overwrite existing config
    """
    cfg = ctx.obj["config"]
    config_dir = cfg.data_dir
    config_file = config_dir / "config.toml"
    prod_db = cfg.db_path
    mock_db = config_dir / "mock_categorizer.db"

    # Check if config already exists
    if config_file.exists() and not force:
        click.echo(click.style(f"Config file already exists: {config_file}", fg="yellow"))
        click.echo("Use --force to overwrite")
        return

    # Create config directory if needed (should already exist from load_config)
    config_dir.mkdir(parents=True, exist_ok=True)

    # Write config template with secure permissions
    config_file.write_text(CONFIG_TEMPLATE)
    _set_secure_permissions(config_file)

    # Create database files with secure permissions if they don't exist
    # SQLite will use these files and preserve their permissions
    dbs_created = []
    for db_file in [prod_db, mock_db]:
        if not db_file.exists():
            db_file.touch()
            _set_secure_permissions(db_file)
            dbs_created.append(db_file.name)

    click.echo(click.style("Initialized ynab-tui:", fg="green"))
    click.echo(f"  Config: {config_file}")
    if dbs_created:
        click.echo(f"  Databases: {', '.join(dbs_created)} (secure permissions)")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Get your YNAB API token from https://app.ynab.com/settings/developer")
    click.echo(f"  2. Edit {config_file} to add your token")
    click.echo("  3. Run: ynab-tui pull --full")
    click.echo()
    click.echo("Amazon credentials are optional (for Amazon order matching).")


@main.command("uncategorized")
@click.pass_context
def uncategorized(ctx):
    """List uncategorized transactions from local database.

    Run 'pull' first to sync data from YNAB.
    """
    categorizer: CategorizerService = get_categorizer(ctx)

    click.echo("Fetching uncategorized transactions from database...")
    batch = categorizer.get_pending_transactions()

    if not batch.transactions:
        click.echo("No uncategorized transactions found.")
        click.echo("Run 'pull' first to sync data from YNAB.")
        return

    click.echo(f"\nFound {batch.total_count} uncategorized transactions:")
    click.echo(f"  - Amazon: {batch.amazon_count}")
    click.echo(f"  - Other: {batch.other_count}")
    click.echo()

    for txn in batch.transactions:
        marker = "[AMZ] " if txn.is_amazon else "      "
        payee = txn.payee_name[:25].ljust(25)
        click.echo(f"{marker}{txn.display_date}  {payee}  {txn.display_amount:>12}")
        if txn.enrichment_summary:
            click.echo(f"        ↳ {txn.enrichment_summary}")


@main.command("ynab-categories")
@click.option("--csv", "csv_file", type=click.Path(), help="Export to CSV file")
@click.pass_context
def ynab_categories(ctx, csv_file):
    """List available YNAB categories from local database."""
    import csv

    sync_service = get_sync_service(ctx)
    db = sync_service._db

    groups = db.get_categories()

    if not groups:
        click.echo("No categories in database. Run 'pull' first.")
        return

    # CSV export
    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "group_id",
                    "group_name",
                    "category_id",
                    "budget_id",
                    "category_name",
                    "hidden",
                    "deleted",
                ]
            )
            for group in groups:
                for cat in group["categories"]:
                    writer.writerow(
                        [
                            group["id"],
                            group["name"],
                            cat["id"],
                            cat.get("budget_id") or "",
                            cat["name"],
                            str(cat["hidden"]).lower(),
                            str(cat["deleted"]).lower(),
                        ]
                    )
        click.echo(f"Exported {db.get_category_count()} categories to {csv_file}")
        return

    # Normal display
    total = 0
    for group in groups:
        click.echo(f"\n[{group['name']}]")
        for cat in group["categories"]:
            click.echo(f"  - {cat['name']}")
            total += 1

    click.echo(f"\nTotal: {total} categories")


@main.command("ynab-test")
@click.pass_context
def ynab_test(ctx):
    """Test YNAB API connection."""
    from .clients import YNABClient

    if ctx.obj.get("mock"):
        click.echo(
            click.style("Note: --mock flag ignored (this command tests live API)", fg="yellow")
        )

    cfg = ctx.obj["config"]

    click.echo("Testing YNAB API connection...")

    try:
        client = YNABClient(cfg.ynab)
        result = client.test_connection()

        if result["success"]:
            click.echo(click.style("✓ Connection successful!", fg="green"))
            click.echo(f"  User ID: {result['user_id']}")

            # Also test budget access
            budgets = client.get_budgets()
            click.echo(f"  Budgets accessible: {len(budgets)}")
        else:
            click.echo(click.style("✗ Connection failed!", fg="red"))
            click.echo(f"  Error: {result['error']}")

    except Exception as e:
        click.echo(click.style(f"✗ Error: {e}", fg="red"))


@main.command("ynab-budgets")
@click.option("--show-ids", is_flag=True, help="Show budget UUIDs (hidden by default)")
@click.pass_context
def ynab_budgets(ctx, show_ids):
    """List available YNAB budgets and show which is selected.

    Use --budget "Budget Name" with any command to select a different budget.
    """
    from .clients import YNABClient

    if ctx.obj.get("mock"):
        click.echo(
            click.style("Note: --mock flag ignored (this command tests live API)", fg="yellow")
        )

    cfg = ctx.obj["config"]

    click.echo("Fetching budgets from YNAB...")

    try:
        client = YNABClient(cfg.ynab)
        budget_list = client.get_budgets()

        if not budget_list:
            click.echo("No budgets found!")
            return

        # Sort by last_modified_on (newest first) to match "last-used" logic
        budget_list.sort(
            key=lambda b: b["last_modified_on"] or "",
            reverse=True,
        )

        # Determine which budget is selected (resolve name if needed)
        if cfg.ynab.budget_id == "last-used":
            selected_id = budget_list[0]["id"]  # Most recently modified
            selection_mode = "last-used"
        else:
            # Could be a name or UUID - find the matching budget
            selected_id = None
            for b in budget_list:
                if b["id"] == cfg.ynab.budget_id or b["name"].lower() == cfg.ynab.budget_id.lower():
                    selected_id = b["id"]
                    break
            if not selected_id:
                selected_id = cfg.ynab.budget_id  # Will show as not found
            selection_mode = "configured"

        click.echo(f"\nFound {len(budget_list)} budget(s):\n")

        # Table header
        if show_ids:
            click.echo(f"  {'':3} {'Name':<30} {'Last Modified':<12} {'ID'}")
            click.echo(f"  {'-' * 3} {'-' * 30} {'-' * 12} {'-' * 36}")
        else:
            click.echo(f"  {'':3} {'Name':<30} {'Last Modified'}")
            click.echo(f"  {'-' * 3} {'-' * 30} {'-' * 12}")

        for b in budget_list:
            modified_on = b["last_modified_on"]
            if modified_on:
                if hasattr(modified_on, "strftime"):
                    modified = modified_on.strftime("%Y-%m-%d")
                else:
                    modified = str(modified_on)[:10]
            else:
                modified = "unknown"

            # Mark selected budget
            if b["id"] == selected_id:
                marker = click.style("→", fg="green", bold=True)
                name = click.style(b["name"][:30], fg="green", bold=True)
            else:
                marker = " "
                name = b["name"][:30]

            if show_ids:
                click.echo(f"  {marker:3} {name:<30} {modified:<12} {b['id']}")
            else:
                click.echo(f"  {marker:3} {name:<30} {modified}")

        # Show selected budget name
        selected_name = next((b["name"] for b in budget_list if b["id"] == selected_id), "Unknown")
        click.echo(f"\n  Selected: {click.style(selected_name, fg='green')} ({selection_mode})")
        click.echo(f'\n  Tip: Use --budget "{selected_name}" to select a different budget')

    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"))


@main.command("ynab-unapproved")
@click.option("--csv", "csv_file", type=click.Path(), help="Export to CSV file")
@click.pass_context
def ynab_unapproved(ctx, csv_file):
    """List unapproved transactions from local database.

    Run 'pull' first to sync data from YNAB.
    """
    import csv

    sync_service = get_sync_service(ctx)
    db = sync_service._db

    # Check if we have data
    if not require_data(db, "transactions"):
        return

    if not csv_file:
        click.echo("Querying unapproved transactions from database...")

    txns = db.get_ynab_transactions(unapproved_only=True)

    if not txns:
        click.echo("No unapproved transactions found!")
        return

    # CSV export
    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "id",
                    "date",
                    "amount",
                    "payee_name",
                    "category_id",
                    "category_name",
                    "account_name",
                    "memo",
                    "approved",
                    "cleared",
                ]
            )
            for txn in txns:
                writer.writerow(
                    [
                        txn["id"],
                        format_date_for_display(txn["date"]),
                        txn["amount"],
                        txn.get("payee_name") or "",
                        txn.get("category_id") or "",
                        txn.get("category_name") or "",
                        txn.get("account_name") or "",
                        txn.get("memo") or "",
                        str(txn.get("approved", False)).lower(),
                        txn.get("cleared") or "",
                    ]
                )
        click.echo(f"Exported {len(txns)} unapproved transactions to {csv_file}")
        return

    # Normal display
    click.echo(f"\nFound {len(txns)} unapproved transaction(s):\n")

    for txn in txns:
        # Format category indicator
        is_uncategorized = not txn.get("category_id")
        cat_indicator = "[?]" if is_uncategorized else "   "

        # Format category
        cat_name = txn.get("category_name") or "Uncategorized"
        cat = cat_name[:15].ljust(15)

        # Format date and amount
        date_str = format_date_for_display(txn["date"])
        amount = txn["amount"]
        display_amount = f"-${abs(amount):,.2f}" if amount < 0 else f"${amount:,.2f}"

        payee = (txn.get("payee_name") or "")[:25].ljust(25)
        click.echo(f"{cat_indicator} {date_str}  {payee}  {display_amount:>12}  {cat}")


@main.command("amazon-test")
@click.pass_context
def amazon_test(ctx):
    """Test Amazon connection and authentication."""
    from .clients import AmazonClientError

    if ctx.obj.get("mock"):
        click.echo(
            click.style("Note: --mock flag ignored (this command tests live API)", fg="yellow")
        )

    cfg = ctx.obj["config"]

    click.echo("Testing Amazon connection...")

    if not cfg.amazon.username or not cfg.amazon.password:
        click.echo(click.style("✗ Amazon credentials not configured!", fg="red"))
        click.echo("  Set AMAZON_USERNAME and AMAZON_PASSWORD environment variables")
        click.echo("  or configure in config.toml")
        return

    click.echo(f"  Username: {cfg.amazon.username}")
    click.echo(f"  OTP Secret: {'configured' if cfg.amazon.otp_secret else 'not set'}")

    try:
        client = AmazonClient(cfg.amazon)
        click.echo("  Attempting login...")

        # Try to fetch recent orders to verify connection
        orders = client.get_recent_orders(days=30)

        click.echo(click.style("✓ Connection successful!", fg="green"))
        click.echo(f"  Orders in last 30 days: {len(orders)}")

        if orders:
            click.echo("  Recent orders:")
            for order in orders[:5]:
                items = ", ".join(order.item_names[:2])
                if len(order.item_names) > 2:
                    items += f" (+{len(order.item_names) - 2} more)"
                click.echo(
                    f"    {order.order_date.strftime('%Y-%m-%d')}  ${order.total:>8.2f}  {items[:40]}"
                )

    except AmazonClientError as e:
        click.echo(click.style(f"✗ Connection failed: {e}", fg="red"))
    except Exception as e:
        click.echo(click.style(f"✗ Error: {e}", fg="red"))


@main.command("db-amazon-orders")
@click.option(
    "--days", "-d", type=int, default=30, help="Query orders from last N days (default: 30)"
)
@click.option("--year", "-y", type=int, help="Query orders for specific year")
@click.option("--csv", "csv_file", type=click.Path(), help="Export to CSV file")
@click.pass_context
def db_amazon_orders(ctx, days, year, csv_file):
    """List or export Amazon orders from local database.

    Run 'pull' first to sync data from Amazon.
    """
    import csv
    from datetime import datetime, timedelta

    sync_service = get_sync_service(ctx)
    db = sync_service._db

    # Check if we have data
    if not require_data(db, "orders"):
        return

    if year:
        if not csv_file:
            click.echo(f"Querying orders for {year} from database...")
        orders = db.get_cached_orders_for_year(year)
    else:
        if not csv_file:
            click.echo(f"Querying orders from last {days} days from database...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        orders = db.get_cached_orders_by_date_range(start_date, end_date)

    if not orders:
        click.echo("No orders found for the specified criteria!")
        return

    # CSV export
    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["order_id", "order_date", "total", "items"])
            for order in orders:
                # Get items with prices from amazon_order_items table
                items_with_prices = db.get_amazon_order_items_with_prices(order.order_id)
                if items_with_prices:
                    # Format as "item_name|price ||| item_name|price" for mock client parsing
                    # Uses " ||| " as separator since item names can contain "; "
                    item_parts = []
                    for item in items_with_prices:
                        name = item["item_name"]
                        price = item.get("item_price")
                        if price is not None:
                            item_parts.append(f"{name}|{price}")
                        else:
                            item_parts.append(name)
                    items_str = " ||| ".join(item_parts)
                else:
                    # Fallback to just names if no items in amazon_order_items
                    items_str = " ||| ".join(order.items)
                writer.writerow(
                    [
                        order.order_id,
                        order.order_date.strftime("%Y-%m-%d"),
                        order.total,
                        items_str,
                    ]
                )
        click.echo(f"Exported {len(orders)} orders to {csv_file}")
        return

    # Normal display
    click.echo(f"\nFound {len(orders)} order(s):\n")

    for order in orders:
        # Get items with prices
        items_with_prices = db.get_amazon_order_items_with_prices(order.order_id)

        # Format header line
        click.echo(
            f"  {order.order_date.strftime('%Y-%m-%d')}  ${order.total:>8.2f}  {order.order_id}"
        )

        if items_with_prices:
            for item in items_with_prices:
                name = item["item_name"][:60]
                price = item.get("item_price")
                if price is not None:
                    click.echo(f"                          ${price:>8.2f}  {name}")
                else:
                    click.echo(f"                                     {name}")
        elif order.items:
            for item_name in order.items[:5]:
                click.echo(f"                                     {item_name[:60]}")
            if len(order.items) > 5:
                click.echo(f"                                     (+{len(order.items) - 5} more)")
        click.echo()  # Blank line between orders


@main.command("amazon-match")
@click.option("-v", "--verbose", is_flag=True, help="Show each item with predicted category")
@click.pass_context
def amazon_match(ctx, verbose):
    """Match unapproved Amazon transactions to Amazon orders.

    Uses local database to match unapproved transactions to cached orders
    by amount (within $0.10) and date. Uses two-stage matching:
    - Stage 1: Strict 7-day window
    - Stage 2: Extended 24-day window for remaining unmatched

    Detects and reports duplicate matches (same order matching multiple transactions).

    Run 'pull' first to sync data from YNAB and Amazon.
    """
    from .services.amazon_matcher import AmazonOrderMatcher

    cfg = ctx.obj["config"]
    sync_service = get_sync_service(ctx)
    db = sync_service._db

    # Check if we have data
    if not require_data(db, "transactions"):
        return

    # Step 1: Get ALL Amazon transactions from DB (including approved)
    # This ensures proper duplicate detection - approved transactions have already
    # claimed their orders and shouldn't be re-matched to new transactions
    click.echo("Querying Amazon transactions from database...")
    amazon_patterns = cfg.payees.amazon_patterns
    txns = db.get_ynab_transactions()
    amazon_txns = [t for t in txns if is_amazon_payee(t.get("payee_name", ""), amazon_patterns)]

    if not amazon_txns:
        click.echo("No Amazon transactions found in database.")
        return

    # Count approved vs unapproved
    approved_count = sum(1 for t in amazon_txns if t.get("approved", False))
    unapproved_count = len(amazon_txns) - approved_count
    click.echo(
        f"Found {len(amazon_txns)} Amazon transactions "
        f"({unapproved_count} unapproved, {approved_count} approved)."
    )

    # Step 3: Create matcher and normalize transactions
    matcher = AmazonOrderMatcher(db)
    txn_infos = [
        matcher.normalize_transaction(t)
        for t in sorted(amazon_txns, key=lambda t: t["date"], reverse=True)
    ]

    # Get date range for display
    earliest_date = min(t.date for t in txn_infos)
    latest_date = max(t.date for t in txn_infos)
    click.echo(
        f"Date range: {earliest_date.strftime('%Y-%m-%d')} to {latest_date.strftime('%Y-%m-%d')}"
    )

    # Step 4: Get orders from database cache
    click.echo("Querying Amazon orders from database cache...")
    orders = matcher.get_orders_for_date_range(txn_infos)

    if not orders:
        click.echo(click.style("No Amazon orders in database for this date range.", fg="yellow"))
        click.echo("Run 'pull' to sync Amazon orders.")
        return

    click.echo(f"Found {len(orders)} Amazon orders in cache.\n")

    # Step 5: Get all Amazon transactions for reverse matching
    all_amazon_txns = [
        matcher.normalize_transaction(t)
        for t in db.get_ynab_transactions()
        if is_amazon_payee(t.get("payee_name", ""), amazon_patterns)
    ]

    # Step 6: Run matching
    result = matcher.match_transactions(txn_infos, orders, all_amazon_txns)

    # === DISPLAY SECTION ===
    mapping_service = None
    if verbose:
        from .services.category_mapping import CategoryMappingService

        mapping_service = CategoryMappingService(db, payees_config=cfg.payees)

    display_amazon_match_results(
        result, matcher.stage1_window, matcher.stage2_window, verbose, mapping_service
    )


# =============================================================================
# Pull/Push Commands (Git-style sync)
# =============================================================================


@main.command("pull")
@click.option("--full", is_flag=True, help="Full pull instead of incremental")
@click.option("--ynab-only", is_flag=True, help="Only pull YNAB transactions")
@click.option("--amazon-only", is_flag=True, help="Only pull Amazon orders")
@click.option("--amazon-year", type=int, help="Specific year for Amazon orders")
@click.option(
    "--since-days",
    type=int,
    help="Only fetch Amazon orders from the last N days (ignores sync state)",
)
@click.pass_context
def pull(ctx, full, ynab_only, amazon_only, amazon_year, since_days):
    """Pull data from YNAB and Amazon to local database.

    Downloads categories, transactions and orders to local SQLite for offline
    analysis and categorization. Uses incremental sync by default (7-day overlap).

    When --budget is specified, only YNAB data is pulled (Amazon orders are not
    budget-specific).
    """
    config = ctx.obj["config"]
    sync_overlap_days = config.categorization.sync_overlap_days

    # If --budget was specified, imply --ynab-only (Amazon isn't budget-specific)
    budget_specified = ctx.obj.get("budget_specified", False)
    if budget_specified and not amazon_only:
        if not ynab_only:
            click.echo(
                click.style(
                    "Note: --budget specified, pulling YNAB data only "
                    "(Amazon orders are not budget-specific)",
                    fg="cyan",
                )
            )
        ynab_only = True

    sync_service = get_sync_service(ctx)

    # Show which budget we're pulling for
    if not amazon_only:
        try:
            budget_name = sync_service._ynab.get_budget_name()
            click.echo(f"Budget: {click.style(budget_name, fg='green')}\n")
        except Exception:
            pass  # Skip if we can't get budget name yet

    results = {}

    # Pull categories (always, unless amazon-only)
    if not amazon_only:
        click.echo("Pulling YNAB categories...")
        result = sync_service.pull_categories()
        results["categories"] = result

        if result.success:
            click.echo(click.style(f"  ✓ Fetched {result.fetched} categories", fg="green"))
            click.echo(f"    Inserted: {result.inserted}, Updated: {result.updated}")
            click.echo(f"    Total in database: {result.total}")
        else:
            click.echo(click.style(f"  ✗ Error: {result.errors}", fg="red"))

    # Pull YNAB transactions
    if not amazon_only:
        click.echo("\nPulling YNAB transactions...")
        ynab_state = sync_service._db.get_sync_state("ynab")
        if ynab_state and ynab_state.get("last_sync_at") and not full:
            from datetime import timedelta

            click.echo(f"  Last sync: {ynab_state['last_sync_at'].strftime('%Y-%m-%d %H:%M')}")
            since_date = (
                ynab_state["last_sync_date"] - timedelta(days=sync_overlap_days)
                if ynab_state.get("last_sync_date")
                else "all"
            )
            click.echo(f"  Fetching since: {since_date}")
        elif full:
            click.echo("  Full sync requested")
        else:
            click.echo("  First sync - fetching all transactions")

        result = sync_service.pull_ynab(full=full)
        results["ynab"] = result

        if result.success:
            click.echo(click.style(f"  ✓ Fetched {result.fetched} transactions", fg="green"))
            if result.oldest_date and result.newest_date:
                click.echo(
                    f"    Date range: {result.oldest_date.strftime('%Y-%m-%d')} to {result.newest_date.strftime('%Y-%m-%d')}"
                )
            click.echo(f"    Inserted: {result.inserted}, Updated: {result.updated}")
            click.echo(f"    Total in database: {result.total}")
        else:
            click.echo(click.style(f"  ✗ Error: {result.errors}", fg="red"))

    # Pull Amazon
    if not ynab_only:
        mock = ctx.obj.get("mock", False)
        has_amazon_creds = mock or (config.amazon.username and config.amazon.password)

        if not has_amazon_creds:
            if amazon_only:
                # User explicitly requested Amazon-only but no credentials
                click.echo(click.style("\nError: Amazon credentials not configured.", fg="red"))
                click.echo("Set AMAZON_USERNAME and AMAZON_PASSWORD environment variables")
                click.echo("or configure in config.toml")
                return
            else:
                # Just skip Amazon with informational message
                click.echo("\nSkipping Amazon (no credentials configured)")
        else:
            click.echo("\nPulling Amazon orders...")
            amazon_state = sync_service._db.get_sync_state("amazon")
            if amazon_year:
                click.echo(f"  Fetching year: {amazon_year}")
            elif since_days:
                click.echo(f"  Fetching last {since_days} days")
            elif full:
                click.echo("  Full sync requested")
            elif amazon_state and amazon_state.get("last_sync_at"):
                from datetime import datetime as dt
                from datetime import timedelta

                click.echo(
                    f"  Last sync: {amazon_state['last_sync_at'].strftime('%Y-%m-%d %H:%M')}"
                )
                days_since = (dt.now() - amazon_state["last_sync_date"]).days + sync_overlap_days
                since_date = dt.now() - timedelta(days=days_since)
                click.echo(f"  Fetching since: {since_date.strftime('%Y-%m-%d')}")
            else:
                click.echo("  First sync - fetching all orders")

            result = sync_service.pull_amazon(full=full, year=amazon_year, since_days=since_days)
            results["amazon"] = result

            if result.success:
                click.echo(click.style(f"  ✓ Fetched {result.fetched} orders", fg="green"))
                if result.oldest_date and result.newest_date:
                    click.echo(
                        f"    Date range: {result.oldest_date.strftime('%Y-%m-%d')} to {result.newest_date.strftime('%Y-%m-%d')}"
                    )
                click.echo(f"    Inserted: {result.inserted}, Updated: {result.updated}")
                click.echo(f"    Total in database: {result.total}")
            else:
                click.echo(click.style(f"  ✗ Error: {result.errors}", fg="red"))

    click.echo("\nPull complete!")


@main.command("push")
@click.option("--dry-run", is_flag=True, help="Show what would be pushed without making changes")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def push(ctx, dry_run, yes):
    """Push local categorization changes to YNAB.

    Uploads any transactions that were categorized locally (stored in pending_changes)
    back to YNAB. Shows a detailed summary of what will change before pushing.
    """
    sync_service = get_sync_service(ctx)

    # Get pending changes from delta table
    pending = sync_service._db.get_all_pending_changes()
    pending_count = len(pending)

    if pending_count == 0:
        click.echo("No pending changes to push.")
        return

    # Always show detailed summary
    display_pending_changes(pending)

    if dry_run:
        click.echo("\n(Dry run - no changes made)")
        return

    if not yes and not click.confirm(f"\nPush {pending_count} change(s) to YNAB?"):
        click.echo("Cancelled.")
        return

    click.echo("\nPushing to YNAB...")
    result = sync_service.push_ynab(dry_run=False)

    if result.success:
        click.echo(click.style(f"✓ Successfully pushed {result.succeeded} change(s)", fg="green"))
    else:
        click.echo(click.style(f"✗ Pushed {result.succeeded}, failed {result.failed}", fg="yellow"))
        for error in result.errors:
            click.echo(f"  Error: {error}")


@main.command("db-deltas")
@click.pass_context
def db_deltas(ctx):
    """List pending changes (deltas) awaiting push to YNAB.

    Shows all local categorization changes that haven't been pushed yet.
    Use 'push' to send these changes to YNAB, or 'undo' to revert them.
    """
    sync_service = get_sync_service(ctx)
    db = sync_service._db

    pending = db.get_all_pending_changes()

    if not pending:
        click.echo("No pending changes.")
        return

    display_pending_changes(pending)

    click.echo(f"\nTotal: {len(pending)} pending change(s)")
    click.echo("Use 'push' to send to YNAB, or 'undo --all' to revert all.")


@main.command("undo")
@click.argument("transaction_id", required=False)
@click.option("--all", "undo_all", is_flag=True, help="Undo all pending changes")
@click.pass_context
def undo(ctx, transaction_id, undo_all):
    """Undo pending category changes.

    Reverts local categorization changes that haven't been pushed to YNAB yet.

    \b
    Examples:
      undo abc123          # Undo specific transaction by ID
      undo --all           # Undo all pending changes
    """
    sync_service = get_sync_service(ctx)
    db = sync_service._db

    if not transaction_id and not undo_all:
        click.echo("Error: Provide a transaction ID or use --all to undo all changes.")
        click.echo("Use 'db-deltas' to see pending changes and their transaction IDs.")
        return

    if undo_all:
        pending = db.get_all_pending_changes()
        if not pending:
            click.echo("No pending changes to undo.")
            return

        if not click.confirm(f"Undo {len(pending)} pending change(s)?"):
            click.echo("Cancelled.")
            return

        count = 0
        for change in pending:
            txn_id = change["transaction_id"]
            # Also clear any pending splits
            if change.get("change_type") == "split":
                db.clear_pending_splits(txn_id)
            db.delete_pending_change(txn_id)
            count += 1

        click.echo(click.style(f"✓ Undone {count} change(s)", fg="green"))
    else:
        # Undo specific transaction
        single_pending = db.get_pending_change(transaction_id)
        if not single_pending:
            click.echo(f"No pending change found for transaction ID: {transaction_id}")
            return

        # Clear any pending splits
        if single_pending.get("change_type") == "split":
            db.clear_pending_splits(transaction_id)
        db.delete_pending_change(transaction_id)

        old_cat = single_pending.get("original_category_name") or "Uncategorized"
        click.echo(click.style(f"✓ Undone: restored to '{old_cat}'", fg="green"))


@main.command("db-status")
@click.pass_context
def db_status(ctx):
    """Show database sync status and statistics."""
    sync_service = get_sync_service(ctx)
    status = sync_service.get_status()
    is_mock = ctx.obj.get("mock", False)

    db_type = click.style("MOCK", fg="yellow") if is_mock else "Production"
    click.echo(f"\n=== Database Status ({db_type}) ===\n")

    # Categories section
    categories = status["categories"]
    click.echo("YNAB Categories:")
    click.echo(f"  Total:          {categories['count']:,}")
    if categories["last_sync_at"]:
        click.echo(f"  Last sync:      {categories['last_sync_at'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        click.echo("  Last sync:      Never")

    click.echo()

    # YNAB section
    ynab = status["ynab"]
    click.echo("YNAB Transactions:")
    click.echo(f"  Total:          {ynab['transaction_count']:,}")
    if ynab["earliest_date"] and ynab["latest_date"]:
        click.echo(f"  Date range:     {ynab['earliest_date']} to {ynab['latest_date']}")
    click.echo(f"  Uncategorized:  {ynab['uncategorized_count']:,}")
    click.echo(f"  Pending push:   {ynab['pending_push_count']:,}")
    if ynab["last_sync_at"]:
        click.echo(f"  Last sync:      {ynab['last_sync_at'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        click.echo("  Last sync:      Never")

    click.echo()

    # Amazon section
    amazon = status["amazon"]
    click.echo("Amazon Orders:")
    click.echo(f"  Orders:         {amazon['order_count']:,}")
    if amazon["earliest_date"] and amazon["latest_date"]:
        click.echo(f"  Date range:     {amazon['earliest_date']} to {amazon['latest_date']}")
    click.echo(f"  Items:          {amazon['item_count']:,}")
    if amazon["last_sync_at"]:
        click.echo(f"  Last sync:      {amazon['last_sync_at'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        click.echo("  Last sync:      Never")

    click.echo()

    # Category Mappings section
    db = sync_service._db
    mapping_count = db.get_item_category_history_count()
    unique_items = db.get_unique_item_count()
    click.echo("Category Mappings:")
    click.echo(f"  Total mappings: {mapping_count:,}")
    click.echo(f"  Unique items:   {unique_items:,}")


@main.command("db-transactions")
@click.option("--uncategorized", is_flag=True, help="Only show uncategorized transactions")
@click.option("--pending", is_flag=True, help="Only show transactions pending push")
@click.option("--payee", type=str, help="Filter by payee name")
@click.option("--year", type=int, help="Filter by year (e.g., 2025)")
@click.option("--limit", "-n", type=int, default=50, help="Maximum results to show (default: 50)")
@click.option("--csv", "csv_file", type=click.Path(), help="Export to CSV file")
@click.option("--all", "show_all", is_flag=True, help="Show all transactions (no limit)")
@click.pass_context
def db_transactions(ctx, uncategorized, pending, payee, year, limit, csv_file, show_all):
    """Query transactions from local database."""
    import csv

    sync_service = get_sync_service(ctx)
    db = sync_service._db

    # For CSV export or --all, remove limit
    effective_limit = None if (csv_file or show_all) else limit

    txns = db.get_ynab_transactions(
        uncategorized_only=uncategorized,
        pending_push_only=pending,
        payee_filter=payee,
        limit=effective_limit,
    )

    # Filter by year if specified
    if year and txns:
        filtered = []
        for txn in txns:
            if format_date_for_display(txn["date"]).startswith(str(year)):
                filtered.append(txn)
        txns = filtered

    if not txns:
        click.echo("No transactions found matching criteria.")
        return

    # CSV export
    if csv_file:
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "id",
                    "budget_id",
                    "date",
                    "amount",
                    "payee_name",
                    "category_id",
                    "category_name",
                    "account_name",
                    "memo",
                    "approved",
                    "cleared",
                    "transfer_account_id",
                    "transfer_account_name",
                    "debt_transaction_type",
                    "is_split",
                    "parent_transaction_id",
                ]
            )
            for txn in txns:
                writer.writerow(
                    [
                        txn["id"],
                        txn.get("budget_id") or "",
                        format_date_for_display(txn["date"]),
                        txn["amount"],
                        txn.get("payee_name") or "",
                        txn.get("category_id") or "",
                        txn.get("category_name") or "",
                        txn.get("account_name") or "",
                        txn.get("memo") or "",
                        "1" if txn.get("approved") else "0",
                        txn.get("cleared") or "",
                        txn.get("transfer_account_id") or "",
                        txn.get("transfer_account_name") or "",
                        txn.get("debt_transaction_type") or "",
                        "1" if txn.get("is_split") else "0",
                        txn.get("parent_transaction_id") or "",
                    ]
                )
        click.echo(f"Exported {len(txns)} transactions to {csv_file}")
        return

    click.echo(f"\nFound {len(txns)} transaction(s):\n")

    from .models.transaction import BALANCE_ADJUSTMENT_PAYEES

    for txn in txns:
        # Status indicators
        status = ""
        if not txn.get("approved"):
            status += "[U]"
        # Only show [?] for transactions that need categorization
        # (not transfers, balance adjustments, or splits)
        is_transfer = txn.get("transfer_account_id") is not None
        is_balance_adj = txn.get("payee_name") in BALANCE_ADJUSTMENT_PAYEES
        is_split = txn.get("is_split")
        if not txn.get("category_id") and not is_transfer and not is_balance_adj and not is_split:
            status += "[?]"
        if txn.get("sync_status") == "pending_push":
            status += "[P]"
        status = status.ljust(8) if status else "        "

        # Format fields
        date = txn.get("date", "")[:10]
        payee_name = (txn.get("payee_name") or "")[:25].ljust(25)
        amount = txn.get("amount", 0)
        amount_str = f"${abs(amount):,.2f}" if amount >= 0 else f"-${abs(amount):,.2f}"
        cat = (txn.get("category_name") or "Uncategorized")[:15].ljust(15)

        click.echo(f"{status} {date}  {payee_name}  {amount_str:>12}  {cat}")

    click.echo("\n[U]=Unapproved  [?]=Uncategorized  [P]=Pending Push")


@main.command("db-clear")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def db_clear(ctx, yes):
    """Clear all data from the local database.

    This removes all synced data (categories, transactions, orders, sync state).
    You will need to run 'pull' again to repopulate the database.

    Use --mock to clear only the mock database.
    """
    sync_service = get_sync_service(ctx)
    db = sync_service._db
    is_mock = ctx.obj.get("mock", False)

    # Show which database we're clearing
    db_type = click.style("MOCK", fg="yellow") if is_mock else click.style("PRODUCTION", fg="red")
    click.echo(f"\nDatabase: {db_type}")

    # Show current counts
    status = sync_service.get_status()
    click.echo("\nCurrent database contents:")
    click.echo(f"  Categories:     {status['categories']['count']:,}")
    click.echo(f"  Transactions:   {status['ynab']['transaction_count']:,}")
    click.echo(f"  Amazon orders:  {status['amazon']['order_count']:,}")
    click.echo(f"  Amazon items:   {status['amazon']['item_count']:,}")

    if not yes:
        db_name = "mock database" if is_mock else "PRODUCTION database"
        if not click.confirm(f"\nAre you sure you want to clear the {db_name}?"):
            click.echo("Cancelled.")
            return

    click.echo("\nClearing database...")
    counts = db.clear_all()

    total = sum(counts.values())
    click.echo(click.style(f"✓ Cleared {total:,} records", fg="green"))
    click.echo("\nRun 'pull' to repopulate the database.")


# =============================================================================
# Category Mapping Commands
# =============================================================================


@main.command("mappings-create")
@click.option(
    "--since",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Only process transactions on or after this date",
)
@click.option("--dry-run", is_flag=True, help="Preview what would be learned without saving")
@click.pass_context
def mappings_create(ctx, since, dry_run):
    """Learn category mappings from approved Amazon transactions.

    Scans historical approved Amazon transactions and builds a database of
    which YNAB categories are typically assigned to which Amazon items.

    This creates mappings that can be used for future categorization suggestions.

    \b
    Examples:
        uv run python -m src.main mappings-create
        uv run python -m src.main mappings-create --dry-run
        uv run python -m src.main mappings-create --since 2024-01-01
    """
    from .services.category_mapping import CategoryMappingService

    cfg = ctx.obj["config"]
    sync_service = get_sync_service(ctx)
    db = sync_service._db

    # Check if we have data
    if not require_data(db, "transactions"):
        return

    click.echo("Learning category mappings from approved Amazon transactions...")
    if dry_run:
        click.echo(click.style("(DRY RUN - no changes will be saved)", fg="yellow"))
    click.echo()

    # Create service and run learning
    service = CategoryMappingService(db, payees_config=cfg.payees)

    # Show progress with tqdm-style output
    click.echo("Scanning transactions...")
    result = service.learn_from_approved_transactions(
        since_date=since,
        dry_run=dry_run,
    )

    # Display results
    click.echo()
    click.echo("=" * 50)
    click.echo("Results:")
    click.echo("=" * 50)
    click.echo(f"  Transactions processed:  {result.transactions_processed:>6}")
    click.echo(f"  Transactions matched:    {result.transactions_matched:>6}")
    click.echo(
        f"  Items learned:           {click.style(str(result.items_learned), fg='green'):>15}"
    )
    if result.items_skipped_duplicate > 0:
        click.echo(f"  Items skipped (dupe):    {result.items_skipped_duplicate:>6}")
    if result.items_skipped_no_category > 0:
        click.echo(f"  Items skipped (no cat):  {result.items_skipped_no_category:>6}")
    if result.split_transactions_skipped > 0:
        click.echo(f"  Split txns skipped:      {result.split_transactions_skipped:>6}")

    if result.errors:
        click.echo()
        click.echo(click.style("Errors:", fg="red"))
        for err in result.errors:
            click.echo(f"  - {err}")

    # Show current statistics
    if not dry_run:
        stats = service.get_statistics()
        click.echo()
        click.echo("Database now contains:")
        click.echo(f"  Total mappings:  {stats['total_mappings']:,}")
        click.echo(f"  Unique items:    {stats['unique_items']:,}")


@main.command("mappings")
@click.option("--item", "-i", help="Filter by item name (partial match)")
@click.option("--category", "-c", help="Filter by category name (partial match)")
@click.option("--limit", "-n", type=int, default=50, help="Maximum items to show (default: 50)")
@click.pass_context
def mappings(ctx, item, category, limit):
    """Show learned Amazon item to category mappings.

    Displays all learned mappings with their category distributions.
    Use filters to find specific items or categories.

    \b
    Examples:
        uv run python -m src.main mappings
        uv run python -m src.main mappings --item "cat"
        uv run python -m src.main mappings --category "Pet"
        uv run python -m src.main mappings -n 100
    """
    from .services.category_mapping import CategoryMappingService

    sync_service = get_sync_service(ctx)
    db = sync_service._db

    # Get statistics first
    service = CategoryMappingService(db)
    stats = service.get_statistics()

    if stats["total_mappings"] == 0:
        click.echo(click.style("No category mappings found.", fg="yellow"))
        click.echo("Run 'mappings-create' to build the mapping database.")
        return

    click.echo(
        f"Category mapping database: {stats['unique_items']:,} unique items, {stats['total_mappings']:,} total mappings"
    )
    click.echo()

    # Get mappings with filters
    mappings = db.get_all_item_category_mappings(
        search_term=item,
        category_filter=category,
    )

    if not mappings:
        click.echo("No mappings found matching your filters.")
        return

    # Show filters if applied
    filters = []
    if item:
        filters.append(f"item contains '{item}'")
    if category:
        filters.append(f"category contains '{category}'")
    if filters:
        click.echo(f"Filters: {', '.join(filters)}")
        click.echo()

    # Limit results
    total_found = len(mappings)
    if len(mappings) > limit:
        mappings = mappings[:limit]

    click.echo(f"Showing {len(mappings)} of {total_found} items:\n")
    click.echo("-" * 70)

    for mapping in mappings:
        # Truncate long item names
        item_name = mapping["item_name"]
        if len(item_name) > 60:
            item_name = item_name[:57] + "..."

        click.echo(f"{item_name}")

        # Show category distribution
        for cat in mapping["categories"]:
            pct = cat["percentage"] * 100
            count = cat["count"]
            bar_len = int(pct / 5)  # 20 chars max for 100%
            bar = "█" * bar_len + "░" * (20 - bar_len)

            if pct >= 80:
                pct_style = click.style(f"{pct:5.1f}%", fg="green")
            elif pct >= 50:
                pct_style = click.style(f"{pct:5.1f}%", fg="yellow")
            else:
                pct_style = f"{pct:5.1f}%"

            click.echo(f"  {bar} {pct_style} {cat['name']} ({count}x)")

        click.echo()

    if total_found > limit:
        click.echo(f"... and {total_found - limit} more items. Use -n to show more.")


if __name__ == "__main__":
    main()
