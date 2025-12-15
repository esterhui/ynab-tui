#!/usr/bin/env python3
"""Generate synthetic mock data for YNAB TUI testing.

Creates fake but realistic transaction, category, and Amazon order data
to replace PII-containing mock files while preserving all testing scenarios.

Usage:
    uv run python src/mock_data/generate_mock_data.py
"""

import csv
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
BUDGET_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
START_DATE = datetime(2025, 10, 1)
END_DATE = datetime(2025, 12, 14)
OUTPUT_DIR = Path(__file__).parent

# Set seed for reproducibility
random.seed(42)


def generate_uuid() -> str:
    """Generate a random UUID."""
    return str(uuid.uuid4())


# ============================================================================
# Category Data
# ============================================================================

CATEGORY_GROUPS = [
    {
        "name": "Housing",
        "categories": [
            "Rent/Mortgage",
            "Electricity",
            "Water/Sewer",
            "Natural Gas",
            "Internet",
            "Home Maintenance",
            "Home Insurance",
        ],
    },
    {
        "name": "Transportation",
        "categories": [
            "Gas",
            "Car Insurance",
            "Car Maintenance",
            "Parking",
            "Public Transit",
        ],
    },
    {
        "name": "Food",
        "categories": [
            "Groceries",
            "Dining Out",
            "Coffee Shops",
        ],
    },
    {
        "name": "Bills & Utilities",
        "categories": [
            "Phone",
            "Subscriptions",
            "Software",
        ],
    },
    {
        "name": "Personal",
        "categories": [
            "Clothing",
            "Healthcare",
            "Personal Care",
            "Fitness",
            "Education",
        ],
    },
    {
        "name": "Entertainment",
        "categories": [
            "Entertainment",
            "Hobbies",
            "Travel",
            "Gifts",
        ],
    },
    {
        "name": "Shopping",
        "categories": [
            "General Shopping",
            "Electronics",
            "Home Goods",
            "Baby & Kids",
        ],
    },
    {
        "name": "Financial",
        "categories": [
            "Savings Transfer",
            "Investment",
            "Emergency Fund",
            "Credit Card Payment",
        ],
    },
    {
        "name": "Income",
        "categories": [
            "Inflow: Ready to Assign",
            "Reimbursement",
        ],
    },
    {
        "name": "Internal Master Category",
        "categories": [
            "Uncategorized",
        ],
    },
]

# ============================================================================
# Payee Data
# ============================================================================

PAYEES = {
    "Groceries": [
        "Valley Fresh Market",
        "Green Leaf Grocers",
        "Sunshine Foods",
        "Corner Mart",
    ],
    "Dining Out": [
        "Golden Dragon Restaurant",
        "Riverside Cafe",
        "Pizza Palace",
        "Burger Barn",
        "Thai Garden",
        "Morning Glory Bakery",
    ],
    "Coffee Shops": [
        "Bean There Coffee",
        "Daily Grind Cafe",
        "Roasted Bliss",
    ],
    "Gas": [
        "QuickFill Gas",
        "Speedy Fuel",
        "Highway Gas Station",
    ],
    "Subscriptions": [
        "StreamFlix",
        "MusicBox Premium",
        "CloudStorage Pro",
        "NewsDaily Plus",
    ],
    "Electricity": ["Metro Power Co"],
    "Water/Sewer": ["City Water District"],
    "Internet": ["FastNet Internet"],
    "Phone": ["MobileFirst Wireless"],
    "Clothing": ["Fashion Forward", "Urban Threads", "Classic Outfitters"],
    "Electronics": ["TechMart Electronics", "Gadget Galaxy"],
    "Home Goods": ["HomeStyle Decor", "Comfort Living"],
    "Healthcare": ["City Medical Center", "QuickCare Clinic", "Valley Pharmacy"],
    "Fitness": ["FitLife Gym", "Yoga Studio"],
    "Entertainment": ["Cinema World", "Game Zone", "Concert Hall"],
    "Car Maintenance": ["AutoCare Service Center", "Quick Lube Express"],
    "Baby & Kids": ["Little Ones Shop", "Kids Corner"],
}

AMAZON_PAYEES = ["Amazon", "Amazon Prime", "Amazon Marketplace", "AMZN Mktp"]

ACCOUNTS = ["Main Checking", "Rewards Visa", "Savings", "Investment Account"]

# ============================================================================
# Amazon Product Data
# ============================================================================

