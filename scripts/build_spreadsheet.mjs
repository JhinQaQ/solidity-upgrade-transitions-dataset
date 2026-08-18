import fs from "node:fs/promises";

process.on("uncaughtException", (error) => {
  console.error(error?.message ?? String(error));
  process.exit(1);
});
process.on("unhandledRejection", (error) => {
  console.error(error?.message ?? String(error));
  process.exit(1);
});

const { SpreadsheetFile, Workbook } = await import("@oai/artifact-tool");

const csvPath = "data/upgrade_transactions_100.csv";
const jsonPath = "data/upgrade_transactions_100.json";
const contractIndexPath = "contracts/index.json";
const contractIndexCsvPath = "contracts/index.csv";
const outputPath = "data/upgrade_transactions_100.xlsx";
const previewDir = "spreadsheet-previews";

function columnName(index) {
  let value = index + 1;
  let name = "";
  while (value > 0) {
    value -= 1;
    name = String.fromCharCode(65 + (value % 26)) + name;
    value = Math.floor(value / 26);
  }
  return name;
}

function setColumnWidth(sheet, column, rowCount, width) {
  sheet.getRange(`${column}1:${column}${rowCount}`).format.columnWidth = width;
}

const csvText = await fs.readFile(csvPath, "utf8");
const jsonRows = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const contractRows = JSON.parse(await fs.readFile(contractIndexPath, "utf8"));
const contractCsvText = await fs.readFile(contractIndexCsvPath, "utf8");
console.log("phase: import mapping CSV");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Mappings" });
const mappings = workbook.worksheets.getItem("Mappings");
const readme = workbook.worksheets.add("README");
const contracts = workbook.worksheets.add("Contract Artifacts");

console.log("phase: normalize mapping types");
const mappingHeaders = csvText.slice(0, csvText.indexOf("\n")).replace(/\r$/, "").split(",");
const mappingLastColumn = columnName(mappingHeaders.length - 1);
const mappingLastRow = jsonRows.length + 1;
const dateFields = new Set([
  "block_timestamp_utc",
  "source_timestamp_utc",
  "validated_at_utc",
]);
const mappingValues = jsonRows.map((row) => mappingHeaders.map((field) => {
  const value = row[field];
  return dateFields.has(field) ? new Date(String(value)) : value;
}));
mappings.getRange(`A1:${mappingLastColumn}1`).values = [mappingHeaders];
mappings.getRange(`A2:${mappingLastColumn}${mappingLastRow}`).values = mappingValues;

