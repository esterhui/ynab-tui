# Architecture Refactoring - Remaining Work

This document captures the remaining refactoring tasks identified during the architecture review. These are lower-priority items that can be addressed in future iterations.

## 1. Split database.py into Repositories

**Complexity:** High
**Current State:** `src/db/database.py` is 2000+ lines with 60+ methods mixing multiple concerns.

### Proposed Structure

```
src/db/
├── __init__.py
├── database.py              # Facade + connection management only
├── repositories/
│   ├── __init__.py
│   ├── ynab_transactions.py # YNAB transaction CRUD
│   ├── amazon_orders.py     # Amazon order caching
│   ├── categorization.py    # Categorization history
│   ├── pending_changes.py   # Delta table operations
│   ├── sync_state.py        # Sync state tracking
│   └── item_categories.py   # Amazon item → category mappings
```

### Method Groupings

| Repository | Methods to Move |
|------------|-----------------|
| `ynab_transactions.py` | `upsert_ynab_transaction`, `get_ynab_transactions`, `get_ynab_transaction`, `get_subtransactions`, `mark_pending_push`, `mark_synced` |
| `amazon_orders.py` | `cache_amazon_order`, `get_cached_orders_*`, `upsert_amazon_order_items` |
| `categorization.py` | `add_categorization`, `get_payee_history`, `get_payee_category_distribution*` |
| `pending_changes.py` | `create_pending_change`, `get_pending_change`, `delete_pending_change`, `apply_pending_change`, `mark_pending_split`, `get_pending_splits` |
| `sync_state.py` | `get_sync_state`, `update_sync_state` |
| `item_categories.py` | `get_amazon_item_categories`, `set_amazon_item_category`, `record_item_category_learning`, `get_item_category_distribution` |

### Implementation Notes

- Keep `Database` class as a facade that delegates to repositories
- Repositories share the connection via dependency injection
- Maintain backwards compatibility by keeping existing method signatures on `Database`

---

## 2. Migrate CLI Commands to Modules

**Complexity:** Medium
**Current State:** `src/main.py` is 1500+ lines with all CLI commands in one file.

### Proposed Structure

```
src/cli/
├── __init__.py
├── main_group.py            # Main click group + global options
├── formatters.py            # Output formatting (already created)
├── helpers.py               # _get_categorizer, _get_sync_service
├── commands/
│   ├── __init__.py
│   ├── sync.py              # pull, push
│   ├── ynab.py              # ynab-test, ynab-budgets, ynab-categories, ynab-unapproved
│   ├── amazon.py            # amazon-test, amazon-match
│   ├── db.py                # db-status, db-transactions, db-amazon-orders, db-deltas, db-clear
│   ├── mappings.py          # mappings, mappings-create
│   └── core.py              # uncategorized, undo
```

### Implementation Approach

1. Create `main_group.py` with the main click group:
   ```python
   @click.group()
   @click.pass_context
   def main(ctx, ...):
       ...
   ```

2. Commands register themselves on import:
   ```python
   # In commands/sync.py
   from ..main_group import main

   @main.command("pull")
   def pull(...):
       ...
   ```

3. Update `main.py` to just import and run:
   ```python
   from .cli.main_group import main
   from .cli import commands  # Triggers command registration

   if __name__ == "__main__":
       main()
   ```

### Challenges

- Click's decorator pattern requires careful import ordering
- Shared context (`ctx.obj`) management across modules
- Avoiding circular imports

---

## 3. Virtual Scrolling for TUI List

**Complexity:** Medium
**Current State:** All transactions are formatted upfront when loading the list.

### Problem

```python
# src/tui/app.py:490-494
items = [
    TransactionListItem(txn, self._amazon_items_collapsed)
    for txn in self._transactions.transactions
]
```

For 1000+ transactions, this creates all items immediately, causing:
- Memory overhead
- Initial render delay
- Unnecessary formatting of off-screen items

### Solution Options

1. **Textual's Built-in Virtual Scrolling**
   - Use `ListView` with virtual rendering
   - Defer `TransactionListItem` creation until visible

2. **Custom Virtual List Widget**
   - Only render visible rows + buffer
   - Recycle row widgets as user scrolls

3. **Lazy Formatting**
   - Create all `TransactionListItem` objects but defer `_format_row()` until first render

### Recommended Approach

Option 1 with Textual's virtual rendering is cleanest. Check if `ListView` already supports this or if a custom `VirtualList` widget is needed.

---

## Priority Order

| Priority | Task | Estimated Effort |
|----------|------|------------------|
| 1 | CLI command migration | 2-3 hours |
| 2 | Database repository split | 4-6 hours |
| 3 | Virtual scrolling | 2-3 hours |

## Related Files

- Architecture review plan: `~/.claude/plans/crispy-stirring-wolf.md`
- Constants: `src/constants.py`
- New formatters: `src/cli/formatters.py`
- CLI structure: `src/cli/`
