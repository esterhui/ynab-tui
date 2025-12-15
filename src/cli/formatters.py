"""CLI output formatters.

Extracts display/formatting logic from main.py for better maintainability.
"""

import click


def format_sync_time(sync_state: dict | None) -> str:
    """Format sync time for display."""
    if sync_state and sync_state.get("last_sync_at"):
        return sync_state["last_sync_at"].strftime("%Y-%m-%d %H:%M")
    return "Never"


def format_transaction_row(txn: dict, show_status: bool = False) -> str:
    """Format a transaction row for CLI display.

    Args:
        txn: Transaction dictionary.
        show_status: Whether to show sync status.

    Returns:
        Formatted string for display.
    """
    date = txn.get("date", "")[:10]
    amount = f"${abs(txn.get('amount', 0)):,.2f}"
    payee = (txn.get("payee_name") or "")[:25].ljust(25)
    category = (txn.get("category_name") or "Uncategorized")[:20].ljust(20)

    row = f"{date}  {amount:>10}  {payee}  {category}"

    if show_status:
        status = txn.get("sync_status", "synced")
        if status == "pending_push":
            row += "  [PENDING]"

    return row


def format_category_row(cat: dict, group_name: str = "") -> str:
    """Format a category row for CLI display."""
    name = cat.get("name", "")
    if group_name:
        return f"  {group_name}: {name}"
    return f"  {name}"


def echo_success(message: str) -> None:
    """Echo a success message in green."""
    click.echo(click.style(f"✓ {message}", fg="green"))


def echo_error(message: str) -> None:
    """Echo an error message in red."""
    click.echo(click.style(f"✗ {message}", fg="red"))


def echo_warning(message: str) -> None:
    """Echo a warning message in yellow."""
    click.echo(click.style(f"⚠ {message}", fg="yellow"))


def echo_header(message: str) -> None:
    """Echo a header with underline."""
    click.echo(f"\n{message}")
    click.echo("=" * len(message))


def format_pull_result(source: str, result) -> None:
    """Format and display a pull operation result.

    Args:
        source: Source name (e.g., "YNAB", "Amazon").
        result: PullResult object.
    """
    if result.success:
        echo_success(f"Fetched {result.fetched} {source} records")
        if result.oldest_date and result.newest_date:
            click.echo(
                f"    Date range: {result.oldest_date.strftime('%Y-%m-%d')} "
                f"to {result.newest_date.strftime('%Y-%m-%d')}"
            )
        click.echo(f"    Inserted: {result.inserted}, Updated: {result.updated}")
        click.echo(f"    Total in database: {result.total}")
    else:
        echo_error(f"Error: {result.errors}")


def format_push_result(result) -> None:
    """Format and display a push operation result.

    Args:
        result: PushResult object.
    """
    if result.success:
        echo_success(f"Pushed {result.succeeded} changes to YNAB")
    else:
        echo_error(f"Push failed: {result.failed} failures")
        for error in result.errors:
            click.echo(f"    {error}")


# =============================================================================
# Amazon Match Display Helpers
# =============================================================================


def format_item_prediction(item_name: str, prediction) -> str:
    """Format a single item with its category prediction.

    Args:
        item_name: The item name.
        prediction: ItemCategoryPrediction from mapping service.

    Returns:
        Formatted string like "Item Name [Category 95%]" or "Item Name [?]"
    """
    if prediction.category_id:
        return f"{item_name} [{prediction.category_name} {prediction.confidence:.0%}]"
    return f"{item_name} [?]"


def display_verbose_items(order, mapping_service) -> None:
    """Display verbose item predictions for an order."""
    prediction = mapping_service.predict_order_categories(order)
    for item_pred in prediction.item_predictions:
        formatted = format_item_prediction(item_pred.item_name, item_pred)
        click.echo(f"      • {formatted}")


