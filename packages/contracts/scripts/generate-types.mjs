import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

function argumentsByName(argv) {
  const values = new Map();
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || !value) {
      throw new Error("Usage: node generate-types.mjs --input <openapi.json> --output <types.ts>");
    }
    values.set(key, value);
  }
  return values;
}

const values = argumentsByName(process.argv);
const input = values.get("--input");
const output = values.get("--output");
if (!input || !output) {
  throw new Error("Usage: node generate-types.mjs --input <openapi.json> --output <types.ts>");
}

const inputPath = resolve(input);
const outputPath = resolve(output);
const repositoryRoot = resolve(import.meta.dirname, "..", "..", "..");
const generatorCli = resolve(
  repositoryRoot,
  "node_modules",
  "openapi-typescript",
  "bin",
  "cli.js",
);
mkdirSync(dirname(outputPath), { recursive: true });
execFileSync(process.execPath, [generatorCli, inputPath, "-o", outputPath], { stdio: "inherit" });
