# Solidity Upgrade Transactions 100

A research dataset of **100 Ethereum mainnet upgrade transactions mapped to their new implementation addresses**.

## Dataset files

| File | Use |
|---|---|
| [`data/upgrade_transactions_100.csv`](data/upgrade_transactions_100.csv) | Machine-readable flat table |
| [`data/upgrade_transactions_100.json`](data/upgrade_transactions_100.json) | Typed JSON records |
| [`data/upgrade_transactions_100.xlsx`](data/upgrade_transactions_100.xlsx) | Filterable spreadsheet with a README sheet |
| [`data/metadata.json`](data/metadata.json) | Selection, source, validation, and limitation metadata |
| [`data/schema.json`](data/schema.json) | JSON Schema for the JSON release |
| [`CHECKSUMS.sha256`](CHECKSUMS.sha256) | SHA-256 integrity checks for release files |

The sample contains 87 `upgradeTo(address)` and 13 `upgradeToAndCall(address,bytes)` transactions, covering 100 distinct event-emitting proxies and 85 distinct new implementation addresses. Its block timestamps range from 2018-10-25 to 2023-06-05 UTC.

## What each row confirms

Every included row passed all of these checks against Ethereum mainnet:

1. Transaction hash, sender, target, function selector, and implementation argument match the source candidate.
2. The transaction receipt has successful status.
3. The receipt contains an `Upgraded(address)` event whose implementation equals the calldata argument.
4. The source timestamp equals the on-chain block timestamp.
5. The new implementation address has nonempty bytecode at the latest state used during validation.

The canonical mapping is:

```text
upgrade_transaction_hash -> new_implementation_address
```

`proxy_address` is the address that emitted the matching event. `upgrade_entrypoint_address` is the transaction target. They are retained separately even though they are equal in this 100-row sample.

## Selection protocol

- Candidate source: USCDetector's published grouped upgrade-transaction artifact.
- Source is pinned to commit `9b2bf71d1929a8bc27c88b52fe9224c24325cd68`.
- Eligible calls are limited to standard `upgradeTo` and `upgradeToAndCall` entry points.
- Candidates are ranked by SHA-256 using seed `fse2027-upgrade-dataset-v1`.
- The first validated transition for each event-emitting proxy is selected until 100 rows are obtained.
- Final rows are ordered by block number and transaction hash.

See [`PROVENANCE.md`](PROVENANCE.md) for the exact source and trust boundary.

## Scope boundary

This is suitable for experiments that need known upgrade transaction → new implementation mappings.

It is **not yet** a complete incremental-verification benchmark. In particular, it does not provide:

- a historically pinned old implementation for every row;
- verified Solidity source for both versions;
- formal properties, proof obligations, or expected verification outcomes;
- Beacon, Diamond, metamorphic, or nonstandard upgrade mechanisms.

For an old/new verification benchmark, add archive-state resolution at `blockNumber - 1` and `blockNumber`, pin source/compiler metadata for both implementations, and attach properties with checker-verifiable expected results.

## Reproduce and validate

Requirements: Python 3 and an Ethereum mainnet JSON-RPC endpoint. The builder defaults to a public endpoint, so reproducibility is subject to its availability and rate limits.

```bash
python3 scripts/build_dataset.py
python3 scripts/validate_dataset.py
```

The selection is deterministic, but `validated_at_utc` and the latest-state bytecode-size field can change when regenerated later.

