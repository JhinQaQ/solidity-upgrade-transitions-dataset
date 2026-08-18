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
const outputPath = "data/upgrade_transactions_100.xlsx";
const previewDir = "spreadsheet-previews";

const csvText = await fs.readFile(csvPath, "utf8");
const jsonRows = JSON.parse(await fs.readFile(jsonPath, "utf8"));
console.log("phase: import CSV");
const workbook = await Workbook.fromCSV(csvText, { sheetName: "Mappings" });
const mappings = workbook.worksheets.getItem("Mappings");
const readme = workbook.worksheets.add("README");

// Preserve machine-readable types in the spreadsheet release copy.
console.log("phase: type normalization");
const headers = mappings.getRange("A1:Y1").values[0].map(String);
const dateFields = new Set([
  "block_timestamp_utc",
  "source_timestamp_utc",
  "validated_at_utc",
]);
const typedRows = jsonRows.map((row) => headers.map((field) => {
  const value = row[field];
  return dateFields.has(field) ? new Date(String(value)) : value;
}));
mappings.getRange("A2:Y101").values = typedRows;
for (const column of ["I", "R", "Y"]) {
  mappings.getRange(`${column}2:${column}101`).format.numberFormat = "yyyy-mm-dd hh:mm:ss";
}

mappings.showGridLines = false;
console.log("phase: mappings formatting");
mappings.freezePanes.freezeRows(1);
mappings.freezePanes.freezeColumns(3);
const fullRange = mappings.getRange("A1:Y101");
fullRange.format.font = { name: "Aptos", size: 10, color: "#172033" };
fullRange.format.rowHeight = 18;
const header = mappings.getRange("A1:Y1");
header.format = {
  fill: "#164E63",
  font: { name: "Aptos", size: 10, bold: true, color: "#FFFFFF" },
  wrapText: true,
  rowHeight: 42,
  verticalAlignment: "center",
};
const table = mappings.tables.add("A1:Y101", true, "UpgradeMappings");
table.style = "TableStyleMedium2";
table.showBandedRows = true;
table.showFilterButton = true;

const widths = {
  A: 13, B: 8, C: 18, D: 44, E: 44, F: 68, G: 15, H: 68, I: 22,
  J: 44, K: 20, L: 14, M: 44, N: 20, O: 12, P: 18, Q: 14, R: 22,
  S: 18, T: 15, U: 42, V: 16, W: 68, X: 25, Y: 22,
};
for (const [column, width] of Object.entries(widths)) {
  mappings.getRange(`${column}1:${column}101`).format.columnWidth = width;
}
mappings.getRange("B2:B101").format.numberFormat = "0";
mappings.getRange("G2:G101").format.numberFormat = "0";
mappings.getRange("N2:N101").format.numberFormat = "0";
mappings.getRange("P2:P101").format.numberFormat = "0";
mappings.getRange("V2:V101").format.numberFormat = "0";
for (const column of ["A", "C", "D", "E", "F", "H", "J", "K", "L", "M", "O", "T", "U", "W", "X"]) {
  mappings.getRange(`${column}2:${column}101`).format.numberFormat = "@";
}
mappings.getRange("Q2:Q101").conditionalFormats.add("cellIs", {
  operator: "equal",
  formula: "TRUE",
  format: { fill: "#DCFCE7", font: { color: "#166534" } },
});
mappings.getRange("S2:S101").conditionalFormats.add("cellIs", {
  operator: "equal",
  formula: "TRUE",
  format: { fill: "#DCFCE7", font: { color: "#166534" } },
});