def display_amazon_match_results(
    result,
    stage1_window: int,
    stage2_window: int,
    verbose: bool = False,
    mapping_service=None,
) -> None:
    """Display Amazon match results to console.

    Args:
        result: AmazonMatchResult from matcher.
        stage1_window: Stage 1 window size in days.
        stage2_window: Stage 2 window size in days.
        verbose: If True, show item-level predictions.
        mapping_service: CategoryMappingService for predictions (required if verbose).
    """
    # Section 1: Stage 1 Matched transactions
    if result.stage1_matches:
        click.echo("=" * 60)
        click.echo(f"Matched YNAB transactions ({stage1_window}-day window):")
        click.echo("=" * 60 + "\n")

        for txn_info, order in result.stage1_matches:
            approved_marker = click.style(" A", fg="cyan") if txn_info.approved else ""
            click.echo(
                f"YNAB: {txn_info.date_str}  Amazon  {txn_info.display_amount}{approved_marker}"
            )
            items_str = "; ".join(order.items)
            if len(items_str) > 60:
                items_str = items_str[:57] + "..."
            click.echo(
                f"  → {click.style('MATCH:', fg='green')} Order {order.order_id} "
                f"({order.order_date.strftime('%Y-%m-%d')}) ${order.total:.2f}"
            )
            click.echo(f"    Items: {items_str}")
            if verbose and mapping_service:
                display_verbose_items(order, mapping_service)
            click.echo()

        click.echo(f"Matched ({stage1_window}-day): {len(result.stage1_matches)} transactions\n")

    # Section 2: Stage 2 Matched transactions (extended window)
    if result.stage2_matches:
        click.echo("=" * 60)
        click.echo(f"Matched YNAB transactions ({stage2_window}-day extended window):")
        click.echo("=" * 60 + "\n")

        for txn_info, order in result.stage2_matches:
            date_diff = abs((txn_info.date - order.order_date).days)
            approved_marker = click.style(" A", fg="cyan") if txn_info.approved else ""
            click.echo(
                f"YNAB: {txn_info.date_str}  Amazon  {txn_info.display_amount}{approved_marker}"
            )
            items_str = "; ".join(order.items)
            if len(items_str) > 60:
                items_str = items_str[:57] + "..."
            click.echo(
                f"  → {click.style('EXTENDED MATCH:', fg='cyan')} Order {order.order_id} "
                f"({order.order_date.strftime('%Y-%m-%d')}) ${order.total:.2f} "
                f"[{date_diff} days apart]"
            )
            click.echo(f"    Items: {items_str}")
            if verbose and mapping_service:
                display_verbose_items(order, mapping_service)
            click.echo()

        click.echo(
            f"Matched ({stage2_window}-day extended): {len(result.stage2_matches)} transactions\n"
        )

    # Section 3: Duplicate matches
    if result.duplicate_matches:
        click.echo("=" * 60)
        click.echo(
            click.style(
                "Duplicate matches (same order matched multiple transactions):", fg="yellow"
            )
        )
        click.echo("=" * 60 + "\n")

        duplicates_by_order: dict[str, dict] = {}
        for txn_info, order in result.duplicate_matches:
            if order.order_id not in duplicates_by_order:
                duplicates_by_order[order.order_id] = {"order": order, "txns": []}
            duplicates_by_order[order.order_id]["txns"].append(txn_info)

        for order_id, data in duplicates_by_order.items():
            order = data["order"]
            for txn_info, matched_order in result.all_matches:
                if matched_order.order_id == order_id:
                    data["original_txn"] = txn_info
                    break

        for order_id, data in duplicates_by_order.items():
            order = data["order"]
            items_str = "; ".join(order.items)
            if len(items_str) > 50:
                items_str = items_str[:47] + "..."
            click.echo(
                f"Order: {order.order_id} ({order.order_date.strftime('%Y-%m-%d')}) "
                f"${order.total:.2f} - {items_str}"
            )
            click.echo(f"  {click.style('Matched to:', fg='green')} ", nl=False)
            if "original_txn" in data:
                orig = data["original_txn"]
                approved_marker = click.style(" A", fg="cyan") if orig.approved else ""
                click.echo(f"{orig.date_str} {orig.display_amount}{approved_marker}")
            else:
                click.echo("(original match)")
            click.echo(f"  {click.style('Also matches:', fg='yellow')}")
            for txn_info in data["txns"]:
                approved_marker = click.style(" A", fg="cyan") if txn_info.approved else ""
                click.echo(f"    • {txn_info.date_str}  {txn_info.display_amount}{approved_marker}")
            click.echo()

        click.echo(
            f"Duplicates: {len(result.duplicate_matches)} transaction(s) matching already-used orders\n"
        )

    # Section 4: Combo matches (split shipments)
    if result.combo_matches:
        click.echo("=" * 60)
        click.echo("Combination matches (split shipments):")
        click.echo("=" * 60 + "\n")

        for order, combo_txns in sorted(
            result.combo_matches, key=lambda x: x[0].order_date, reverse=True
        ):
            combo_total = sum(t.amount for t in combo_txns)
            items_str = "; ".join(order.items)
            if len(items_str) > 50:
                items_str = items_str[:47] + "..."
            click.echo(
                f"Order: {order.order_date.strftime('%Y-%m-%d')}  ${order.total:.2f} - {items_str}"
            )
            click.echo(
                f"  → {click.style('COMBO MATCH:', fg='cyan')} {len(combo_txns)} transactions sum to ${combo_total:.2f}"
            )
            for t in combo_txns:
                approved_marker = click.style(" A", fg="cyan") if t.approved else ""
                click.echo(f"      • {t.date_str}  ${t.amount:.2f}{approved_marker}")
            click.echo()

        click.echo(f"Combo matched: {len(result.combo_matches)} orders\n")

    # Section 5: Unmatched items
    if result.unmatched_transactions or result.unmatched_orders:
        click.echo("=" * 60)
        click.echo("Unmatched items:")
        click.echo("=" * 60 + "\n")

        if result.unmatched_transactions:
            click.echo(click.style("Transactions without matching orders:", fg="yellow"))
            for t in result.unmatched_transactions:
                approved_marker = click.style(" A", fg="cyan") if t.approved else ""
                click.echo(f"  • {t.date_str}  Amazon  -${t.amount:.2f}{approved_marker}")
            click.echo()

        if result.unmatched_orders:
            click.echo(click.style("Orders without matching transactions:", fg="yellow"))
            for order in sorted(result.unmatched_orders, key=lambda o: o.order_date, reverse=True):
                items_str = "; ".join(order.items)
                if len(items_str) > 50:
                    items_str = items_str[:47] + "..."
                click.echo(
                    f"  • {order.order_date.strftime('%Y-%m-%d')}  ${order.total:.2f} - {items_str}"
                )
            click.echo()

    # Final summary
    click.echo("=" * 60)
    summary_parts = []
    if result.stage1_matches:
        summary_parts.append(f"{len(result.stage1_matches)} matched ({stage1_window}d)")
    if result.stage2_matches:
        summary_parts.append(f"{len(result.stage2_matches)} extended ({stage2_window}d)")
    if result.duplicate_matches:
        summary_parts.append(
            click.style(f"{len(result.duplicate_matches)} duplicates", fg="yellow")
        )
    if result.combo_matches:
        summary_parts.append(f"{len(result.combo_matches)} combo")
    if result.unmatched_transactions:
        summary_parts.append(f"{len(result.unmatched_transactions)} unmatched txns")
    if result.unmatched_orders:
        summary_parts.append(f"{len(result.unmatched_orders)} unmatched orders")

    click.echo(f"Summary: {', '.join(summary_parts)}")