const mappingColumn = Object.fromEntries(
  mappingHeaders.map((field, index) => [field, columnName(index)]),
);
for (const field of dateFields) {
  const column = mappingColumn[field];
  mappings.getRange(`${column}2:${column}${mappingLastRow}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
}

mappings.showGridLines = false;
mappings.freezePanes.freezeRows(1);
mappings.freezePanes.freezeColumns(3);
const mappingFullRange = mappings.getRange(`A1:${mappingLastColumn}${mappingLastRow}`);
mappingFullRange.format.font = { name: "Aptos", size: 10, color: "#172033" };
mappingFullRange.format.rowHeight = 18;
const mappingHeader = mappings.getRange(`A1:${mappingLastColumn}1`);
mappingHeader.format = {
  fill: "#164E63",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  wrapText: true,
  rowHeight: 50,
  verticalAlignment: "center",
};
const mappingTable = mappings.tables.add(
  `A1:${mappingLastColumn}${mappingLastRow}`,
  true,
  "UpgradeMappings",
);
mappingTable.style = "TableStyleMedium2";
mappingTable.showBandedRows = true;
mappingTable.showFilterButton = true;

const mappingWidths = {
  dataset_id: 13, chain_id: 8, network: 18,
  upgrade_entrypoint_address: 44, proxy_address: 44,
  upgrade_transaction_hash: 68, upgrade_block_number: 15,
  upgrade_block_hash: 68, block_timestamp_utc: 22,
  transaction_sender: 44, upgrade_function: 20, calldata_selector: 14,
  new_implementation_address: 44, new_implementation_code_size_bytes_latest: 20,
  receipt_status: 12, upgraded_event_log_index: 18,
  upgraded_event_matches: 14, source_timestamp_utc: 22,
  source_timestamp_matches_block: 18, source_dataset: 15,
  source_commit: 42, source_record_index: 16, selection_rank_sha256: 68,
  validation_rpc_host: 25, validated_at_utc: 22,
  new_implementation_artifact_dir: 55,
  new_implementation_runtime_bytecode_path: 65,
  new_implementation_runtime_bytecode_sha256: 68,
  new_implementation_runtime_bytecode_size_bytes: 20,
  new_implementation_source_available: 17,
  new_implementation_source_provider: 18,
  new_implementation_source_match: 18,
  new_implementation_source_file_count: 18,
  new_implementation_contract_name: 24,
  new_implementation_compiler_version: 28,
};
for (const [field, width] of Object.entries(mappingWidths)) {
  setColumnWidth(mappings, mappingColumn[field], mappingLastRow, width);
}
const mappingNumericFields = [
  "chain_id", "upgrade_block_number", "new_implementation_code_size_bytes_latest",
  "upgraded_event_log_index", "source_record_index",
  "new_implementation_runtime_bytecode_size_bytes",
  "new_implementation_source_file_count",
];
for (const field of mappingNumericFields) {
  const column = mappingColumn[field];
  mappings.getRange(`${column}2:${column}${mappingLastRow}`).format.numberFormat = "0";
}
for (const field of mappingHeaders) {
  if (!mappingNumericFields.includes(field) && !dateFields.has(field)
      && !field.endsWith("_available") && !field.endsWith("_matches")
      && field !== "upgraded_event_matches") {
    const column = mappingColumn[field];
    mappings.getRange(`${column}2:${column}${mappingLastRow}`).format.numberFormat = "@";
  }
}
for (const field of [
  "upgraded_event_matches",
  "source_timestamp_matches_block",
  "new_implementation_source_available",
]) {
  const column = mappingColumn[field];
  mappings.getRange(`${column}2:${column}${mappingLastRow}`).conditionalFormats.add("cellIs", {
    operator: "equal",
    formula: "TRUE",
    format: { fill: "#DCFCE7", font: { color: "#166534" } },
  });
}

console.log("phase: contract artifact sheet");
const contractHeaders = contractCsvText.slice(0, contractCsvText.indexOf("\n")).replace(/\r$/, "").split(",");
const contractLastColumn = columnName(contractHeaders.length - 1);
const contractLastRow = contractRows.length + 1;
contracts.getRange(`A1:${contractLastColumn}1`).values = [contractHeaders];
contracts.getRange(`A2:${contractLastColumn}${contractLastRow}`).values = contractRows.map(
  (row) => contractHeaders.map((field) => (
    field === "collected_at_utc" ? new Date(String(row[field])) : row[field]
  )),
);
const contractColumn = Object.fromEntries(
  contractHeaders.map((field, index) => [field, columnName(index)]),
);
contracts.showGridLines = false;
contracts.freezePanes.freezeRows(1);
contracts.freezePanes.freezeColumns(2);
const contractFullRange = contracts.getRange(`A1:${contractLastColumn}${contractLastRow}`);
contractFullRange.format.font = { name: "Aptos", size: 10, color: "#172033" };
contractFullRange.format.rowHeight = 18;
const contractHeader = contracts.getRange(`A1:${contractLastColumn}1`);
contractHeader.format = {
  fill: "#7C2D12",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  wrapText: true,
  rowHeight: 50,
  verticalAlignment: "center",
};
const contractTable = contracts.tables.add(
  `A1:${contractLastColumn}${contractLastRow}`,
  true,
  "ContractArtifacts",
);
contractTable.style = "TableStyleMedium9";
contractTable.showBandedRows = true;
contractTable.showFilterButton = true;

const contractWidths = {
  implementation_address: 44, mapping_count: 14, artifact_dir: 55,
  runtime_bytecode_path: 65, runtime_bytecode_sha256: 68,
  runtime_bytecode_size_bytes: 20, source_available: 17,
  source_provider: 18, source_match: 18, source_file_count: 18,
  contract_name: 24, compiler: 14, compiler_version: 28,
  abi_path: 60, metadata_path: 60, standard_json_input_path: 65,
  storage_layout_path: 60, verification_manifest_path: 65,
  verification_url: 75, collected_at_utc: 22,
};
for (const [field, width] of Object.entries(contractWidths)) {
  setColumnWidth(contracts, contractColumn[field], contractLastRow, width);
}
for (const field of ["mapping_count", "runtime_bytecode_size_bytes", "source_file_count"]) {
  const column = contractColumn[field];
  contracts.getRange(`${column}2:${column}${contractLastRow}`).format.numberFormat = "0";
}
for (const field of contractHeaders) {
  if (!["mapping_count", "runtime_bytecode_size_bytes", "source_file_count", "source_available", "collected_at_utc"].includes(field)) {
    const column = contractColumn[field];
    contracts.getRange(`${column}2:${column}${contractLastRow}`).format.numberFormat = "@";
  }
}
contracts.getRange(`${contractColumn.collected_at_utc}2:${contractColumn.collected_at_utc}${contractLastRow}`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
contracts.getRange(`${contractColumn.source_available}2:${contractColumn.source_available}${contractLastRow}`).conditionalFormats.add("cellIs", {
  operator: "equal",
  formula: "TRUE",
  format: { fill: "#DCFCE7", font: { color: "#166534" } },
});

console.log("phase: README sheet");
readme.showGridLines = false;
readme.freezePanes.freezeRows(3);
readme.getRange("A1:B1").values = [["Solidity Upgrade Transactions 100", null]];
readme.getRange("A2:B2").values = [[
  "Ethereum mainnet upgrade transaction → new implementation, with linked code artifacts",
  null,
]];
readme.getRange("A4:B14").values = [
  ["Quality check", "Value"],
  ["Mapping rows", null],
  ["Successful receipts", null],
  ["Rows with Upgraded(address) validation flag", null],
  ["Rows with source/block timestamp validation flag", null],
  ["Distinct new implementations", null],
  ["Runtime bytecode artifacts", null],
  ["Implementations with verified source", null],
  ["Implementations without verified source", null],
  ["Network", "Ethereum mainnet (chain ID 1)"],
  ["Important limit", "Artifacts cover new implementations. Old implementation resolution and historical state snapshots remain incomplete."],
];
readme.getRange("B5").formulas = [[`=COUNTA('Mappings'!$${mappingColumn.dataset_id}$2:$${mappingColumn.dataset_id}$${mappingLastRow})`]];
readme.getRange("B6").formulas = [[`=COUNTIF('Mappings'!$${mappingColumn.receipt_status}$2:$${mappingColumn.receipt_status}$${mappingLastRow},\"success\")`]];
readme.getRange("B7").formulas = [[`=COUNTA('Mappings'!$${mappingColumn.upgraded_event_matches}$2:$${mappingColumn.upgraded_event_matches}$${mappingLastRow})`]];
readme.getRange("B8").formulas = [[`=COUNTA('Mappings'!$${mappingColumn.source_timestamp_matches_block}$2:$${mappingColumn.source_timestamp_matches_block}$${mappingLastRow})`]];
readme.getRange("B9").formulas = [[`=COUNTA('Contract Artifacts'!$${contractColumn.implementation_address}$2:$${contractColumn.implementation_address}$${contractLastRow})`]];
readme.getRange("B10").formulas = [[`=COUNTA('Contract Artifacts'!$${contractColumn.runtime_bytecode_path}$2:$${contractColumn.runtime_bytecode_path}$${contractLastRow})`]];
readme.getRange("B11").formulas = [[`=COUNTIF('Contract Artifacts'!$${contractColumn.source_provider}$2:$${contractColumn.source_provider}$${contractLastRow},\"sourcify\")+COUNTIF('Contract Artifacts'!$${contractColumn.source_provider}$2:$${contractColumn.source_provider}$${contractLastRow},\"blockscout\")`]];
readme.getRange("B12").formulas = [[`=COUNTIF('Contract Artifacts'!$${contractColumn.source_provider}$2:$${contractColumn.source_provider}$${contractLastRow},\"none\")`]];
readme.getRange("A16:B20").values = [
  ["Provenance", "Value"],
  ["Candidate dataset", "USCDetector"],
  ["Pinned source commit", "9b2bf71d1929a8bc27c88b52fe9224c24325cd68"],
  ["Source-code services", "Sourcify v2, with Blockscout fallback"],
  ["Paper", "Xiaofan Li et al., Characterizing Ethereum Upgradable Smart Contracts and Their Security Implications, WWW 2024"],
];
readme.getRange("A1:B20").format.font = { name: "Aptos", size: 11, color: "#172033" };
readme.getRange("A1:B1").format = {
  fill: "#0F172A",
  font: { name: "Aptos Display", size: 16, bold: true, color: "#FFFFFF" },
  rowHeight: 48,
};
readme.getRange("A2:B2").format = {
  fill: "#E0F2FE",
  font: { name: "Aptos", size: 11, color: "#0C4A6E" },
  rowHeight: 32,
};
for (const rangeAddress of ["A4:B4", "A16:B16"]) {
  readme.getRange(rangeAddress).format = {
    fill: "#164E63",
    font: { name: "Aptos", size: 11, bold: true, color: "#FFFFFF" },
    borders: { preset: "outside", style: "thin", color: "#0E7490" },
  };
}
readme.getRange("A5:A14").format.font = { bold: true, color: "#334155" };
readme.getRange("A17:A20").format.font = { bold: true, color: "#334155" };
for (const rangeAddress of ["A4:B14", "A16:B20"]) {
  readme.getRange(rangeAddress).format.borders = {
    insideHorizontal: { style: "thin", color: "#E2E8F0" },
    bottom: { style: "thin", color: "#CBD5E1" },
  };
}
readme.getRange("A1:A20").format.columnWidth = 42;
readme.getRange("B1:B20").format.columnWidth = 105;
readme.getRange("A1:B20").format.wrapText = true;
readme.getRange("A5:B20").format.autofitRows();

const readmeCheck = await workbook.inspect({
  kind: "table", range: "README!A1:B20", include: "values,formulas",
  tableMaxRows: 20, tableMaxCols: 2, maxChars: 7000,
});
const mappingCheck = await workbook.inspect({
  kind: "table", range: `Mappings!A1:${mappingLastColumn}3`, include: "values,formulas",
  tableMaxRows: 3, tableMaxCols: mappingHeaders.length, maxChars: 9000,
});
const contractCheck = await workbook.inspect({
  kind: "table", range: `Contract Artifacts!A1:${contractLastColumn}4`, include: "values,formulas",
  tableMaxRows: 4, tableMaxCols: contractHeaders.length, maxChars: 8000,
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
  maxChars: 3000,
});
console.log(readmeCheck.ndjson);
console.log(mappingCheck.ndjson);
console.log(contractCheck.ndjson);
console.log(formulaErrors.ndjson);

await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range, fileName, scale] of [
  ["README", "A1:B20", "readme.png", 1.5],
  ["Mappings", `A1:${mappingLastColumn}12`, "mappings.png", 0.55],
  ["Contract Artifacts", `A1:${contractLastColumn}12`, "contract-artifacts.png", 0.65],
]) {
  const preview = await workbook.render({ sheetName, range, scale, format: "png" });
  await fs.writeFile(`${previewDir}/${fileName}`, new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`wrote ${outputPath}`);
