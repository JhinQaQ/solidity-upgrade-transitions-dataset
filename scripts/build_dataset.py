#!/usr/bin/env python3
"""Build a deterministic, on-chain-validated Solidity proxy upgrade dataset.

The candidate pool comes from USCDetector's published upgrade-chain artifact.
Only upgrades using upgradeTo(address) or upgradeToAndCall(address,bytes) are
eligible. Every emitted row is checked against Ethereum mainnet transaction,
receipt, block, matching Upgraded(address) event, and current implementation
bytecode data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SOURCE_REPOSITORY = "xiaofan88/USCDetector"
SOURCE_COMMIT = "9b2bf71d1929a8bc27c88b52fe9224c24325cd68"
SOURCE_PATH = (
    "upgrade_chains_data/"
    "proxy_upgrade_transactions_group_all_remove_repeat.json"
)
SOURCE_URL = (
    f"https://raw.githubusercontent.com/{SOURCE_REPOSITORY}/"
    f"{SOURCE_COMMIT}/{SOURCE_PATH}"
)
DEFAULT_RPC_URL = "https://ethereum.publicnode.com"
DEFAULT_SEED = "fse2027-upgrade-dataset-v1"

UPGRADED_EVENT_TOPIC = (
    "0xbc7cd75a20ee27fd9adebab32041f755214dbc6bffa90cc0225b39da2e5c2d3b"
)
ELIGIBLE_FUNCTIONS = {
    "upgradeTo": {
        "selector": "0x3659cfe6",
        "types": ["address"],
    },
    "upgradeToAndCall": {
        "selector": "0x4f1ef286",
        "types": ["address", "bytes"],
    },
}

CSV_FIELDS = [
    "dataset_id",
    "chain_id",
    "network",
    "upgrade_entrypoint_address",
    "proxy_address",
    "upgrade_transaction_hash",
    "upgrade_block_number",
    "upgrade_block_hash",
    "block_timestamp_utc",
    "transaction_sender",
    "upgrade_function",
    "calldata_selector",
    "new_implementation_address",
    "new_implementation_code_size_bytes_latest",
    "receipt_status",
    "upgraded_event_log_index",
    "upgraded_event_matches",
    "source_timestamp_utc",
    "source_timestamp_matches_block",
    "source_dataset",
    "source_commit",
    "source_record_index",
    "selection_rank_sha256",
    "validation_rpc_host",
    "validated_at_utc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--batch-size",
        type=int,
        default=12,
        help="Candidates validated per JSON-RPC batch group.",
    )
    return parser.parse_args()


def http_json(url: str) -> tuple[Any, bytes]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "solidity-upgrade-transitions-dataset/1.0"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
    return json.loads(raw), raw


class RpcClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.next_id = 1

    def batch(self, calls: Iterable[tuple[str, list[Any]]]) -> list[Any]:
        payload = []
        order = []
        for method, params in calls:
            request_id = self.next_id
            self.next_id += 1
            order.append(request_id)
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": request_id,
                }
            )
        if not payload:
            return []

        body = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                request = urllib.request.Request(
                    self.url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "solidity-upgrade-transitions-dataset/1.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=90) as response:
                    decoded = json.loads(response.read())
                if isinstance(decoded, dict):
                    decoded = [decoded]
                by_id = {item.get("id"): item for item in decoded}
                results = []
                for request_id in order:
                    item = by_id.get(request_id, {})
                    if "error" in item:
                        raise RuntimeError(f"JSON-RPC error: {item['error']}")
                    results.append(item.get("result"))
                return results
            except (OSError, RuntimeError, ValueError, urllib.error.URLError) as error:
                last_error = error
                if attempt == 3:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"JSON-RPC batch failed after retries: {last_error}")

    def one(self, method: str, params: list[Any]) -> Any:
        return self.batch([(method, params)])[0]


def normalize_address(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        return None
    if int(raw, 16) == 0:
        return None
    return "0x" + raw


def normalize_hash(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        return None
    return "0x" + raw


def topic_address(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("0x"):
        return None
    raw = value[2:].lower().rjust(64, "0")
    return normalize_address(raw[-40:])


def calldata_address(calldata: str) -> str | None:
    if not isinstance(calldata, str) or len(calldata) < 10 + 64:
        return None
    return normalize_address(calldata[10 + 24 : 10 + 64])


def chunks(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def build_candidates(source: Any, seed: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    failures: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    seen_transactions: set[str] = set()
    if not isinstance(source, dict):
        raise ValueError("Expected source artifact to contain an object keyed by address")

    for proxy_raw, records in source.items():
        proxy = normalize_address(proxy_raw)
        if proxy is None or not isinstance(records, list):
            failures["invalid_proxy_or_records"] += 1
            continue
        for source_index, record in enumerate(records):
            if not isinstance(record, list) or len(record) < 6:
                failures["malformed_source_record"] += 1
                continue
            tx_hash = normalize_hash(record[0])
            sender = normalize_address(record[1])
            source_timestamp = record[2]
            function_name = record[3]
            arg_types = record[4]
            arg_values = record[5]
            expected = ELIGIBLE_FUNCTIONS.get(function_name)
            if expected is None:
                failures["unsupported_upgrade_function"] += 1
                continue
            if not isinstance(arg_types, list) or arg_types != expected["types"]:
                failures["unexpected_argument_types"] += 1
                continue
            if not isinstance(arg_values, list) or not arg_values:
                failures["missing_argument_values"] += 1
                continue
            implementation = normalize_address(arg_values[0])
            if tx_hash is None or sender is None or implementation is None:
                failures["invalid_hash_sender_or_implementation"] += 1
                continue
            if tx_hash in seen_transactions:
                failures["duplicate_transaction"] += 1
                continue
            seen_transactions.add(tx_hash)
            rank = hashlib.sha256(
                f"{seed}|{proxy}|{tx_hash}|{implementation}".encode("utf-8")
            ).hexdigest()
            candidates.append(
                {
                    "upgrade_entrypoint_address": proxy,
                    "upgrade_transaction_hash": tx_hash,
                    "transaction_sender": sender,
                    "source_timestamp_utc": str(source_timestamp),
                    "upgrade_function": function_name,
                    "calldata_selector": expected["selector"],
                    "new_implementation_address": implementation,
                    "source_record_index": source_index,
                    "selection_rank_sha256": rank,
                }
            )
    candidates.sort(key=lambda item: item["selection_rank_sha256"])
    return candidates, failures


def validate_tx_and_receipt(
    candidate: dict[str, Any], tx: Any, receipt: Any
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(tx, dict) or not isinstance(receipt, dict):
        return None, "transaction_or_receipt_not_found"
    if normalize_hash(tx.get("hash")) != candidate["upgrade_transaction_hash"]:
        return None, "transaction_hash_mismatch"
    if normalize_address(tx.get("to")) != candidate["upgrade_entrypoint_address"]:
        return None, "transaction_target_mismatch"
    if normalize_address(tx.get("from")) != candidate["transaction_sender"]:
        return None, "transaction_sender_mismatch"
    calldata = tx.get("input")
    if not isinstance(calldata, str):
        return None, "missing_calldata"
    if calldata[:10].lower() != candidate["calldata_selector"]:
        return None, "calldata_selector_mismatch"
    if calldata_address(calldata) != candidate["new_implementation_address"]:
        return None, "calldata_implementation_mismatch"
    if receipt.get("status") != "0x1":
        return None, "unsuccessful_receipt"
    block_hex = tx.get("blockNumber")
    if not isinstance(block_hex, str):
        return None, "missing_block_number"
    block_number = int(block_hex, 16)
    if block_number <= 0:
        return None, "invalid_block_number"

    matching_event = None
    for log in receipt.get("logs", []):
        topics = log.get("topics", []) if isinstance(log, dict) else []
        if (
            len(topics) >= 2
            and str(topics[0]).lower() == UPGRADED_EVENT_TOPIC
            and topic_address(topics[1]) == candidate["new_implementation_address"]
        ):
            matching_event = log
            break
    if matching_event is None:
        return None, "matching_upgraded_event_not_found"

    enriched = dict(candidate)
    enriched.update(
        {
            "upgrade_block_number": block_number,
            "upgrade_block_hex": block_hex.lower(),
            "upgrade_block_hash": str(tx.get("blockHash", "")).lower(),
            "receipt_status": "success",
            "proxy_address": normalize_address(matching_event["address"]),
            "upgraded_event_log_index": int(matching_event["logIndex"], 16),
            "upgraded_event_matches": True,
        }
    )
    return enriched, None


def validate_block_and_code(
    candidate: dict[str, Any], block: Any, implementation_code: Any
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(block, dict) or "timestamp" not in block:
        return None, "block_not_found"
    block_timestamp = datetime.fromtimestamp(
        int(block["timestamp"], 16), tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")
    if block_timestamp != candidate["source_timestamp_utc"]:
        return None, "source_timestamp_mismatch"
    implementation_size = code_size(implementation_code)
    if implementation_size == 0:
        return None, "new_implementation_code_missing_latest"

    enriched = dict(candidate)
    enriched.update(
        {
            "block_timestamp_utc": block_timestamp,
            "source_timestamp_matches_block": True,
            "new_implementation_code_size_bytes_latest": implementation_size,
        }
    )
    return enriched, None


def code_size(code: Any) -> int:
    if not isinstance(code, str) or not code.startswith("0x") or len(code) <= 2:
        return 0
    return (len(code) - 2) // 2


def validate_candidate_batch(
    rpc: RpcClient, batch: list[dict[str, Any]], failures: Counter[str]
) -> list[dict[str, Any]]:
    first_calls = []
    for candidate in batch:
        tx_hash = candidate["upgrade_transaction_hash"]
        first_calls.extend(
            [
                ("eth_getTransactionByHash", [tx_hash]),
                ("eth_getTransactionReceipt", [tx_hash]),
            ]
        )
    first_results = rpc.batch(first_calls)

    stage_one = []
    for index, candidate in enumerate(batch):
        enriched, failure = validate_tx_and_receipt(
            candidate, first_results[index * 2], first_results[index * 2 + 1]
        )
        if failure:
            failures[failure] += 1
        else:
            stage_one.append(enriched)

    second_calls = []
    for candidate in stage_one:
        after_hex = candidate["upgrade_block_hex"]
        second_calls.extend(
            [
                ("eth_getBlockByNumber", [after_hex, False]),
                (
                    "eth_getCode",
                    [candidate["new_implementation_address"], "latest"],
                ),
            ]
        )
    second_results = rpc.batch(second_calls)

    validated = []
    for index, candidate in enumerate(stage_one):
        enriched, failure = validate_block_and_code(
            candidate,
            second_results[index * 2],
            second_results[index * 2 + 1],
        )
        if failure:
            failures[failure] += 1
        else:
            validated.append(enriched)
    return validated


def write_outputs(
    output_dir: Path,
    rows: list[dict[str, Any]],
    source_sha256: str,
    source_url: str,
    rpc_url: str,
    seed: str,
    candidate_count: int,
    candidates_checked: int,
    failures: Counter[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    validated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rpc_host = urllib.parse.urlparse(rpc_url).netloc
    rows.sort(
        key=lambda row: (
            row["upgrade_block_number"],
            row["upgrade_transaction_hash"],
        )
    )
    for index, row in enumerate(rows, start=1):
        row["dataset_id"] = f"SUT-{index:04d}"
        row["chain_id"] = 1
        row["network"] = "ethereum-mainnet"
        row["source_dataset"] = "USCDetector"
        row["source_commit"] = SOURCE_COMMIT
        row["validation_rpc_host"] = rpc_host
        row["validated_at_utc"] = validated_at

    csv_path = output_dir / "upgrade_transactions_100.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_FIELDS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    json_path = output_dir / "upgrade_transactions_100.json"
    with json_path.open("w", encoding="utf-8") as handle:
        json_rows = [
            {field: row[field] for field in CSV_FIELDS}
            for row in rows
        ]
        json.dump(json_rows, handle, indent=2, sort_keys=True)
        handle.write("\n")

    metadata = {
        "dataset_name": "Solidity Upgrade Transactions 100",
        "dataset_version": "1.0.0",
        "chain_id": 1,
        "network": "ethereum-mainnet",
        "row_count": len(rows),
        "unique_proxy_count": len({row["proxy_address"] for row in rows}),
        "unique_transaction_count": len(
            {row["upgrade_transaction_hash"] for row in rows}
        ),
        "selection": {
            "seed": seed,
            "method": "SHA-256 rank, first validated transition per proxy",
            "eligible_functions": sorted(ELIGIBLE_FUNCTIONS),
            "candidate_count": candidate_count,
            "candidates_checked": candidates_checked,
        },
        "validation": {
            "validated_at_utc": validated_at,
            "rpc_host": rpc_host,
            "required_chain_id": 1,
            "checks": [
                "transaction hash, sender, target, selector, and implementation argument",
                "successful transaction receipt",
                "matching Upgraded(address) event emitted by the proxy",
                "source timestamp equals the on-chain block timestamp",
                "new implementation bytecode currently exists",
            ],
            "failure_counts": dict(sorted(failures.items())),
        },
        "source": {
            "repository": SOURCE_REPOSITORY,
            "commit": SOURCE_COMMIT,
            "path": SOURCE_PATH,
            "url": source_url,
            "artifact_sha256": source_sha256,
        },
        "scope_limitations": [
            "Only direct upgradeTo and upgradeToAndCall transactions are included.",
            "This is an upgrade-transaction-to-new-implementation mapping dataset; it does not claim a fully pinned old/new snapshot pair.",
            "Beacon, Diamond, metamorphic, and nonstandard upgrade functions are excluded.",
            "The bytecode-presence check is at latest state because the public validation endpoint does not provide archive state.",
            "The dataset does not contain verified Solidity source code or formal properties.",
        ],
    }
    with (output_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    if args.count <= 0 or args.batch_size <= 0:
        raise ValueError("count and batch-size must be positive")

    source, source_raw = http_json(args.source_url)
    source_sha256 = hashlib.sha256(source_raw).hexdigest()
    candidates, failures = build_candidates(source, args.seed)
    rpc = RpcClient(args.rpc_url)
    chain_id = rpc.one("eth_chainId", [])
    if chain_id != "0x1":
        raise RuntimeError(f"Expected Ethereum mainnet chain ID 0x1, got {chain_id}")

    selected: list[dict[str, Any]] = []
    selected_proxies: set[str] = set()
    candidates_checked = 0
    for batch in chunks(candidates, args.batch_size):
        candidates_checked += len(batch)
        for row in validate_candidate_batch(rpc, batch, failures):
            proxy = row["proxy_address"]
            if proxy in selected_proxies:
                failures["duplicate_proxy_after_validation"] += 1
                continue
            selected.append(row)
            selected_proxies.add(proxy)
            if len(selected) >= args.count:
                break
        print(
            (
                f"validated {len(selected)}/{args.count}; checked {candidates_checked}; "
                f"top_failures={failures.most_common(4)}"
            ),
            file=sys.stderr,
        )
        if len(selected) >= args.count:
            break

    if len(selected) < args.count:
        raise RuntimeError(
            f"Only {len(selected)} validated transitions found; requested {args.count}"
        )
    selected = selected[: args.count]
    write_outputs(
        args.output_dir,
        selected,
        source_sha256,
        args.source_url,
        args.rpc_url,
        args.seed,
        len(candidates),
        candidates_checked,
        failures,
    )
    print(f"wrote {len(selected)} rows to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
