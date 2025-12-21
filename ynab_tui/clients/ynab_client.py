"""YNAB API client for transaction management.

Wraps the official ynab library to provide a clean interface for:
- Fetching uncategorized/unapproved transactions
- Getting category list
- Updating transaction categories
"""

import logging
from datetime import datetime
from typing import Optional

import urllib3
import ynab

from ..config import YNABConfig
from ..models import Category, CategoryGroup, CategoryList, SubTransaction, Transaction
from ..utils import parse_to_datetime
from .decorators import with_retry, wrap_client_errors

logger = logging.getLogger(__name__)


class YNABClientError(Exception):
    """Error communicating with YNAB API."""

    pass


# Decorator for YNAB API error handling
def _ynab_api_call(operation: str):
    """Shorthand decorator for YNAB API calls."""
    return wrap_client_errors(YNABClientError, operation, ynab.ApiException)


class YNABClient:
    """Client for YNAB API operations."""

    def __init__(self, config: YNABConfig):
        """Initialize YNAB client.

        Args:
            config: YNAB configuration with API token and budget ID.
        """
        if not config.api_token:
            raise YNABClientError("YNAB API token is required")

        self._configuration = ynab.Configuration(access_token=config.api_token)
        self._budget_id = config.budget_id
        self._resolved_budget_id: Optional[str] = None
        self._account_cache: dict[str, str] = {}  # account_id -> account_name

        # Store retry/timeout settings from config
        self._timeout_seconds = getattr(config, "timeout_seconds", 30)
        self._max_retries = getattr(config, "max_retries", 3)
        self._retry_base_delay = getattr(config, "retry_base_delay", 1.0)

    def _get_api_client(self) -> ynab.ApiClient:
        """Create API client for use in context manager.

        Configures timeout via urllib3 pool manager.
        """
        client = ynab.ApiClient(self._configuration)

        # Configure timeout on the underlying urllib3 pool manager
        # The ynab SDK uses urllib3 under the hood
        if hasattr(client, "rest_client") and hasattr(client.rest_client, "pool_manager"):
            client.rest_client.pool_manager = urllib3.PoolManager(
                timeout=urllib3.Timeout(total=self._timeout_seconds)
            )

        return client

    def _with_retry(self, func, operation: str):
        """Execute a function with retry logic for transient failures.

        Args:
            func: Callable to execute.
            operation: Description for logging.

        Returns:
            Result of the function call.

        Raises:
            YNABClientError: If all retries are exhausted or non-retryable error.
        """
        retry_decorator = with_retry(
            max_retries=self._max_retries,
            base_delay=self._retry_base_delay,
            retryable_exceptions=(ynab.ApiException, Exception),
        )
        wrapped = retry_decorator(func)
        try:
            return wrapped()
        except ynab.ApiException as e:
            raise YNABClientError(f"Failed to {operation}: {e}") from e
        except Exception as e:
            raise YNABClientError(f"Failed to {operation}: {e}") from e

    def _is_uuid(self, value: str) -> bool:
        """Check if a string looks like a UUID."""
        # UUIDs are 36 chars with hyphens in specific positions
        if len(value) != 36:
            return False
        try:
            parts = value.split("-")
            return len(parts) == 5 and all(len(p) in (8, 4, 4, 4, 12) for p in parts)
        except Exception:
            return False

    def _resolve_budget_name(self, name: str) -> str:
        """Resolve a budget name to its UUID.

        Args:
            name: Budget name (case-insensitive match).

        Returns:
            Budget UUID.

        Raises:
            YNABClientError: If budget name not found.
        """
        with self._get_api_client() as api_client:
            budgets_api = ynab.BudgetsApi(api_client)
            response = budgets_api.get_budgets()

            if not response.data.budgets:
                raise YNABClientError("No budgets found in YNAB account")

            # Case-insensitive match
            name_lower = name.lower()
            for budget in response.data.budgets:
                if budget.name.lower() == name_lower:
                    return budget.id

            # No match found - show available budgets
            available = [b.name for b in response.data.budgets]
            raise YNABClientError(
                f"Budget '{name}' not found. Available budgets: {', '.join(available)}"
            )

    def _get_budget_id(self) -> str:
        """Get the actual budget ID, resolving 'last-used' or budget name if needed."""
        if self._resolved_budget_id:
            return self._resolved_budget_id

        if self._budget_id == "last-used":
            # Get the most recently modified budget
            with self._get_api_client() as api_client:
                budgets_api = ynab.BudgetsApi(api_client)
                response = budgets_api.get_budgets()

                if not response.data.budgets:
                    raise YNABClientError("No budgets found in YNAB account")

                # Sort by last modified and get the first one
                sorted_budgets = sorted(
                    response.data.budgets,
                    key=lambda b: b.last_modified_on or "",
                    reverse=True,
                )
                self._resolved_budget_id = sorted_budgets[0].id
        elif self._is_uuid(self._budget_id):
            # Already a UUID
            self._resolved_budget_id = self._budget_id
        else:
            # Treat as budget name, resolve to UUID
            self._resolved_budget_id = self._resolve_budget_name(self._budget_id)

        return self._resolved_budget_id

    def set_budget_id(self, budget_id: str) -> None:
        """Set the budget ID to use for all operations.

        Accepts either a UUID or budget name. Names are resolved to UUIDs.

        Args:
            budget_id: YNAB budget ID or budget name.
        """
        self._budget_id = budget_id
        # Clear resolved ID to force re-resolution (handles name -> UUID)
        self._resolved_budget_id = None
        # Clear account cache since it's budget-specific
        self._account_cache = {}
        # Trigger resolution now to validate the budget exists
        self._get_budget_id()

    def get_current_budget_id(self) -> str:
        """Get the current resolved budget ID.

        Returns:
            The budget ID being used for operations.
        """
        return self._get_budget_id()

    def get_budget_name(self, budget_id: Optional[str] = None) -> str:
        """Get the name of a budget by ID.

        Args:
            budget_id: Budget UUID. If None, uses current budget.

        Returns:
            Budget name.
        """
        target_id = budget_id or self._get_budget_id()
        budgets = self.get_budgets()
        for budget in budgets:
            if budget["id"] == target_id:
                return budget["name"]
        return "Unknown Budget"

    def _ensure_account_cache(self) -> None:
        """Populate the account cache if not already done."""
        if self._account_cache:
            return

        budget_id = self._get_budget_id()
        with self._get_api_client() as api_client:
            accounts_api = ynab.AccountsApi(api_client)
            response = accounts_api.get_accounts(budget_id)
            for account in response.data.accounts:
                self._account_cache[account.id] = account.name

    def _get_account_name(self, account_id: Optional[str]) -> Optional[str]:
        """Look up account name by ID."""
        if not account_id:
            return None
        self._ensure_account_cache()
        return self._account_cache.get(account_id)

    @_ynab_api_call("fetch categories")
    def get_categories(self) -> CategoryList:
        """Fetch all categories from YNAB.

        Returns:
            CategoryList with all category groups and categories.
        """
        budget_id = self._get_budget_id()

        with self._get_api_client() as api_client:
            categories_api = ynab.CategoriesApi(api_client)
            response = categories_api.get_categories(budget_id)

            groups = []
            for group_data in response.data.category_groups:
                categories = []
                for cat_data in group_data.categories:
                    categories.append(
                        Category(
                            id=cat_data.id,
                            name=cat_data.name,
                            group_id=group_data.id,
                            group_name=group_data.name,
                            budgeted=cat_data.budgeted / 1000 if cat_data.budgeted else None,
                            activity=cat_data.activity / 1000 if cat_data.activity else None,
                            balance=cat_data.balance / 1000 if cat_data.balance else None,
                            hidden=cat_data.hidden,
                            deleted=cat_data.deleted,
                            note=cat_data.note,
                        )
                    )

                groups.append(
                    CategoryGroup(
                        id=group_data.id,
                        name=group_data.name,
                        categories=categories,
                        hidden=group_data.hidden,
                        deleted=group_data.deleted,
                    )
                )

            return CategoryList(groups=groups)

    @_ynab_api_call("fetch uncategorized transactions")
    def get_uncategorized_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch transactions that need categorization.

        Args:
            since_date: Only fetch transactions on or after this date.

        Returns:
            List of uncategorized transactions.
        """
        budget_id = self._get_budget_id()
        since = since_date.date() if since_date else None

        with self._get_api_client() as api_client:
            transactions_api = ynab.TransactionsApi(api_client)
            response = transactions_api.get_transactions(
                budget_id,
                since_date=since,
                type="uncategorized",
            )

            return self._convert_transactions(response.data.transactions)

    @_ynab_api_call("fetch unapproved transactions")
    def get_unapproved_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch transactions that need approval.

        Args:
            since_date: Only fetch transactions on or after this date.

        Returns:
            List of unapproved transactions.
        """
        budget_id = self._get_budget_id()
        since = since_date.date() if since_date else None

        with self._get_api_client() as api_client:
            transactions_api = ynab.TransactionsApi(api_client)
            response = transactions_api.get_transactions(
                budget_id,
                since_date=since,
                type="unapproved",
            )

            return self._convert_transactions(response.data.transactions)

    def get_all_pending_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch all transactions that need attention (uncategorized OR unapproved).

        Args:
            since_date: Only fetch transactions on or after this date.

        Returns:
            List of transactions needing categorization or approval.
        """
        uncategorized = self.get_uncategorized_transactions(since_date)
        unapproved = self.get_unapproved_transactions(since_date)

        # Merge and dedupe by transaction ID
        seen = set()
        transactions = []

        for txn in uncategorized + unapproved:
            if txn.id not in seen:
                seen.add(txn.id)
                transactions.append(txn)

        # Sort by date (newest first)
        transactions.sort(key=lambda t: t.date, reverse=True)
        return transactions

    def update_transaction_category(
        self,
        transaction_id: str,
        category_id: str,
        approve: bool = True,
    ) -> Transaction:
        """Update a transaction's category and optionally approve it.

        Includes retry logic for transient failures (network errors, rate limits).

        Args:
            transaction_id: YNAB transaction ID.
            category_id: YNAB category ID to assign.
            approve: Whether to also approve the transaction.

        Returns:
            Updated transaction.
        """
        budget_id = self._get_budget_id()

        def _do_update():
            with self._get_api_client() as api_client:
                transactions_api = ynab.TransactionsApi(api_client)

                # Create the update model
                existing_txn = ynab.ExistingTransaction(
                    category_id=category_id,
                    approved=approve if approve else None,
                )
                wrapper = ynab.PutTransactionWrapper(transaction=existing_txn)

                response = transactions_api.update_transaction(
                    budget_id,
                    transaction_id,
                    wrapper,
                )

                return self._convert_transaction(response.data.transaction)

        return self._with_retry(_do_update, "update transaction")

    def create_split_transaction(
        self,
        transaction_id: str,
        splits: list[dict],
        approve: bool = True,
    ) -> Transaction:
        """Convert a transaction to a split transaction.

        Includes retry logic for transient failures (network errors, rate limits).

        Args:
            transaction_id: YNAB transaction ID.
            splits: List of dicts with 'category_id', 'amount' (in dollars, negative),
                    and optional 'memo'.
            approve: Whether to approve the transaction.

        Returns:
            Updated transaction with splits.

        Note:
            YNAB API doesn't allow updating existing splits, so this only works
            on non-split transactions. The sum of split amounts must equal the
            original transaction amount.
        """
        budget_id = self._get_budget_id()

        # Build SaveSubTransaction list
        # YNAB amounts are in milliunits (1000 = $1.00)
        # Use round() to avoid float precision issues (e.g., 10.005 * 1000 = 10004.999...)
        subtransactions = []
        for split in splits:
            amount_milliunits = int(round(split["amount"] * 1000))
            sub = ynab.SaveSubTransaction(
                amount=amount_milliunits,
                category_id=split.get("category_id"),
                memo=split.get("memo"),
            )
            subtransactions.append(sub)

        def _do_split():
            with self._get_api_client() as api_client:
                transactions_api = ynab.TransactionsApi(api_client)

                # Create the update with subtransactions
                existing_txn = ynab.ExistingTransaction(
                    subtransactions=subtransactions,
                    approved=approve if approve else None,
                )
                wrapper = ynab.PutTransactionWrapper(transaction=existing_txn)

                response = transactions_api.update_transaction(
                    budget_id,
                    transaction_id,
                    wrapper,
                )

                return self._convert_transaction(response.data.transaction)

        return self._with_retry(_do_split, "create split transaction")

    def approve_transaction(self, transaction_id: str) -> Transaction:
        """Approve a transaction without changing its category.

        Includes retry logic for transient failures (network errors, rate limits).

        Args:
            transaction_id: YNAB transaction ID.

        Returns:
            Updated transaction.
        """
        budget_id = self._get_budget_id()

        def _do_approve():
            with self._get_api_client() as api_client:
                transactions_api = ynab.TransactionsApi(api_client)

                existing_txn = ynab.ExistingTransaction(approved=True)
                wrapper = ynab.PutTransactionWrapper(transaction=existing_txn)

                response = transactions_api.update_transaction(
                    budget_id,
                    transaction_id,
                    wrapper,
                )

                return self._convert_transaction(response.data.transaction)

        return self._with_retry(_do_approve, "approve transaction")

    def update_transaction(
        self,
        transaction_id: str,
        category_id: Optional[str] = None,
        memo: Optional[str] = None,
        approved: Optional[bool] = None,
    ) -> Transaction:
        """Update a transaction with any combination of fields.

        Generic update method that can modify any supported field. Only
        non-None fields are sent to the API.

        Args:
            transaction_id: YNAB transaction ID.
            category_id: New category ID (None = don't change).
            memo: New memo text (None = don't change, "" = clear memo).
            approved: New approval status (None = don't change).

        Returns:
            Updated transaction.
        """
        budget_id = self._get_budget_id()

        def _do_update():
            with self._get_api_client() as api_client:
                transactions_api = ynab.TransactionsApi(api_client)

                # Build ExistingTransaction with only provided fields
                # Note: memo="" is valid (clears memo), but memo=None means don't change
                # Pass parameters directly to avoid mypy dict unpacking issues
                existing_txn = ynab.ExistingTransaction(
                    category_id=category_id,
                    memo=memo,
                    approved=approved,
                )
                wrapper = ynab.PutTransactionWrapper(transaction=existing_txn)

                response = transactions_api.update_transaction(
                    budget_id,
                    transaction_id,
                    wrapper,
                )

                return self._convert_transaction(response.data.transaction)

        return self._with_retry(_do_update, "update transaction")

    @_ynab_api_call("fetch budgets")
    def get_budgets(self) -> list[dict]:
        """Fetch all available budgets.

        Returns:
            List of budget info dicts with id, name, and last_modified_on.
        """
        with self._get_api_client() as api_client:
            budgets_api = ynab.BudgetsApi(api_client)
            response = budgets_api.get_budgets()

            return [
                {"id": b.id, "name": b.name, "last_modified_on": b.last_modified_on}
                for b in response.data.budgets
            ]

    @_ynab_api_call("fetch recent transactions")
    def get_recent_transactions(
        self,
        limit: int = 50,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch recent transactions regardless of status.

        Args:
            limit: Maximum number of transactions to return.
            since_date: Only fetch transactions on or after this date.

        Returns:
            List of recent transactions (newest first).
        """
        budget_id = self._get_budget_id()
        since = since_date.date() if since_date else None

        with self._get_api_client() as api_client:
            transactions_api = ynab.TransactionsApi(api_client)
            response = transactions_api.get_transactions(budget_id, since_date=since)

            transactions = self._convert_transactions(response.data.transactions)
            transactions.sort(key=lambda t: t.date, reverse=True)
            return transactions[:limit]

    @_ynab_api_call("fetch all transactions")
    def get_all_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Fetch ALL transactions (approved + unapproved, categorized + uncategorized).

        Used for syncing all YNAB data to local database.

        Args:
            since_date: Only fetch transactions on or after this date.

        Returns:
            List of all transactions.
        """
        budget_id = self._get_budget_id()
        since = since_date.date() if since_date else None

        with self._get_api_client() as api_client:
            transactions_api = ynab.TransactionsApi(api_client)
            response = transactions_api.get_transactions(budget_id, since_date=since)
            return self._convert_transactions(response.data.transactions)

    def test_connection(self) -> dict:
        """Test API connection by fetching user info.

        Returns:
            Dict with connection status and user info.
        """
        try:
            with self._get_api_client() as api_client:
                user_api = ynab.UserApi(api_client)
                response = user_api.get_user()

                return {
                    "success": True,
                    "user_id": response.data.user.id,
                }

        except ynab.ApiException as e:
            return {
                "success": False,
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _convert_transactions(self, transactions) -> list[Transaction]:
        """Convert YNAB SDK transactions to our model."""
        return [self._convert_transaction(t) for t in transactions]

    def _convert_transaction(self, txn) -> Transaction:
        """Convert a single YNAB SDK transaction to our model."""
        # YNAB amounts are in milliunits (1000 = $1.00)
        amount = txn.amount / 1000 if txn.amount else 0.0

        # Handle date - new SDK uses var_date which may be string, date, or datetime
        txn_date = parse_to_datetime(txn.var_date)

        # Handle subtransactions (split transactions)
        subtransactions = []
        is_split = False
        if hasattr(txn, "subtransactions") and txn.subtransactions:
            is_split = True
            for sub in txn.subtransactions:
                sub_amount = sub.amount / 1000 if sub.amount else 0.0
                subtransactions.append(
                    SubTransaction(
                        id=sub.id,
                        transaction_id=txn.id,
                        amount=sub_amount,
                        payee_id=getattr(sub, "payee_id", None),
                        payee_name=getattr(sub, "payee_name", None),
                        memo=getattr(sub, "memo", None),
                        category_id=getattr(sub, "category_id", None),
                        category_name=getattr(sub, "category_name", None),
                    )
                )

        # Handle transfer fields (transfers don't need categories)
        transfer_account_id = getattr(txn, "transfer_account_id", None)
        transfer_account_name = self._get_account_name(transfer_account_id)
        debt_transaction_type = getattr(txn, "debt_transaction_type", None)

        return Transaction(
            id=txn.id,
            date=txn_date,
            amount=amount,
            payee_name=txn.payee_name or "",
            payee_id=txn.payee_id,
            memo=txn.memo,
            account_name=txn.account_name,
            account_id=txn.account_id,
            category_id=txn.category_id,
            category_name=txn.category_name,
            approved=txn.approved,
            cleared=txn.cleared,
            is_split=is_split,
            subtransactions=subtransactions,
            transfer_account_id=transfer_account_id,
            transfer_account_name=transfer_account_name,
            debt_transaction_type=debt_transaction_type,
        )
