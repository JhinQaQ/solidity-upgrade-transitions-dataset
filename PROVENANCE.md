# Provenance and validation

## Candidate source

- Repository: <https://github.com/xiaofan88/USCDetector>
- Commit: `9b2bf71d1929a8bc27c88b52fe9224c24325cd68`
- Artifact: `upgrade_chains_data/proxy_upgrade_transactions_group_all_remove_repeat.json`
- Pinned URL: <https://raw.githubusercontent.com/xiaofan88/USCDetector/9b2bf71d1929a8bc27c88b52fe9224c24325cd68/upgrade_chains_data/proxy_upgrade_transactions_group_all_remove_repeat.json>
- Downloaded artifact SHA-256: `b6e05d3ecf12bc757f8f48b55f858afdd55d2639b1af6050b2342bb2baebbf22`

The source groups decoded upgrade transaction records by address. This repository does not redistribute the complete upstream artifact; it publishes only the selected mapping records and source indices needed for traceability.

## Deterministic sampling

The builder keeps source records whose decoded signature is exactly one of:

- `upgradeTo(address)` / selector `0x3659cfe6`
- `upgradeToAndCall(address,bytes)` / selector `0x4f1ef286`

It computes:

```text
SHA256(seed | source-address | transaction-hash | new-implementation)
```

with seed `fse2027-upgrade-dataset-v1`, sorts ascending by that digest, validates candidates in that order, and retains at most one row per event-emitting proxy. The 100 retained mappings are then sorted by `(upgrade_block_number, upgrade_transaction_hash)` and assigned stable `SUT-0001` through `SUT-0100` identifiers.

## On-chain checks

Validation requires chain ID 1 and checks the transaction, receipt, block, and current implementation bytecode. A row is emitted only when:

- transaction hash, target, sender, selector, and first address argument match the candidate;
- receipt status is successful;
- a receipt log has the `Upgraded(address)` topic and its indexed address equals the new implementation;
- the source timestamp equals the timestamp of the containing block; and
- `eth_getCode(newImplementation, "latest")` is nonempty.

The matching event emitter is recorded as `proxy_address`. The RPC hostname and validation timestamp are recorded in every row and in `data/metadata.json`.

## Trust boundary and limitations

Receipt and block checks independently confirm the published mapping, but the public endpoint used for this release did not provide archive-state access. Therefore:

- `new_implementation_code_size_bytes_latest` is a latest-state check, not historical code at the upgrade block;
- no old implementation address is asserted;
- no EIP-1967 storage transition is asserted;
- source code, compiler settings, proxy family, and formal properties are not verified here.

Treat these records as transaction → new-implementation mappings. A paper claiming historical old/new snapshot soundness should add archive-node validation and preserve the resulting state proofs or equivalent independently checkable evidence.
