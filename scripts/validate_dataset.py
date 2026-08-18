#!/usr/bin/env python3
"""Validate the committed dataset copies and their core research invariants."""

from __future__ import annotations

import csv
import hashlib
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
SCHEMA_PATH = DATA / "schema.json"
XLSX_PATH = DATA / "upgrade_transactions_100.xlsx"
CONTRACTS = ROOT / "contracts"
CONTRACT_INDEX_JSON = CONTRACTS / "index.json"
CONTRACT_INDEX_CSV = CONTRACTS / "index.csv"

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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_checksum_manifest(path: Path, base: Path) -> None:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        digest, separator, relative = line.partition("  ")
        require(bool(separator), f"{path}: malformed line {line_number}")
        require(bool(HEX_64.fullmatch(digest)), f"{path}: bad digest on line {line_number}")
        target = base / relative
        require(target.is_file(), f"{path}: missing {relative}")
        require(file_sha256(target) == digest, f"{path}: checksum mismatch for {relative}")


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
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    with CONTRACT_INDEX_JSON.open(encoding="utf-8") as handle:
        contract_rows = json.load(handle)
    with CONTRACT_INDEX_CSV.open(newline="", encoding="utf-8") as handle:
        contract_csv_rows = list(csv.DictReader(handle))

    require(len(csv_rows) == 100, "CSV must contain exactly 100 rows")
    require(len(json_rows) == 100, "JSON must contain exactly 100 rows")
    expected_fields = set(schema["items"]["required"])
    require(all(set(row) == expected_fields for row in json_rows), "JSON rows differ from schema fields")
    require(metadata["row_count"] == 100, "Metadata row_count must be 100")
    require(metadata["chain_id"] == 1, "Metadata chain_id must be 1")
    require(metadata["unique_proxy_count"] == 100, "Expected 100 unique proxies")
    require(metadata["unique_transaction_count"] == 100, "Expected 100 unique transactions")
    require(metadata["unique_new_implementation_count"] == 85, "Expected 85 implementations")
    artifacts_metadata = metadata["contract_artifacts"]
    require(artifacts_metadata["runtime_bytecode_available_count"] == 85, "Expected 85 bytecodes")
    require(artifacts_metadata["source_available_count"] == 48, "Expected 48 source sets")
    require(artifacts_metadata["source_unavailable_count"] == 37, "Expected 37 unavailable sources")

    require(len(contract_rows) == 85, "Contract index must contain 85 implementations")
    require(len(contract_csv_rows) == 85, "Contract CSV index must contain 85 implementations")
    contract_by_address: dict[str, dict[str, object]] = {}
    for index, (csv_row, artifact) in enumerate(zip(contract_csv_rows, contract_rows), start=1):
        require(set(csv_row) == set(artifact), f"Contract row {index}: CSV/JSON fields differ")
        for field, value in artifact.items():
            require(csv_row[field] == csv_string(value), f"Contract row {index}: {field} differs")
        address = artifact["implementation_address"]
        require(bool(ADDRESS.fullmatch(address)), f"Contract row {index}: invalid address")
        require(address not in contract_by_address, f"Contract row {index}: duplicate address")
        contract_by_address[address] = artifact

        bytecode_path = ROOT / artifact["runtime_bytecode_path"]
        require(bytecode_path.is_file(), f"Contract row {index}: missing runtime bytecode")
        require(
            file_sha256(bytecode_path) == artifact["runtime_bytecode_sha256"],
            f"Contract row {index}: bytecode checksum mismatch",
        )
        bytecode = bytecode_path.read_text(encoding="ascii").strip()
        require(bytecode.startswith("0x") and len(bytecode) > 2, f"Contract row {index}: empty bytecode")
        require(
            (len(bytecode) - 2) // 2 == artifact["runtime_bytecode_size_bytes"],
            f"Contract row {index}: bytecode size mismatch",
        )

        verification_path = ROOT / artifact["verification_manifest_path"]
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        require(verification["implementation_address"] == address, f"Contract row {index}: bad manifest")
        require(
            len(verification["source_files"]) == artifact["source_file_count"],
            f"Contract row {index}: source count mismatch",
        )
        if artifact["source_available"]:
            require(artifact["source_provider"] in {"sourcify", "blockscout"}, f"Contract row {index}: bad provider")
            require(artifact["source_file_count"] > 0, f"Contract row {index}: source missing")
        else:
            require(artifact["source_provider"] == "none", f"Contract row {index}: unavailable provider mismatch")
            require(artifact["source_match"] == "unavailable", f"Contract row {index}: unavailable match mismatch")
            require(artifact["source_file_count"] == 0, f"Contract row {index}: unexpected source")
        for source in verification["source_files"]:
            source_path = ROOT / source["stored_path"]
            require(source_path.is_file(), f"Contract row {index}: source file missing")
            require(file_sha256(source_path) == source["sha256"], f"Contract row {index}: source checksum mismatch")

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
        artifact = contract_by_address[row["new_implementation_address"]]
        require(
            row["new_implementation_artifact_dir"] == artifact["artifact_dir"],
            f"Row {index}: artifact directory mismatch",
        )
        require(
            row["new_implementation_runtime_bytecode_path"] == artifact["runtime_bytecode_path"],
            f"Row {index}: bytecode path mismatch",
        )
        require(
            row["new_implementation_runtime_bytecode_sha256"] == artifact["runtime_bytecode_sha256"],
            f"Row {index}: bytecode checksum link mismatch",
        )
        require(
            row["new_implementation_runtime_bytecode_size_bytes"] == artifact["runtime_bytecode_size_bytes"],
            f"Row {index}: bytecode size link mismatch",
        )
        require(
            row["new_implementation_source_available"] is artifact["source_available"],
            f"Row {index}: source availability mismatch",
        )
        require(
            row["new_implementation_source_provider"] == artifact["source_provider"],
            f"Row {index}: source provider mismatch",
        )

    require(len(proxies) == 100, "Proxy addresses are not unique")
    require(len(transactions) == 100, "Transaction hashes are not unique")
    require(len(implementations) == 85, "Expected 85 unique implementations")
    require(
        json_rows == sorted(
            json_rows,
            key=lambda row: (row["upgrade_block_number"], row["upgrade_transaction_hash"]),
        ),
        "Rows are not in canonical block/transaction order",
    )
    validate_xlsx_text_cells(json_rows[0])
    validate_checksum_manifest(CONTRACTS / "CHECKSUMS.sha256", CONTRACTS)
    validate_checksum_manifest(ROOT / "CHECKSUMS.sha256", ROOT)

    print(
        "PASS: 100 rows; 100 unique proxies; "
        f"{len(implementations)} unique new implementations; 85 bytecodes; "
        "48 verified source sets; CSV/JSON/XLSX consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