readme.showGridLines = false;
console.log("phase: README sheet");
readme.freezePanes.freezeRows(3);
readme.getRange("A1:B1").values = [["Solidity Upgrade Transactions 100", null]];
readme.getRange("A2:B2").values = [[
  "Research-ready mapping release: Ethereum mainnet upgrade transaction → new implementation",
  null,
]];
readme.getRange("A4:B12").values = [
  ["Quality check", "Value"],
  ["Mapping rows", null],
  ["Successful receipts", null],
  ["Rows with Upgraded(address) validation flag", null],
  ["Rows with source/block timestamp validation flag", null],
  ["Network", "Ethereum mainnet (chain ID 1)"],
  ["Selection", "Deterministic SHA-256 ranking; at most one mapping per event-emitting proxy"],
  ["Scope", "Direct upgradeTo(address) and upgradeToAndCall(address,bytes) only"],
  ["Important limit", "This maps transactions to new implementations; it is not yet an old/new verification snapshot benchmark."],
];
readme.getRange("B5").formulas = [["=COUNTA('Mappings'!$A$2:$A$101)"]];
readme.getRange("B6").formulas = [["=COUNTIF('Mappings'!$O$2:$O$101,\"success\")"]];
readme.getRange("B7").formulas = [["=COUNTA('Mappings'!$Q$2:$Q$101)"]];
readme.getRange("B8").formulas = [["=COUNTA('Mappings'!$S$2:$S$101)"]];
readme.getRange("A14:B18").values = [
  ["Provenance", "Value"],
  ["Candidate dataset", "USCDetector"],
  ["Pinned source commit", "9b2bf71d1929a8bc27c88b52fe9224c24325cd68"],
  ["Pinned artifact URL", "https://raw.githubusercontent.com/xiaofan88/USCDetector/9b2bf71d1929a8bc27c88b52fe9224c24325cd68/upgrade_chains_data/proxy_upgrade_transactions_group_all_remove_repeat.json"],
  ["Paper", "Xiaofan Li et al., Characterizing Ethereum Upgradable Smart Contracts and Their Security Implications, WWW 2024"],
];
readme.getRange("A1:B18").format.font = { name: "Aptos", size: 11, color: "#172033" };
readme.getRange("A1:B1").format = {
  fill: "#0F172A",
  font: { name: "Aptos Display", size: 16, bold: true, color: "#FFFFFF" },
  rowHeight: 48,
};
readme.getRange("A2:B2").format = {
  fill: "#E0F2FE",
  font: { name: "Aptos", size: 11, color: "#0C4A6E" },
  rowHeight: 28,
};
for (const rangeAddress of ["A4:B4", "A14:B14"]) {
  readme.getRange(rangeAddress).format = {
    fill: "#164E63",
    font: { name: "Aptos", size: 11, bold: true, color: "#FFFFFF" },
    borders: { preset: "outside", style: "thin", color: "#0E7490" },
  };
}
readme.getRange("A5:A12").format.font = { bold: true, color: "#334155" };
readme.getRange("A15:A18").format.font = { bold: true, color: "#334155" };
readme.getRange("A4:B12").format.borders = {
  insideHorizontal: { style: "thin", color: "#E2E8F0" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
readme.getRange("A14:B18").format.borders = {
  insideHorizontal: { style: "thin", color: "#E2E8F0" },
  bottom: { style: "thin", color: "#CBD5E1" },
};
readme.getRange("A1:A18").format.columnWidth = 34;
readme.getRange("B1:B18").format.columnWidth = 105;
readme.getRange("A1:B18").format.wrapText = true;
readme.getRange("A5:B18").format.autofitRows();

const readmeCheck = await workbook.inspect({
  // Keep the final QA output compact and human-auditable.
  kind: "table",
  range: "README!A1:B18",
  include: "values,formulas",
  tableMaxRows: 18,
  tableMaxCols: 2,
  maxChars: 6000,
});
const mappingCheck = await workbook.inspect({
  kind: "table",
  range: "Mappings!A1:Y4",
  include: "values,formulas",
  tableMaxRows: 4,
  tableMaxCols: 25,
  maxChars: 6000,
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
console.log(formulaErrors.ndjson);

await fs.mkdir(previewDir, { recursive: true });
for (const [sheetName, range, fileName, scale] of [
  ["README", "A1:B18", "readme.png", 1.5],
  ["Mappings", "A1:Y12", "mappings.png", 0.8],
]) {
  const preview = await workbook.render({ sheetName, range, scale, format: "png" });
  await fs.writeFile(
    `${previewDir}/${fileName}`,
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`wrote ${outputPath}`);
