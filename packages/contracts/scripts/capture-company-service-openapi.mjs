import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

function argumentsByName(argv) {
  const values = new Map();
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || !value) {
      throw new Error(
        "Usage: node capture-company-service-openapi.mjs --api-commit <sha> --output <snapshot.json> --revision-output <record.json>",
      );
    }
    values.set(key, value);
  }
  return values;
}

const values = argumentsByName(process.argv);
const apiCommit = values.get("--api-commit");
const output = values.get("--output");
const revisionOutput = values.get("--revision-output");
if (!apiCommit || !output || !revisionOutput || !/^[0-9a-f]{7,64}$/i.test(apiCommit)) {
  throw new Error(
    "Usage: node capture-company-service-openapi.mjs --api-commit <sha> --output <snapshot.json> --revision-output <record.json>",
  );
}

const repositoryRoot = resolve(import.meta.dirname, "..", "..", "..");
const uv = process.platform === "win32" ? "uv.exe" : "uv";
const source = execFileSync(uv, ["run", "python", "-m", "dsh_company.api.openapi"], {
  cwd: repositoryRoot,
  encoding: "utf8",
});
JSON.parse(source);
const outputPath = resolve(output);
const revisionPath = resolve(revisionOutput);
mkdirSync(dirname(outputPath), { recursive: true });
mkdirSync(dirname(revisionPath), { recursive: true });
writeFileSync(outputPath, `${source.trim()}\n`, "utf8");
writeFileSync(
  revisionPath,
  `${JSON.stringify(
    {
      api_commit: apiCommit,
      source_kind: "FastAPI app.openapi()",
    },
    null,
    2,
  )}\n`,
  "utf8",
);
