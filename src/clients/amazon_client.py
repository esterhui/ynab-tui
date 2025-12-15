"""Amazon Orders client for fetching order history.

Wraps the amazon-orders library to provide order data for matching
with YNAB transactions.
"""

from datetime import datetime, timedelta
from typing import Optional

from amazonorders.orders import AmazonOrders
from amazonorders.session import AmazonSession

from ..config import AmazonConfig
from ..db.database import Database
from ..models import AmazonOrder, OrderItem


class AmazonClientError(Exception):
    """Error fetching Amazon orders."""

    pass


class AmazonClient:
    """Client for fetching Amazon order history.

    Used by 'pull' command to fetch orders from Amazon API and cache in database.
    """

    def __init__(
        self,
        config: AmazonConfig,
        db: Optional[Database] = None,
    ):
        """Initialize Amazon client.

        Args:
            config: Amazon configuration with credentials.
            db: Optional database for caching orders.
        """
        self._config = config
        self._db = db
        self._session: Optional[AmazonSession] = None
        self._orders_api: Optional[AmazonOrders] = None

    def _ensure_session(self):
        """Ensure we have an authenticated Amazon session."""
        if self._session is not None:
            return

        if not self._config.username or not self._config.password:
            raise AmazonClientError(
                "Amazon username and password are required. "
                "Set AMAZON_USERNAME and AMAZON_PASSWORD environment variables "
                "or configure in config.toml"
            )

        try:
            self._session = AmazonSession(
                self._config.username,
                self._config.password,
                otp_secret_key=self._config.otp_secret if self._config.otp_secret else None,
            )
            self._session.login()
            self._orders_api = AmazonOrders(self._session)
        except Exception as e:
            raise AmazonClientError(f"Failed to authenticate with Amazon: {e}") from e

    def get_orders_for_year(self, year: int) -> list[AmazonOrder]:
        """Fetch all orders for a specific year.

        Args:
            year: Year to fetch orders for.

        Returns:
            List of Amazon orders.
        """
        self._ensure_session()
        assert self._orders_api is not None  # Set by _ensure_session

        try:
            orders = self._orders_api.get_order_history(year=year, full_details=True)
            return [self._convert_order(o) for o in orders]
        except Exception as e:
            raise AmazonClientError(f"Failed to fetch orders for {year}: {e}") from e

    def get_orders_in_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[AmazonOrder]:
        """Fetch orders within a date range.

        Args:
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            List of Amazon orders in the range.
        """
        # Fetch from Amazon
        self._ensure_session()

        # Get unique years in range
        years = set()
        current = start_date
        while current <= end_date:
            years.add(current.year)
            current += timedelta(days=365)
        years.add(end_date.year)

        all_orders = []
        for year in sorted(years):
            try:
                year_orders = self.get_orders_for_year(year)
                # Filter to date range
                for order in year_orders:
                    if start_date <= order.order_date <= end_date:
                        all_orders.append(order)
                        # Cache the order header (items stored via upsert_amazon_order_items)
                        if self._db:
                            self._db.cache_amazon_order(
                                order_id=order.order_id,
                                order_date=order.order_date,
                                total=order.total,
                            )
            except AmazonClientError:
                # Log but continue with other years
                pass

        return all_orders

    def get_recent_orders(self, days: int = 30) -> list[AmazonOrder]:
        """Fetch orders from the last N days.

        Args:
            days: Number of days to look back.

        Returns:
            List of recent Amazon orders.
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        return self.get_orders_in_range(start_date, end_date)

    def find_matching_order(
        self,
        amount: float,
        date: datetime,
        window_days: int = 3,
    ) -> Optional[AmazonOrder]:
        """Find an order matching the given amount and date.

        Args:
            amount: Transaction amount (positive, absolute value).
            date: Transaction date.
            window_days: Days before/after to search.

        Returns:
            Matching order or None.
        """
        # Check cache first
        if self._db:
            cached = self._db.get_cached_order_by_amount(
                amount=amount,
                date=date,
                window_days=window_days,
            )
            if cached:
                return AmazonOrder(
                    order_id=cached.order_id,
                    order_date=cached.order_date,
                    total=cached.total,
                    items=[OrderItem(name=name) for name in cached.items],
                    from_cache=True,
                    fetched_at=cached.fetched_at,
                )

        # Fetch from Amazon
        start_date = date - timedelta(days=window_days)
        end_date = date + timedelta(days=window_days)

        orders = self.get_orders_in_range(start_date, end_date)

        # Find best match by amount
        best_match = None
        best_diff = float("inf")

        for order in orders:
            diff = abs(order.total - amount)
            if diff < best_diff and diff < 0.10:  # Within 10 cents
                best_diff = diff
                best_match = order

        return best_match

    def _convert_order(self, order) -> AmazonOrder:
        """Convert amazon-orders Order to our model."""
        items = []
        if hasattr(order, "items") and order.items:
            for item in order.items:
                items.append(
                    OrderItem(
                        name=item.title if hasattr(item, "title") else str(item),
                        price=item.price if hasattr(item, "price") else None,
                        quantity=item.quantity if hasattr(item, "quantity") else 1,
                    )
                )

        # Parse order date
        order_date = order.order_placed_date
        if isinstance(order_date, str):
            # Try common formats
            for fmt in ["%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y"]:
                try:
                    order_date = datetime.strptime(order_date, fmt)
                    break
                except ValueError:
                    continue
            else:
                order_date = datetime.now()  # Fallback
        elif hasattr(order_date, "year") and not isinstance(order_date, datetime):
            # Convert date to datetime
            order_date = datetime.combine(order_date, datetime.min.time())

        # Parse total
        total = 0.0
        if hasattr(order, "grand_total"):
            total_str = str(order.grand_total)
            # Remove currency symbol and commas
            total_str = total_str.replace("$", "").replace(",", "").strip()
            try:
                total = float(total_str)
            except ValueError:
                total = 0.0  # Keep default on parse failure

        return AmazonOrder(
            order_id=order.order_number if hasattr(order, "order_number") else "",
            order_date=order_date,
            total=total,
            items=items,
            status=order.order_status if hasattr(order, "order_status") else "unknown",
            from_cache=False,
            fetched_at=datetime.now(),
        )


class MockAmazonClient:
    """Mock client for testing without Amazon credentials.

    Loads order data from CSV files in src/mock_data/ for realistic testing.
    """

    def __init__(self, data_dir: Optional[str] = None):
        """Initialize mock client.

        Args:
            data_dir: Directory containing CSV files. Defaults to src/mock_data.
        """
        from pathlib import Path

        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            # Default to src/mock_data relative to this file
            self._data_dir = Path(__file__).parent.parent / "mock_data"

        self._mock_orders: list[AmazonOrder] = []
        self._load_orders()

    def _load_orders(self):
        """Load orders from CSV file."""
        import csv

        csv_path = self._data_dir / "orders.csv"
        if not csv_path.exists():
            return

        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                order_date = datetime.strptime(row["order_date"], "%Y-%m-%d")

                # Parse items from separator-separated string
                # Format: "item1|price1 ||| item2|price2" or "item1 ||| item2" (no prices)
                # Uses " ||| " as separator since item names can contain "; "
                items_str = row.get("items", "")
                items = []
                if items_str:
                    for item_entry in items_str.split(" ||| "):
                        item_entry = item_entry.strip()
                        if item_entry:
                            # Check for price separator
                            if "|" in item_entry:
                                name, price_str = item_entry.rsplit("|", 1)
                                try:
                                    price = float(price_str)
                                except ValueError:
                                    price = None
                                items.append(OrderItem(name=name.strip(), price=price))
                            else:
                                items.append(OrderItem(name=item_entry))

                self._mock_orders.append(
                    AmazonOrder(
                        order_id=row["order_id"],
                        order_date=order_date,
                        total=float(row["total"]),
                        items=items,
                        status=row.get("status", "unknown"),
                        from_cache=True,
                        fetched_at=datetime.now(),
                    )
                )

    def add_mock_order(self, order: AmazonOrder):
        """Add a mock order for testing."""
        self._mock_orders.append(order)

    def get_orders_for_year(self, year: int) -> list[AmazonOrder]:
        """Return mock orders for year."""
        return [o for o in self._mock_orders if o.order_date.year == year]

    def get_orders_in_range(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[AmazonOrder]:
        """Return mock orders in range."""
        return [o for o in self._mock_orders if start_date <= o.order_date <= end_date]

    def get_recent_orders(self, days: int = 30) -> list[AmazonOrder]:
        """Return recent mock orders."""
        cutoff = datetime.now() - timedelta(days=days)
        return [o for o in self._mock_orders if o.order_date >= cutoff]

    def find_matching_order(
        self,
        amount: float,
        date: datetime,
        window_days: int = 3,
    ) -> Optional[AmazonOrder]:
        """Find matching mock order."""
        start = date - timedelta(days=window_days)
        end = date + timedelta(days=window_days)

        for order in self._mock_orders:
            if start <= order.order_date <= end:
                if abs(order.total - amount) < 0.10:
                    return order
        return None
