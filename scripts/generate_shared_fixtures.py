"""Regenerate deterministic shared fixtures; public snapshots are never downloaded here."""

import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "r/autoschemaR/inst/validation"


def write_csv(name, columns, rows, *, delimiter=",", bom=False, line_end="\n"):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator=line_end)
    writer.writerow(columns)
    writer.writerows(rows)
    content = stream.getvalue().encode("utf-8-sig" if bom else "utf-8")
    (ROOT / name).write_bytes(content)


def fingerprint(path):
    content = path.read_bytes()
    return {"sha256": hashlib.sha256(content).hexdigest(), "md5": hashlib.md5(content).hexdigest()}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    public_hashes = {
        "penguins.csv": "f204db2c753b0937caac3cb35258562c14f073e4bbc76be24b4c51ce22767a93",
        "bike_daily.csv": "a6bcf826782d3c0fbfdcbeead17cd0884185a0dafe8ff10cd48a874ee7ba18be",
    }
    for name in public_hashes:
        if not (ROOT / name).is_file():
            raise SystemExit(f"Missing public snapshot: {ROOT / name}; see its README for sources.")
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != public_hashes[name]:
            raise SystemExit(
                f"Public snapshot changed: {name}; review provenance before updating its pin."
            )
    with (ROOT / "penguins.csv").open(encoding="utf-8", newline="") as source:
        penguins = list(csv.reader(source))
    write_csv(
        "penguins_blanks.csv",
        penguins[0],
        [["" if x == "NA" else x for x in row] for row in penguins[1:]],
    )

    columns = [
        "order_id",
        "line_number",
        "customer_id",
        "customer_name",
        "customer_city",
        "product_id",
        "product_name",
        "postcode",
        "quantity",
        "unit_price",
        "note",
    ]
    cities = ["London", "Paris", "Montr\u00e9al", "Kuala Lumpur", "Melbourne"]
    rows = []
    for order in range(30):
        customer = order % 5
        for line in range(1, 5):
            product = (order * 7 + line) % 8
            rows.append(
                [
                    f"O{order:03d}",
                    line,
                    f"C{customer:02d}",
                    ["Amina", "O'Brien", "Zo\u00eb", "Yusuf", "Lin"][customer],
                    cities[customer],
                    f"P{product:02d}",
                    f"Product {product}",
                    f"00{customer:02d}",
                    (order + line) % 7 + 1,
                    f"{product + 1}.50",
                    ["", "NA", "two\nlines", 'commas, quotes "here"'][line - 1],
                ]
            )
    write_csv("messy_orders.csv", columns, rows)
    write_csv(
        "conflicts.csv",
        ["row_id", "customer_id", "city"],
        [[i + 1, "AB"[i % 2], "XY"[(i // 2) % 2]] for i in range(32)],
    )
    wide_columns = ["row_id"] + [f"attribute_{i:03d}" for i in range(128)]
    write_csv(
        "wide.csv",
        wide_columns,
        [
            [row] + [f"v{(row * (col % 5 + 1) + col) % (col % 11 + 2)}" for col in range(128)]
            for row in range(1, 33)
        ],
    )
    prefix = "customer_" + "x" * 260
    write_csv(
        "long_names.csv",
        ["row_id", prefix + "_first_id", "city", prefix + "_second_id", "name"],
        [
            [
                i + 1,
                "AB"[i % 2],
                ["London", "Paris"][i % 2],
                "CD"[(i // 2) % 2],
                ["Amina", "Yusuf"][(i // 2) % 2],
            ]
            for i in range(24)
        ],
    )
    unusual_columns = ["row_id", 'odd; "column"\nname', "<script>alert(1)</script>"]
    unusual_rows = [
        [str(i + 1), value, ["001", "NA", ""][i % 3]]
        for i, value in enumerate(
            [
                "a\nb",
                "a\r\nb",
                "a\rb",
                "caf\u00e9",
                'O\'Brien; "quoted"',
                "",
                "padded ",
                "\u4e2d\u6587",
            ]
        )
    ]
    write_csv(
        "unusual_text.csv", unusual_columns, unusual_rows, delimiter=";", bom=True, line_end="\r\n"
    )
    write_csv(
        "numeric_formats.csv",
        ["row_id", "postcode", "fixed", "large", "scientific", "signed_zero", "precision", "blank"],
        [
            [
                i + 1,
                f"00{i:03d}",
                f"{i + 1}.00",
                "9223372036854775808",
                "1e3",
                ["-0", "-0.0"][i % 2],
                ["1.000000000000001", "0.30000000000000004"][i % 2],
                "",
            ]
            for i in range(16)
        ],
    )
    write_csv("quoted_empty.csv", ["value"], [[""], ["x"], [""]])
    invalid = {
        "duplicate_header.csv": b"id,id\n1,2\n",
        "case_header.csv": b"id,ID\n1,2\n",
        "ragged.csv": b"id,value\n1,a,extra\n",
        "unclosed.csv": b'id,value\n1,"unclosed\n',
        "empty.csv": b"id,value\n",
        "nul_bytes.csv": b"id,value\n1,a\x00b\n",
    }
    for name, content in invalid.items():
        (ROOT / name).write_bytes(content)

    cases = [
        {
            "id": "penguins_original",
            "file": "penguins.csv",
            "origin": "public",
            "features": ["literal NA tokens", "mixed measurements"],
        },
        {
            "id": "penguins_blank_missing",
            "file": "penguins_blanks.csv",
            "origin": "derived-public",
            "features": ["missing fields", "duplicates"],
        },
        {
            "id": "bike_daily",
            "file": "bike_daily.csv",
            "origin": "public",
            "options": {"key_columns": ["dteday"]},
            "required_dependencies": [
                {"keys": ["holiday", "weekday"], "attributes": ["workingday"]}
            ],
            "features": ["calendar dependencies", "weather measurements"],
        },
        {
            "id": "messy_orders",
            "file": "messy_orders.csv",
            "options": {"key_columns": ["order_id", "line_number"]},
            "required_dependencies": [
                {
                    "keys": ["customer_id"],
                    "attributes": ["customer_name", "customer_city", "postcode"],
                }
            ],
            "features": ["composite key", "unicode", "quoted newlines", "blanks", "leading zeros"],
        },
        {
            "id": "conflicting_customers",
            "file": "conflicts.csv",
            "options": {"key_columns": ["row_id"]},
            "forbidden_dependencies": [{"keys": ["customer_id"], "attributes": ["city"]}],
            "expected_dimensions": 0,
        },
        {
            "id": "wide_bounded_search",
            "file": "wide.csv",
            "options": {"key_columns": ["row_id"], "max_candidate_columns": 8, "max_checks": 12},
            "expect_search_warning": True,
        },
        {
            "id": "long_identifiers",
            "file": "long_names.csv",
            "options": {"key_columns": ["row_id"]},
        },
        {
            "id": "unusual_text",
            "file": "unusual_text.csv",
            "options": {"delimiter": ";", "key_columns": ["row_id"]},
            "expected_records": unusual_rows,
        },
        {
            "id": "numeric_text_formats",
            "file": "numeric_formats.csv",
            "options": {"key_columns": ["row_id"]},
        },
        {
            "id": "quoted_empty_rows",
            "file": "quoted_empty.csv",
            "expected_records": [[""], ["x"], [""]],
        },
    ]
    for name in invalid:
        cases.append(
            {"id": name.removesuffix(".csv"), "file": name, "expected_error": "invalid_data"}
        )
    cases.append(
        {
            "id": "invalid_domain_key",
            "file": "messy_orders.csv",
            "options": {"key_columns": ["customer_id"]},
            "expected_error": "invalid_data",
        }
    )
    for case in cases:
        case.update(fingerprint(ROOT / case["file"]))
        case.setdefault("origin", "synthetic")
        case.setdefault("options", {})
        if case.get("expected_error"):
            continue
        with (ROOT / case["file"]).open(encoding="utf-8-sig", newline="") as source:
            records = list(csv.reader(source, delimiter=case["options"].get("delimiter", ",")))
        header, records = records[0], records[1:]
        case["expected"] = {
            "columns": header,
            "rows": len(records),
            "blank_cells": sum(x == "" for row in records for x in row),
            "duplicate_rows": len(records) - len({tuple(row) for row in records}),
        }
    manifest = {
        "format_version": 1,
        "cases": cases,
        "public_sources": [
            {
                "file": "penguins.csv",
                "url": "https://raw.githubusercontent.com/allisonhorst/palmerpenguins/v0.1.0/inst/extdata/penguins.csv",
                "landing_page": "https://github.com/allisonhorst/palmerpenguins",
                "license": "CC0-1.0",
                "citation": "Horst AM, Hill AP, Gorman KB (2020). palmerpenguins. doi:10.5281/zenodo.3960218.",
            },
            {
                "file": "bike_daily.csv",
                "url": "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip",
                "member": "day.csv",
                "landing_page": "https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset",
                "license": "CC-BY-4.0",
                "citation": "Fanaee-T, H. (2013). Bike Sharing [Dataset]. UCI Machine Learning Repository. doi:10.24432/C5W894.",
            },
        ],
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Generated {len(cases)} shared cases ({sum(not x.get('expected_error') for x in cases)} valid); public snapshot bytes retained."
    )


if __name__ == "__main__":
    main()
