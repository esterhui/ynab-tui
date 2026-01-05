"""Mock YNAB client for testing without real API calls.

Loads transaction and category data from CSV files in src/mock_data/.
Supports persistent updates via save_transactions().
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import Category, CategoryGroup, CategoryList, SubTransaction, Transaction
from .ynab_client import YNABClientError

logger = logging.getLogger(__name__)


class MockYNABClient:
    """Mock YNAB client that loads data from CSV files for testing."""

    @staticmethod
    def _sorted_by_date(txns: list[Transaction], limit: Optional[int] = None) -> list[Transaction]:
        """Sort transactions by date descending, optionally limiting results."""
        result = sorted(txns, key=lambda t: t.date, reverse=True)
        return result[:limit] if limit else result

    def __init__(self, data_dir: Optional[str] = None, max_transactions: Optional[int] = None):
        """Initialize mock client.

        Args:
            data_dir: Directory containing CSV files. Defaults to src/mock_data.
            max_transactions: Maximum number of transactions to load (for faster tests).
        """
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            # Default to src/mock_data relative to this file
            self._data_dir = Path(__file__).parent.parent / "mock_data"

        self._max_transactions = max_transactions
        self._transactions: list[Transaction] = []
        self._categories: CategoryList = CategoryList(groups=[])
        self._updated_transactions: dict[str, dict] = {}

        self._load_transactions()
        self._load_categories()

    def _load_transactions(self):
        """Load transactions from CSV file."""
        csv_path = self._data_dir / "transactions.csv"
        if not csv_path.exists():
            return

        # First pass: collect subtransactions by parent_id
        subtxns_by_parent: dict[str, list[SubTransaction]] = {}
        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parent_id = row.get("parent_transaction_id")
                if parent_id:
                    if parent_id not in subtxns_by_parent:
                        subtxns_by_parent[parent_id] = []
                    subtxns_by_parent[parent_id].append(
                        SubTransaction(
                            id=row["id"],
                            transaction_id=parent_id,
                            amount=float(row["amount"]),
                            payee_name=row["payee_name"] if row["payee_name"] else None,
                            memo=row["memo"] if row["memo"] else None,
                            category_id=row["category_id"] if row["category_id"] else None,
                            category_name=row["category_name"] if row["category_name"] else None,
                        )
                    )

        # Second pass: load parent transactions with subtransactions attached
        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip subtransactions (they have a parent_transaction_id)
                if row.get("parent_transaction_id"):
                    continue

                # Respect max_transactions limit for faster tests
                if self._max_transactions and len(self._transactions) >= self._max_transactions:
                    break

                txn_date = datetime.strptime(row["date"], "%Y-%m-%d")
                txn_id = row["id"]
                is_split = row.get("is_split", "0") in ("1", "true", "True")

                self._transactions.append(
                    Transaction(
                        id=txn_id,
                        date=txn_date,
                        amount=float(row["amount"]),
                        payee_name=row["payee_name"],
                        category_id=row["category_id"] if row["category_id"] else None,
                        category_name=row["category_name"] if row["category_name"] else None,
                        account_name=row["account_name"] if row["account_name"] else None,
                        memo=row["memo"] if row["memo"] else None,
                        approved=row["approved"] in ("1", "true", "True"),
                        cleared=row["cleared"] if row["cleared"] else "uncleared",
                        transfer_account_id=row.get("transfer_account_id") or None,
                        transfer_account_name=row.get("transfer_account_name") or None,
                        debt_transaction_type=row.get("debt_transaction_type") or None,
                        is_split=is_split,
                        subtransactions=subtxns_by_parent.get(txn_id, []) if is_split else [],
                    )
                )

    def _load_categories(self):
        """Load categories from CSV file."""
        csv_path = self._data_dir / "categories.csv"
        if not csv_path.exists():
            return

        groups_dict: dict[str, CategoryGroup] = {}

        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                group_id = row["group_id"]

                if group_id not in groups_dict:
                    groups_dict[group_id] = CategoryGroup(
                        id=group_id,
                        name=row["group_name"],
                        categories=[],
                        hidden=row.get("hidden", "false").lower() == "true",
                        deleted=row.get("deleted", "false").lower() == "true",
                    )

                groups_dict[group_id].categories.append(
                    Category(
                        id=row["category_id"],
                        name=row["category_name"],
                        group_id=group_id,
                        group_name=row["group_name"],
                        hidden=row.get("hidden", "false").lower() == "true",
                        deleted=row.get("deleted", "false").lower() == "true",
                    )
                )

        self._categories = CategoryList(groups=list(groups_dict.values()))

    def get_categories(self) -> CategoryList:
        """Return loaded categories."""
        return self._categories

    def get_uncategorized_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Return transactions without a category (excludes transfers)."""
        uncategorized = []
        for txn in self._transactions:
            # Check if updated
            if txn.id in self._updated_transactions:
                continue

            # Use is_uncategorized property (excludes transfers)
            if txn.is_uncategorized or txn.category_name == "Uncategorized":
                if since_date is None or txn.date >= since_date:
                    uncategorized.append(txn)

        return self._sorted_by_date(uncategorized)

    def get_unapproved_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Return unapproved transactions by filtering transactions.csv."""
        unapproved = []
        for txn in self._transactions:
            if txn.id in self._updated_transactions:
                update = self._updated_transactions[txn.id]
                if update.get("approved", txn.approved):
                    continue

            if not txn.approved:
                if since_date is None or txn.date >= since_date:
                    unapproved.append(txn)

        return self._sorted_by_date(unapproved)

    def get_all_pending_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Return all transactions needing attention."""
        uncategorized = self.get_uncategorized_transactions(since_date)
        unapproved = self.get_unapproved_transactions(since_date)

        # Merge and dedupe
        seen = set()
        transactions = []
        for txn in uncategorized + unapproved:
            if txn.id not in seen:
                seen.add(txn.id)
                transactions.append(txn)

        return self._sorted_by_date(transactions)

    def get_recent_transactions(
        self,
        limit: int = 50,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Return recent transactions."""
        txns = (
            [t for t in self._transactions if t.date >= since_date]
            if since_date
            else self._transactions
        )
        return self._sorted_by_date(txns, limit)

    def get_all_transactions(
        self,
        since_date: Optional[datetime] = None,
    ) -> list[Transaction]:
        """Return all transactions for syncing."""
        txns = (
            [t for t in self._transactions if t.date >= since_date]
            if since_date
            else self._transactions
        )
        return self._sorted_by_date(txns)

    def update_transaction_category(
        self,
        transaction_id: str,
        category_id: str,
        approve: bool = True,
    ) -> Transaction:
        """Mock update - stores the update without API call."""
        self._updated_transactions[transaction_id] = {
            "category_id": category_id,
            "approved": approve,
        }

        # Find and return updated transaction
        for txn in self._transactions:
            if txn.id == transaction_id:
                # Return a copy with updated values
                return Transaction(
                    id=txn.id,
                    date=txn.date,
                    amount=txn.amount,
                    payee_name=txn.payee_name,
                    payee_id=txn.payee_id,
                    memo=txn.memo,
                    account_name=txn.account_name,
                    account_id=txn.account_id,
                    category_id=category_id,
                    category_name=self._get_category_name(category_id),
                    approved=approve,
                    cleared=txn.cleared,
                )

        # For testing, return a minimal transaction if not found in mock data
        # (allows testing push functionality with transactions that only exist locally)
        return Transaction(
            id=transaction_id,
            date=datetime.now(),
            amount=0.0,
            payee_name="Mock Update",
            category_id=category_id,
            category_name=self._get_category_name(category_id),
            approved=approve,
        )

    def approve_transaction(self, transaction_id: str) -> Transaction:
        """Mock approve - stores the update without API call."""
        self._updated_transactions[transaction_id] = {
            **self._updated_transactions.get(transaction_id, {}),
            "approved": True,
        }

        for txn in self._transactions:
            if txn.id == transaction_id:
                return Transaction(
                    id=txn.id,
                    date=txn.date,
                    amount=txn.amount,
                    payee_name=txn.payee_name,
                    payee_id=txn.payee_id,
                    memo=txn.memo,
                    account_name=txn.account_name,
                    account_id=txn.account_id,
                    category_id=txn.category_id,
                    category_name=txn.category_name,
                    approved=True,
                    cleared=txn.cleared,
                )

        raise YNABClientError(f"Transaction {transaction_id} not found")

    def update_transaction(
        self,
        transaction_id: str,
        category_id: Optional[str] = None,
        memo: Optional[str] = None,
        approved: Optional[bool] = None,
    ) -> Transaction:
        """Mock generic update - stores the update without API call."""
        # Build update dict with only provided fields
        update = self._updated_transactions.get(transaction_id, {})
        if category_id is not None:
            update["category_id"] = category_id
        if memo is not None:
            update["memo"] = memo
        if approved is not None:
            update["approved"] = approved
        self._updated_transactions[transaction_id] = update

        for txn in self._transactions:
            if txn.id == transaction_id:
                return Transaction(
                    id=txn.id,
                    date=txn.date,
                    amount=txn.amount,
                    payee_name=txn.payee_name,
                    payee_id=txn.payee_id,
                    memo=memo if memo is not None else txn.memo,
                    account_name=txn.account_name,
                    account_id=txn.account_id,
                    category_id=category_id if category_id is not None else txn.category_id,
                    category_name=(
                        self._get_category_name(category_id)
                        if category_id is not None
                        else txn.category_name
                    ),
                    approved=approved if approved is not None else txn.approved,
                    cleared=txn.cleared,
                )

        # For testing, return a minimal transaction if not found
        return Transaction(
            id=transaction_id,
            date=datetime.now(),
            amount=0.0,
            payee_name="Mock Update",
            memo=memo,
            category_id=category_id,
            category_name=self._get_category_name(category_id) if category_id else None,
            approved=approved if approved is not None else False,
        )

    def create_split_transaction(
        self,
        transaction_id: str,
        splits: list[dict],
        approve: bool = True,
    ) -> Transaction:
        """Mock split creation - stores the update without API call."""
        self._updated_transactions[transaction_id] = {
            "splits": splits,
            "approved": approve,
        }

        for txn in self._transactions:
            if txn.id == transaction_id:
                # Build mock subtransactions
                subtransactions = []
                for i, split in enumerate(splits):
                    cat_id = split.get("category_id")
                    subtransactions.append(
                        SubTransaction(
                            id=f"{transaction_id}-split-{i}",
                            transaction_id=transaction_id,
                            amount=split["amount"],
                            category_id=cat_id,
                            category_name=self._get_category_name(cat_id) if cat_id else None,
                            memo=split.get("memo"),
                        )
                    )

                return Transaction(
                    id=txn.id,
                    date=txn.date,
                    amount=txn.amount,
                    payee_name=txn.payee_name,
                    payee_id=txn.payee_id,
                    memo=txn.memo,
                    account_name=txn.account_name,
                    account_id=txn.account_id,
                    category_id="mock-split-category-id",  # YNAB assigns a Split category ID
                    category_name="Split",
                    approved=approve,
                    cleared=txn.cleared,
                    is_split=True,
                    subtransactions=subtransactions,
                )

        raise YNABClientError(f"Transaction {transaction_id} not found")

    def get_budgets(self) -> list[dict]:
        """Return mock budget list."""
        return [
            {
                "id": "mock-budget-id",
                "name": "Mock Budget",
                "last_modified_on": datetime.now(),
            },
            {
                "id": "mock-budget-id-2",
                "name": "Second Mock Budget",
                "last_modified_on": datetime.now(),
            },
        ]

    def set_budget_id(self, budget_id: str) -> None:
        """Set the budget ID. Supports both UUID and name."""
        # Check if it's a name and resolve to ID
        budgets = self.get_budgets()
        for budget in budgets:
            if budget["name"].lower() == budget_id.lower():
                self._current_budget_id = budget["id"]
                return
            if budget["id"] == budget_id:
                self._current_budget_id = budget_id
                return
        # Not found - default to mock budget (user likely has real YNAB budget in config)
        self._current_budget_id = "mock-budget-id"

    def get_current_budget_id(self) -> str:
        """Get the current budget ID."""
        return getattr(self, "_current_budget_id", "mock-budget-id")

    def get_budget_name(self, budget_id: Optional[str] = None) -> str:
        """Get the name of a budget by ID."""
        target_id = budget_id or self.get_current_budget_id()
        for budget in self.get_budgets():
            if budget["id"] == target_id:
                return budget["name"]
        return "Unknown Budget"

    def test_connection(self) -> dict:
        """Return successful mock connection."""
        return {
            "success": True,
            "user_id": "mock-user-id",
        }

    def _get_category_name(self, category_id: str) -> Optional[str]:
        """Look up category name by ID."""
        for group in self._categories.groups:
            for cat in group.categories:
                if cat.id == category_id:
                    return cat.name
        return None

    def save_transactions(self) -> int:
        """Persist in-memory transaction updates to CSV file.

        This enables persistent mock mode - changes made via update_transaction_category()
        or create_split_transaction() are written back to transactions.csv.

        Returns:
            Number of transactions updated in CSV.
        """
        if not self._updated_transactions:
            return 0

        csv_path = self._data_dir / "transactions.csv"
        if not csv_path.exists():
            return 0

        # Read all rows, update matching ones, write back
        rows = []
        new_subtransactions = []
        updated_count = 0

        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames) if reader.fieldnames else []

            # Ensure new columns exist
            if "is_split" not in fieldnames:
                fieldnames = fieldnames + ["is_split", "parent_transaction_id"]

            for row in reader:
                # Skip existing subtransactions if we're about to re-split the parent
                parent_id = row.get("parent_transaction_id", "")
                if parent_id and parent_id in self._updated_transactions:
                    # This subtransaction's parent is being updated - skip it
                    # (new subtransactions will be added below)
                    continue

                if row["id"] in self._updated_transactions:
                    update = self._updated_transactions[row["id"]]

                    if "splits" in update:
                        # Split transaction - mark parent and create subtransactions
                        row["is_split"] = "1"
                        row["category_id"] = ""
                        row["category_name"] = "Split"

                        for i, split in enumerate(update["splits"]):
                            sub_row = {
                                "id": f"{row['id']}-split-{i}",
                                "date": row["date"],
                                "amount": str(split["amount"]),
                                "payee_name": row["payee_name"],
                                "category_id": split.get("category_id", ""),
                                "category_name": self._get_category_name(split.get("category_id"))
                                or "",
                                "account_name": row.get("account_name", ""),
                                "memo": split.get("memo", ""),
                                "approved": "1" if update.get("approved", True) else "0",
                                "cleared": row.get("cleared", ""),
                                "transfer_account_id": "",
                                "transfer_account_name": "",
                                "debt_transaction_type": "",
                                "is_split": "0",
                                "parent_transaction_id": row["id"],
                            }
                            new_subtransactions.append(sub_row)
                    else:
                        # Simple category update
                        if "category_id" in update:
                            row["category_id"] = update["category_id"]
                            row["category_name"] = (
                                self._get_category_name(update["category_id"]) or ""
                            )
                        if "approved" in update:
                            row["approved"] = "1" if update["approved"] else "0"

                    updated_count += 1

                # Ensure new columns have values
                row.setdefault("is_split", "0")
                row.setdefault("parent_transaction_id", "")
                rows.append(row)

        # Add new subtransactions
        rows.extend(new_subtransactions)

        # Write back
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        # Clear in-memory updates (they're now persisted)
        self._updated_transactions.clear()

        return updated_count