AMAZON_PRODUCTS = {
    "Electronics": [
        ("USB-C Charging Cable 6ft", 12.99),
        ("Wireless Bluetooth Earbuds", 29.99),
        ("Phone Screen Protector 2-Pack", 8.99),
        ("Portable Power Bank 10000mAh", 24.99),
        ("HDMI Cable 10ft", 11.99),
        ("Laptop Stand Adjustable", 34.99),
        ("Webcam HD 1080p", 39.99),
        ("Mouse Pad Large", 12.99),
    ],
    "Home": [
        ("Kitchen Utensil Set 5-Piece", 22.99),
        ("Storage Containers 10-Pack", 18.99),
        ("LED Desk Lamp", 27.99),
        ("Throw Blanket Fleece", 24.99),
        ("Wall Hooks 4-Pack", 9.99),
        ("Shower Curtain Liner", 14.99),
        ("Dish Drying Rack", 29.99),
        ("Coffee Mug Set 4-Pack", 19.99),
    ],
    "Baby": [
        ("Baby Diapers Size 4 100-Count", 44.99),
        ("Baby Wipes 8-Pack", 22.99),
        ("Sippy Cups 4-Pack", 14.99),
        ("Baby Food Pouches 12-Pack", 18.99),
        ("Teething Toys Set", 12.99),
        ("Baby Blanket Soft", 19.99),
        ("Pacifiers 4-Pack", 9.99),
        ("Baby Bath Toys Set", 16.99),
    ],
    "Personal Care": [
        ("Shampoo Large Bottle", 12.99),
        ("Electric Toothbrush", 34.99),
        ("Vitamins Daily 90-Count", 19.99),
        ("Face Moisturizer", 16.99),
        ("Hair Brush Detangling", 11.99),
        ("Sunscreen SPF 50", 14.99),
    ],
    "Pet": [
        ("Cat Food Premium 24-Pack", 28.99),
        ("Dog Treats Training", 14.99),
        ("Pet Bed Medium", 34.99),
        ("Cat Litter 40lb", 22.99),
    ],
    "Office": [
        ("Notebooks 3-Pack", 12.99),
        ("Pens Ballpoint 24-Pack", 8.99),
        ("Desk Organizer", 19.99),
        ("Sticky Notes Variety", 11.99),
    ],
}


@dataclass
class CategoryInfo:
    """Stores category info for reference."""

    id: str
    name: str
    group_id: str
    group_name: str


@dataclass
class AmazonOrderInfo:
    """Stores Amazon order info for matching to transactions."""

    order_id: str
    order_date: datetime
    total: float
    items: list[tuple[str, float]]  # (name, price)


def generate_categories() -> dict[str, CategoryInfo]:
    """Generate categories and write to CSV. Returns lookup dict by name."""
    categories: dict[str, CategoryInfo] = {}
    rows = []

    for group in CATEGORY_GROUPS:
        group_id = generate_uuid()
        group_name = group["name"]

        for cat_name in group["categories"]:
            cat_id = generate_uuid()
            categories[cat_name] = CategoryInfo(
                id=cat_id,
                name=cat_name,
                group_id=group_id,
                group_name=group_name,
            )
            rows.append(
                {
                    "group_id": group_id,
                    "group_name": group_name,
                    "category_id": cat_id,
                    "budget_id": BUDGET_ID,
                    "category_name": cat_name,
                    "hidden": "false",
                    "deleted": "false",
                }
            )

    # Write CSV
    csv_path = OUTPUT_DIR / "categories.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "group_id",
                "group_name",
                "category_id",
                "budget_id",
                "category_name",
                "hidden",
                "deleted",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} categories")
    return categories


def generate_amazon_orders() -> list[AmazonOrderInfo]:
    """Generate Amazon orders and write to CSV. Returns list for transaction matching."""
    orders: list[AmazonOrderInfo] = []
    rows = []

    # Generate order ID in Amazon format
    def make_order_id() -> str:
        return f"{random.randint(111, 119)}-{random.randint(1000000, 9999999)}-{random.randint(1000000, 9999999)}"

    # Generate dates spread across the date range
    date_range = (END_DATE - START_DATE).days
    order_dates = [START_DATE + timedelta(days=random.randint(0, date_range)) for _ in range(45)]
    order_dates.sort(reverse=True)

    for i, order_date in enumerate(order_dates):
        order_id = make_order_id()

        # Decide order type
        if i < 10:
            # Multi-item orders for split testing (first 10)
            num_items = random.randint(2, 4)
            category = random.choice(list(AMAZON_PRODUCTS.keys()))
            available_items = AMAZON_PRODUCTS[category].copy()

            # Mix in items from other categories for variety
            other_category = random.choice(
                [c for c in AMAZON_PRODUCTS.keys() if c != category]
            )
            available_items.extend(random.sample(AMAZON_PRODUCTS[other_category], 2))

            items = random.sample(available_items, min(num_items, len(available_items)))
            total = round(sum(price for _, price in items), 2)
        elif i < 13:
            # Zero total orders (returns/cancelled)
            items = []
            total = 0.0
        else:
            # Single item orders
            category = random.choice(list(AMAZON_PRODUCTS.keys()))
            item = random.choice(AMAZON_PRODUCTS[category])
            items = [item]
            total = item[1]

        orders.append(
            AmazonOrderInfo(
                order_id=order_id,
                order_date=order_date,
                total=total,
                items=items,
            )
        )

        # Format items for CSV
        if items:
            items_str = " ||| ".join(f"{name}|{price}" for name, price in items)
        else:
            items_str = ""

        rows.append(
            {
                "order_id": order_id,
                "order_date": order_date.strftime("%Y-%m-%d"),
                "total": total,
                "items": items_str,
            }
        )

    # Write CSV
    csv_path = OUTPUT_DIR / "orders.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["order_id", "order_date", "total", "items"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} Amazon orders ({sum(1 for o in orders if len(o.items) > 1)} multi-item)")
    return orders


