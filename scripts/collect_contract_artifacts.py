#!/usr/bin/env python3
"""Collect and link code artifacts for the dataset's new implementations.

For every distinct new implementation, this script records latest-state runtime
bytecode from Ethereum mainnet. It also preserves verified Solidity source and
build metadata from Sourcify, falling back to Blockscout when needed. Missing
human-readable source is explicit rather than silently treated as verified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "upgrade_transactions_100.json"
CSV_PATH = ROOT / "data" / "upgrade_transactions_100.csv"
METADATA_PATH = ROOT / "data" / "metadata.json"
CONTRACTS_DIR = ROOT / "contracts"

DEFAULT_RPC_URL = "https://ethereum.publicnode.com"
SOURCIFY_BASE = "https://sourcify.dev/server/v2/contract/1"
BLOCKSCOUT_BASE = "https://eth.blockscout.com/api/v2/smart-contracts"
USER_AGENT = "solidity-upgrade-transitions-dataset/1.1"

LINK_FIELDS = [
    "new_implementation_artifact_dir",
    "new_implementation_runtime_bytecode_path",
    "new_implementation_runtime_bytecode_sha256",
    "new_implementation_runtime_bytecode_size_bytes",
    "new_implementation_source_available",
    "new_implementation_source_provider",
    "new_implementation_source_match",
    "new_implementation_source_file_count",
    "new_implementation_contract_name",
    "new_implementation_compiler_version",
]

BASE_FIELDS = [
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

INDEX_FIELDS = [
    "implementation_address",
    "mapping_count",
    "artifact_dir",
    "runtime_bytecode_path",
    "runtime_bytecode_sha256",
    "runtime_bytecode_size_bytes",
    "source_available",
    "source_provider",
    "source_match",
    "source_file_count",
    "contract_name",
    "compiler",
    "compiler_version",
    "abi_path",
    "metadata_path",
    "standard_json_input_path",
    "storage_layout_path",
    "verification_manifest_path",
    "verification_url",
    "collected_at_utc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default=DEFAULT_RPC_URL)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def write_json(path: Path, value: Any) -> None:
    write_bytes(path, json_bytes(value))


def http_json(url: str) -> tuple[int, Any | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = None
        return error.code, payload


def blockscout_json(url: str) -> tuple[int, Any | None]:
    """Use curl because Blockscout's edge occasionally rejects urllib."""
    result = subprocess.run(
        [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "90",
            "--user-agent",
            "Mozilla/5.0 (compatible; solidity-upgrade-transitions-dataset/1.1)",
            "--write-out",
            "\n%{http_code}",
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    body, separator, status_text = result.stdout.rpartition("\n")
    status = int(status_text) if separator and status_text.isdigit() else 0
    try:
        payload = json.loads(body) if body else None
    except ValueError:
        payload = None
    return status, payload


def rpc_batch(rpc_url: str, addresses: list[str]) -> dict[str, str]:
    payload = [
        {
            "jsonrpc": "2.0",
            "id": index,
            "method": "eth_getCode",
            "params": [address, "latest"],
        }
        for index, address in enumerate(addresses, start=1)
    ]
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(
                rpc_url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                decoded = json.loads(response.read())
            by_id = {item["id"]: item for item in decoded}
            result: dict[str, str] = {}
            for index, address in enumerate(addresses, start=1):
                item = by_id.get(index, {})
                if "error" in item:
                    raise RuntimeError(f"eth_getCode failed for {address}: {item['error']}")
                code = item.get("result")
                if not isinstance(code, str) or not code.startswith("0x") or len(code) <= 2:
                    raise RuntimeError(f"empty runtime bytecode for {address}")
                result[address] = code.lower()
            return result
        except (OSError, RuntimeError, ValueError, urllib.error.URLError) as error:
            last_error = error
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"JSON-RPC bytecode collection failed: {last_error}")


def safe_source_path(original: str, fallback: str) -> Path:
    normalized = str(original or fallback).replace("\\", "/").lstrip("/")
    parts = []
    for part in PurePosixPath(normalized).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            parts.append("__parent__")
        else:
            parts.append(part.replace(":", "_"))
    return Path(*parts) if parts else Path(fallback)


def collect_source(address: str) -> dict[str, Any]:
    sourcify_url = f"{SOURCIFY_BASE}/{address}?fields=all"
    sourcify_status, sourcify = http_json(sourcify_url)
    if sourcify_status == 200 and isinstance(sourcify, dict):
        sources = sourcify.get("sources")
        if isinstance(sources, dict) and any(
            isinstance(value, dict) and isinstance(value.get("content"), str)
            for value in sources.values()
        ):
            return {
                "provider": "sourcify",
                "match": sourcify.get("match") or sourcify.get("runtimeMatch") or "match",
                "url": sourcify_url,
                "payload": sourcify,
                "lookups": {
                    "sourcify": {"status": sourcify_status, "url": sourcify_url},
                    "blockscout": {"status": "not_needed", "url": None},
                },
            }

    blockscout_url = f"{BLOCKSCOUT_BASE}/{address}"
    blockscout_status, blockscout = blockscout_json(blockscout_url)
    if (
        blockscout_status == 200
        and isinstance(blockscout, dict)
        and isinstance(blockscout.get("source_code"), str)
        and blockscout["source_code"].strip()
    ):
        match = "full_match" if blockscout.get("is_fully_verified") else "partial_match"
        return {
            "provider": "blockscout",
            "match": match,
            "url": blockscout_url,
            "payload": blockscout,
            "lookups": {
                "sourcify": {"status": sourcify_status, "url": sourcify_url},
                "blockscout": {"status": blockscout_status, "url": blockscout_url},
            },
        }

    return {
        "provider": "none",
        "match": "unavailable",
        "url": "",
        "payload": None,
        "lookups": {
            "sourcify": {"status": sourcify_status, "url": sourcify_url},
            "blockscout": {"status": blockscout_status, "url": blockscout_url},
        },
    }


def relative(path: Path | None) -> str:
    return path.relative_to(ROOT).as_posix() if path else ""


def preserve_sources(
    address: str,
    result: dict[str, Any],
    runtime_code: str,
    mapping_count: int,
    collected_at: str,
) -> dict[str, Any]:
    artifact_dir = CONTRACTS_DIR / address
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    bytecode_path = artifact_dir / "runtime-bytecode.hex"
    bytecode_bytes = (runtime_code + "\n").encode("ascii")
    write_bytes(bytecode_path, bytecode_bytes)
    byte_size = (len(runtime_code) - 2) // 2

    provider = result["provider"]
    payload = result["payload"]
    source_manifest: list[dict[str, str]] = []
    abi_path: Path | None = None
    metadata_path: Path | None = None
    standard_input_path: Path | None = None
    storage_layout_path: Path | None = None
    compiler_path: Path | None = None
    contract_name = ""
    compiler = ""
    compiler_version = ""

    if provider == "sourcify":
        compilation = payload.get("compilation") if isinstance(payload, dict) else {}
        compilation = compilation if isinstance(compilation, dict) else {}
        contract_name = str(compilation.get("name") or "")
        compiler = str(compilation.get("compiler") or "")
        compiler_version = str(compilation.get("compilerVersion") or "")
        compiler_path = artifact_dir / "compiler.json"
        write_json(compiler_path, compilation)

        for index, (original, value) in enumerate(sorted(payload.get("sources", {}).items())):
            if not isinstance(value, dict) or not isinstance(value.get("content"), str):
                continue
            stored = artifact_dir / "sources" / safe_source_path(original, f"source-{index}.sol")
            content = value["content"].encode("utf-8")
            write_bytes(stored, content)
            source_manifest.append(
                {
                    "original_path": original,
                    "stored_path": relative(stored),
                    "sha256": sha256_bytes(content),
                }
            )

        if isinstance(payload.get("abi"), list):
            abi_path = artifact_dir / "abi.json"
            write_json(abi_path, payload["abi"])
        if isinstance(payload.get("metadata"), dict):
            metadata_path = artifact_dir / "metadata.json"
            write_json(metadata_path, payload["metadata"])
        if isinstance(payload.get("stdJsonInput"), dict):
            standard_input_path = artifact_dir / "standard-json-input.json"
            write_json(standard_input_path, payload["stdJsonInput"])
        if isinstance(payload.get("storageLayout"), dict):
            storage_layout_path = artifact_dir / "storage-layout.json"
            write_json(storage_layout_path, payload["storageLayout"])

    elif provider == "blockscout":
        contract_name = str(payload.get("name") or "")
        compiler = str(payload.get("language") or "Solidity")
        compiler_version = str(payload.get("compiler_version") or "")
        primary_original = str(payload.get("file_path") or f"{contract_name or 'Contract'}.sol")
        source_items = [(primary_original, payload["source_code"])]
        for index, item in enumerate(payload.get("additional_sources") or []):
            if isinstance(item, dict) and isinstance(item.get("source_code"), str):
                source_items.append(
                    (str(item.get("file_path") or f"additional-{index}.sol"), item["source_code"])
                )
        seen_stored: set[str] = set()
        for index, (original, source) in enumerate(source_items):
            safe = safe_source_path(original, f"source-{index}.sol")
            candidate = safe
            suffix = 1
            while candidate.as_posix() in seen_stored:
                candidate = safe.with_name(f"{safe.stem}-{suffix}{safe.suffix}")
                suffix += 1
            seen_stored.add(candidate.as_posix())
            stored = artifact_dir / "sources" / candidate
            content = source.encode("utf-8")
            write_bytes(stored, content)
            source_manifest.append(
                {
                    "original_path": original,
                    "stored_path": relative(stored),
                    "sha256": sha256_bytes(content),
                }
            )
        if isinstance(payload.get("abi"), list):
            abi_path = artifact_dir / "abi.json"
            write_json(abi_path, payload["abi"])
        compiler_path = artifact_dir / "compiler.json"
        write_json(
            compiler_path,
            {
                "language": payload.get("language"),
                "compiler": "solc",
                "compilerVersion": payload.get("compiler_version"),
                "compilerSettings": payload.get("compiler_settings"),
                "evmVersion": payload.get("evm_version"),
                "optimizationEnabled": payload.get("optimization_enabled"),
                "optimizationRuns": payload.get("optimization_runs"),
                "name": payload.get("name"),
                "filePath": payload.get("file_path"),
            },
        )

    verification_path = artifact_dir / "verification.json"
    verification = {
        "implementation_address": address,
        "chain_id": 1,
        "source_available": bool(source_manifest),
        "source_provider": provider,
        "source_match": result["match"],
        "verification_url": result["url"],
        "provider_lookups": result["lookups"],
        "source_files": source_manifest,
        "runtime_bytecode": {
            "path": relative(bytecode_path),
            "sha256": sha256_bytes(bytecode_bytes),
            "size_bytes": byte_size,
            "state": "latest",
        },
        "collected_at_utc": collected_at,
    }
    if provider == "sourcify" and isinstance(payload, dict):
        verification.update(
            {
                "sourcify_match_id": payload.get("matchId"),
                "sourcify_creation_match": payload.get("creationMatch"),
                "sourcify_runtime_match": payload.get("runtimeMatch"),
                "source_verified_at": payload.get("verifiedAt"),
                "deployment": payload.get("deployment"),
            }
        )
    elif provider == "blockscout" and isinstance(payload, dict):
        verification.update(
            {
                "blockscout_is_fully_verified": payload.get("is_fully_verified"),
                "blockscout_is_partially_verified": payload.get("is_partially_verified"),
                "source_verified_at": payload.get("verified_at"),
            }
        )
    write_json(verification_path, verification)

    return {
        "implementation_address": address,
        "mapping_count": mapping_count,
        "artifact_dir": relative(artifact_dir),
        "runtime_bytecode_path": relative(bytecode_path),
        "runtime_bytecode_sha256": sha256_bytes(bytecode_bytes),
        "runtime_bytecode_size_bytes": byte_size,
        "source_available": bool(source_manifest),
        "source_provider": provider,
        "source_match": result["match"],
        "source_file_count": len(source_manifest),
        "contract_name": contract_name,
        "compiler": compiler,
        "compiler_version": compiler_version,
        "abi_path": relative(abi_path),
        "metadata_path": relative(metadata_path),
        "standard_json_input_path": relative(standard_input_path),
        "storage_layout_path": relative(storage_layout_path),
        "verification_manifest_path": relative(verification_path),
        "verification_url": result["url"],
        "collected_at_utc": collected_at,
    }


def write_index(index_rows: list[dict[str, Any]]) -> None:
    write_json(CONTRACTS_DIR / "index.json", index_rows)
    with (CONTRACTS_DIR / "index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(index_rows)

    artifact_files = sorted(
        path for path in CONTRACTS_DIR.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    )
    lines = [
        f"{sha256_bytes(path.read_bytes())}  {path.relative_to(CONTRACTS_DIR).as_posix()}"
        for path in artifact_files
    ]
    (CONTRACTS_DIR / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def link_mapping_rows(rows: list[dict[str, Any]], index_rows: list[dict[str, Any]]) -> None:
    by_address = {row["implementation_address"]: row for row in index_rows}
    for row in rows:
        artifact = by_address[row["new_implementation_address"]]
        values = {
            "new_implementation_artifact_dir": artifact["artifact_dir"],
            "new_implementation_runtime_bytecode_path": artifact["runtime_bytecode_path"],
            "new_implementation_runtime_bytecode_sha256": artifact["runtime_bytecode_sha256"],
            "new_implementation_runtime_bytecode_size_bytes": artifact["runtime_bytecode_size_bytes"],
            "new_implementation_source_available": artifact["source_available"],
            "new_implementation_source_provider": artifact["source_provider"],
            "new_implementation_source_match": artifact["source_match"],
            "new_implementation_source_file_count": artifact["source_file_count"],
            "new_implementation_contract_name": artifact["contract_name"],
            "new_implementation_compiler_version": artifact["compiler_version"],
        }
        row.update(values)

    fields = BASE_FIELDS + LINK_FIELDS
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_json(DATA_PATH, [{field: row[field] for field in fields} for row in rows])


def update_metadata(index_rows: list[dict[str, Any]], rpc_url: str, collected_at: str) -> None:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    providers = Counter(row["source_provider"] for row in index_rows)
    matches = Counter(row["source_match"] for row in index_rows)
    source_count = sum(bool(row["source_available"]) for row in index_rows)
    metadata["dataset_version"] = "1.1.0"
    metadata["unique_new_implementation_count"] = len(index_rows)
    metadata["contract_artifacts"] = {
        "collected_at_utc": collected_at,
        "unique_implementation_count": len(index_rows),
        "runtime_bytecode_available_count": len(index_rows),
        "source_available_count": source_count,
        "source_unavailable_count": len(index_rows) - source_count,
        "source_provider_counts": dict(sorted(providers.items())),
        "source_match_counts": dict(sorted(matches.items())),
        "runtime_bytecode_state": "latest",
        "rpc_host": urllib.parse.urlparse(rpc_url).netloc,
        "source_services": {
            "sourcify": SOURCIFY_BASE,
            "blockscout": BLOCKSCOUT_BASE,
        },
    }
    metadata["scope_limitations"] = [
        "Only direct upgradeTo and upgradeToAndCall transactions are included.",
        "This maps upgrade transactions to new implementations; it does not claim a fully pinned old/new snapshot pair.",
        "Beacon, Diamond, metamorphic, and nonstandard upgrade functions are excluded.",
        "Runtime bytecode is collected at latest state because the public validation endpoint does not provide archive state.",
        "Verified human-readable source is preserved when available and explicitly marked unavailable otherwise.",
        "The dataset does not contain formal properties or expected verification outcomes.",
    ]
    write_json(METADATA_PATH, metadata)


def main() -> int:
    args = parse_args()
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    rows = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    mapping_counts = Counter(row["new_implementation_address"] for row in rows)
    addresses = sorted(mapping_counts)
    runtime_codes = rpc_batch(args.rpc_url, addresses)

    source_results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(collect_source, address): address for address in addresses}
        for completed, future in enumerate(as_completed(futures), start=1):
            address = futures[future]
            source_results[address] = future.result()
            print(f"source lookup {completed}/{len(addresses)}: {address}")

    collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    index_rows = [
        preserve_sources(
            address,
            source_results[address],
            runtime_codes[address],
            mapping_counts[address],
            collected_at,
        )
        for address in addresses
    ]
    write_index(index_rows)
    link_mapping_rows(rows, index_rows)
    update_metadata(index_rows, args.rpc_url, collected_at)

    source_count = sum(row["source_available"] for row in index_rows)
    providers = Counter(row["source_provider"] for row in index_rows)
    print(
        f"wrote {len(index_rows)} implementation artifacts: "
        f"bytecode={len(index_rows)}, source={source_count}, providers={dict(providers)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
