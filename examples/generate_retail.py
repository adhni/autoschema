"""Reproducible synthetic retail data; no real customer information."""

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path


def generate(path="data/retail_complex.csv", orders=1200, seed=42):
    if orders < 1:
        raise ValueError("orders must be positive")
    randomizer = random.Random(seed)
    cities = ["Melbourne", "Sydney", "Brisbane", "Perth", "Adelaide", "Hobart"]
    customers = [
        {
            "customer_id": f"C{i:04d}",
            "customer_name": f"Customer {i:04d}",
            "customer_city": cities[i % 6],
            "customer_segment": randomizer.choice(["Retail", "Trade", "Member"]),
        }
        for i in range(120)
    ]
    products = [
        {
            "product_id": f"P{i:03d}",
            "product_name": f"Product {i:03d}",
            "category": randomizer.choice(["Home", "Garden", "Office", "Kitchen", "Outdoors"]),
            "brand": randomizer.choice(["Cedar", "Atlas", "Fern", "Harbour"]),
            "unit_price": f"{randomizer.randint(500, 25000) / 100:.2f}",
        }
        for i in range(60)
    ]
    warehouses = [
        {
            "warehouse_id": f"W{i}",
            "warehouse_name": f"Distribution centre {i}",
            "warehouse_city": cities[i],
            "warehouse_postcode": ["0300", "2000", "4000", "6000"][i],
        }
        for i in range(4)
    ]
    stock = {
        (p["product_id"], w["warehouse_id"]): {
            "bin_location": f"{randomizer.choice('ABCDEFGH')}-{randomizer.randint(1, 15):02d}",
            "reorder_point": randomizer.randint(5, 40),
        }
        for p in products
        for w in warehouses
    }
    rows = []
    for order in range(orders):
        base = {
            "order_id": f"O{order:06d}",
            "order_date": str(date(2025, 1, 1) + timedelta(days=randomizer.randrange(90))),
            "order_status": randomizer.choice(["Shipped", "Delivered", "Processing", "Returned"]),
            "sales_channel": randomizer.choice(["Web", "Store", "Phone"]),
            **randomizer.choice(customers),
        }
        for line in range(1, 5):
            product, warehouse = randomizer.choice(products), randomizer.choice(warehouses)
            rows.append(
                {
                    **base,
                    "line_number": line,
                    **product,
                    **warehouse,
                    **stock[(product["product_id"], warehouse["warehouse_id"])],
                    "quantity": randomizer.randint(1, 8),
                    "discount_percent": randomizer.choice([0, 0, 0, 5, 10, 15]),
                    "delivery_note": randomizer.choice(
                        [
                            "",
                            "",
                            "Leave at reception",
                            "Call on arrival",
                            "Customer's side door",
                            "Fragile, handle carefully",
                            "Café delivery",
                        ]
                    ),
                }
            )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return target, len(rows), len(rows[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/retail_complex.csv")
    parser.add_argument("--orders", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    path, rows, columns = generate(args.out, args.orders, args.seed)
    print(f"Generated {path}: {rows:,} rows × {columns} columns (synthetic; seed {args.seed})")