def generate_transactions(
    categories: dict[str, CategoryInfo],
    amazon_orders: list[AmazonOrderInfo],
) -> None:
    """Generate transactions and write to CSV."""
    rows = []

    # Track used order indices to avoid duplicate matches
    used_orders: set[int] = set()

    def add_transaction(
        date: datetime,
        amount: float,
        payee: str,
        category_name: str | None,
        account: str = "Rewards Visa",
        memo: str = "",
        approved: bool = True,
        cleared: str = "cleared",
        transfer_account_id: str = "",
        transfer_account_name: str = "",
        debt_transaction_type: str = "",
        is_split: bool = False,
    ) -> None:
        cat = categories.get(category_name) if category_name else None
        rows.append(
            {
                "id": generate_uuid(),
                "budget_id": BUDGET_ID,
                "date": date.strftime("%Y-%m-%d"),
                "amount": amount,
                "payee_name": payee,
                "category_id": cat.id if cat else "",
                "category_name": category_name or "Uncategorized",
                "account_name": account,
                "memo": memo,
                "approved": "1" if approved else "0",
                "cleared": cleared,
                "transfer_account_id": transfer_account_id,
                "transfer_account_name": transfer_account_name,
                "debt_transaction_type": debt_transaction_type,
                "is_split": "1" if is_split else "0",
                "parent_transaction_id": "",
            }
        )

    # 1. Amazon transactions that match orders (uncategorized for TUI workflow)
    print("Generating Amazon transactions...")
    amazon_txn_count = 0
    for i, order in enumerate(amazon_orders):
        if order.total <= 0:
            continue
        if i in used_orders:
            continue

        # Create matching transaction 1-7 days after order (Stage 1 matching)
        days_after = random.randint(1, 7)
        txn_date = order.order_date + timedelta(days=days_after)
        if txn_date > END_DATE:
            txn_date = END_DATE

        payee = random.choice(AMAZON_PAYEES)

        # First 20 Amazon transactions are uncategorized (for TUI workflow testing)
        if amazon_txn_count < 20:
            category = None
            approved = amazon_txn_count >= 15  # Some uncategorized but approved
        else:
            category = random.choice(["Electronics", "Home Goods", "Baby & Kids", "General Shopping"])
            approved = True

        add_transaction(
            date=txn_date,
            amount=-order.total,
            payee=payee,
            category_name=category,
            approved=approved,
        )
        used_orders.add(i)
        amazon_txn_count += 1

        if amazon_txn_count >= 35:
            break

    # 2. Regular categorized transactions (recurring payees)
    print("Generating regular transactions...")
    current_date = END_DATE
    while current_date >= START_DATE and len(rows) < 200:
        # Generate 2-5 transactions per day
        num_txns = random.randint(2, 5)
        for _ in range(num_txns):
            # Pick a category and matching payee
            category_name = random.choice(list(PAYEES.keys()))
            payee = random.choice(PAYEES[category_name])

            # Generate realistic amount for category
            if category_name == "Groceries":
                amount = round(random.uniform(25, 150), 2)
            elif category_name == "Dining Out":
                amount = round(random.uniform(15, 80), 2)
            elif category_name == "Coffee Shops":
                amount = round(random.uniform(4, 12), 2)
            elif category_name == "Gas":
                amount = round(random.uniform(30, 70), 2)
            elif category_name in ["Electricity", "Water/Sewer", "Internet", "Phone"]:
                amount = round(random.uniform(50, 200), 2)
            elif category_name == "Subscriptions":
                amount = round(random.uniform(9.99, 19.99), 2)
            else:
                amount = round(random.uniform(10, 100), 2)

            add_transaction(
                date=current_date,
                amount=-amount,
                payee=payee,
                category_name=category_name,
                approved=True,
            )

        current_date -= timedelta(days=1)

    # 3. Unapproved transactions (for approval workflow testing)
    print("Generating unapproved transactions...")
    for _ in range(12):
        category_name = random.choice(list(PAYEES.keys()))
        payee = random.choice(PAYEES[category_name])
        amount = round(random.uniform(10, 100), 2)
        date = START_DATE + timedelta(days=random.randint(0, (END_DATE - START_DATE).days))

        add_transaction(
            date=date,
            amount=-amount,
            payee=payee,
            category_name=category_name,
            approved=False,
        )

    # 4. Transfer transactions (pairs)
    print("Generating transfer transactions...")
    checking_id = generate_uuid()
    savings_id = generate_uuid()
    visa_id = generate_uuid()

    # Credit card payment transfers
    for i in range(4):
        date = START_DATE + timedelta(days=i * 20 + 5)
        amount = round(random.uniform(500, 2000), 2)

        # From checking to visa (payment)
        add_transaction(
            date=date,
            amount=-amount,
            payee="Transfer : Rewards Visa",
            category_name=None,
            account="Main Checking",
            transfer_account_id=visa_id,
            transfer_account_name="Rewards Visa",
        )
        # To visa from checking
        add_transaction(
            date=date,
            amount=amount,
            payee="Transfer : Main Checking",
            category_name=None,
            account="Rewards Visa",
            transfer_account_id=checking_id,
            transfer_account_name="Main Checking",
        )

    # Savings transfers
    for i in range(3):
        date = START_DATE + timedelta(days=i * 25 + 10)
        amount = round(random.uniform(200, 500), 2)

        add_transaction(
            date=date,
            amount=-amount,
            payee="Transfer : Savings",
            category_name="Savings Transfer",
            account="Main Checking",
            transfer_account_id=savings_id,
            transfer_account_name="Savings",
        )
        add_transaction(
            date=date,
            amount=amount,
            payee="Transfer : Main Checking",
            category_name=None,
            account="Savings",
            transfer_account_id=checking_id,
            transfer_account_name="Main Checking",
        )

    # 5. Reconciliation adjustments (for investment accounts)
    print("Generating reconciliation adjustments...")
    for i in range(5):
        date = START_DATE + timedelta(days=i * 15)
        amount = round(random.uniform(-500, 2000), 2)

        add_transaction(
            date=date,
            amount=amount,
            payee="Reconciliation Balance Adjustment",
            category_name=None,
            account="Investment Account",
            memo="Entered automatically by YNAB",
            cleared="reconciled",
        )

    # 6. Income transactions
    print("Generating income transactions...")
    for i in range(3):
        date = START_DATE + timedelta(days=i * 30 + 1)
        amount = round(random.uniform(3000, 5000), 2)

        add_transaction(
            date=date,
            amount=amount,
            payee="Employer Direct Deposit",
            category_name="Inflow: Ready to Assign",
            account="Main Checking",
        )

    # Sort by date descending
    rows.sort(key=lambda r: r["date"], reverse=True)

    # Write CSV
    csv_path = OUTPUT_DIR / "transactions.csv"
    fieldnames = [
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

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Print summary
    uncategorized = sum(1 for r in rows if not r["category_id"] or r["category_name"] == "Uncategorized")
    unapproved = sum(1 for r in rows if r["approved"] == "0")
    transfers = sum(1 for r in rows if r["transfer_account_id"])
    amazon = sum(1 for r in rows if "Amazon" in r["payee_name"] or "AMZN" in r["payee_name"])

    print(f"Generated {len(rows)} transactions:")
    print(f"  - {uncategorized} uncategorized")
    print(f"  - {unapproved} unapproved")
    print(f"  - {transfers} transfers")
    print(f"  - {amazon} Amazon")


def main():
    """Generate all mock data files."""
    print("=" * 60)
    print("Generating synthetic mock data for YNAB TUI")
    print("=" * 60)
    print()

    categories = generate_categories()
    print()

    amazon_orders = generate_amazon_orders()
    print()

    generate_transactions(categories, amazon_orders)
    print()

    print("=" * 60)
    print("Done! Files written to:")
    print(f"  - {OUTPUT_DIR / 'categories.csv'}")
    print(f"  - {OUTPUT_DIR / 'orders.csv'}")
    print(f"  - {OUTPUT_DIR / 'transactions.csv'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
