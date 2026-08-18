#!/usr/bin/env python3
"""Validate the committed dataset copies and their core research invariants."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CSV_PATH = DATA / "upgrade_transactions_100.csv"
JSON_PATH = DATA / "upgrade_transactions_100.json"
METADATA_PATH = DATA / "metadata.json"
XLSX_PATH = DATA / "upgrade_transactions_100.xlsx"

ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
HASH = re.compile(r"^0x[0-9a-f]{64}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
SOURCE_COMMIT = "9b2bf71d1929a8bc27c88b52fe9224c24325cd68"
SELECTORS = {
    "upgradeTo": "0x3659cfe6",
    "upgradeToAndCall": "0x4f1ef286",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def csv_string(value: object) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


def validate_xlsx_text_cells(first_row: dict[str, object]) -> None:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(XLSX_PATH) as archive:
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    cells = {
        cell.attrib["r"]: cell
        for cell in sheet.findall(".//x:c", namespace)
        if cell.attrib.get("r") in {"D2", "F2", "M2"}
    }
    expected = {
        "D2": first_row["upgrade_entrypoint_address"],
        "F2": first_row["upgrade_transaction_hash"],
        "M2": first_row["new_implementation_address"],
    }
    for reference, value in expected.items():
        cell = cells.get(reference)
        require(cell is not None, f"XLSX cell {reference} is missing")
        require(cell.attrib.get("t") == "str", f"XLSX cell {reference} is not text")
        stored = cell.findtext("x:v", namespaces=namespace)
        require(stored == value, f"XLSX cell {reference} differs from JSON")


def main() -> int:
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    with JSON_PATH.open(encoding="utf-8") as handle:
        json_rows = json.load(handle)
    with METADATA_PATH.open(encoding="utf-8") as handle:
        metadata = json.load(handle)

    require(len(csv_rows) == 100, "CSV must contain exactly 100 rows")
    require(len(json_rows) == 100, "JSON must contain exactly 100 rows")
    require(metadata["row_count"] == 100, "Metadata row_count must be 100")
    require(metadata["chain_id"] == 1, "Metadata chain_id must be 1")
    require(metadata["unique_proxy_count"] == 100, "Expected 100 unique proxies")
    require(metadata["unique_transaction_count"] == 100, "Expected 100 unique transactions")

    proxies: set[str] = set()
    transactions: set[str] = set()
    implementations: set[str] = set()
    for index, (csv_row, row) in enumerate(zip(csv_rows, json_rows), start=1):
        require(set(csv_row) == set(row), f"Row {index}: CSV/JSON fields differ")
        for field, value in row.items():
            require(csv_row[field] == csv_string(value), f"Row {index}: {field} differs")

        require(row["dataset_id"] == f"SUT-{index:04d}", f"Row {index}: bad dataset_id")
        require(row["chain_id"] == 1, f"Row {index}: bad chain_id")
        require(row["network"] == "ethereum-mainnet", f"Row {index}: bad network")
        for field in (
            "upgrade_entrypoint_address",
            "proxy_address",
            "transaction_sender",
            "new_implementation_address",
        ):
            require(bool(ADDRESS.fullmatch(row[field])), f"Row {index}: bad {field}")
        for field in ("upgrade_transaction_hash", "upgrade_block_hash"):
            require(bool(HASH.fullmatch(row[field])), f"Row {index}: bad {field}")
        require(row["upgrade_function"] in SELECTORS, f"Row {index}: unsupported function")
        require(
            row["calldata_selector"] == SELECTORS[row["upgrade_function"]],
            f"Row {index}: selector/function mismatch",
        )
        require(row["receipt_status"] == "success", f"Row {index}: failed receipt")
        require(row["upgraded_event_matches"] is True, f"Row {index}: event mismatch")
        require(
            row["source_timestamp_matches_block"] is True,
            f"Row {index}: timestamp mismatch",
        )
        require(
            row["block_timestamp_utc"] == row["source_timestamp_utc"],
            f"Row {index}: unequal timestamps",
        )
        require(row["upgrade_block_number"] > 0, f"Row {index}: invalid block")
        require(
            row["new_implementation_code_size_bytes_latest"] > 0,
            f"Row {index}: implementation has no bytecode",
        )
        require(row["source_commit"] == SOURCE_COMMIT, f"Row {index}: source drift")
        require(
            bool(HEX_64.fullmatch(row["selection_rank_sha256"])),
            f"Row {index}: invalid selection rank",
        )
        proxies.add(row["proxy_address"])
        transactions.add(row["upgrade_transaction_hash"])
        implementations.add(row["new_implementation_address"])

    require(len(proxies) == 100, "Proxy addresses are not unique")
    require(len(transactions) == 100, "Transaction hashes are not unique")
    require(
        json_rows == sorted(
            json_rows,
            key=lambda row: (row["upgrade_block_number"], row["upgrade_transaction_hash"]),
        ),
        "Rows are not in canonical block/transaction order",
    )
    validate_xlsx_text_cells(json_rows[0])

    print(
        "PASS: 100 rows; 100 unique proxies; "
        f"{len(implementations)} unique new implementations; CSV/JSON/XLSX consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
