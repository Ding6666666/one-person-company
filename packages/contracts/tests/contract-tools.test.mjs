import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

const contractsRoot = resolve(import.meta.dirname, "..");
const fixture = join(contractsRoot, "fixtures", "minimal.openapi.json");
const generator = join(contractsRoot, "scripts", "generate-types.mjs");
const compatibility = join(contractsRoot, "scripts", "check-compatibility.mjs");
const capture = join(contractsRoot, "scripts", "capture-company-service-openapi.mjs");

function generate(output) {
  execFileSync(process.execPath, [generator, "--input", fixture, "--output", output], {
    encoding: "utf8",
  });
}

test("uses the canonical health response description", () => {
  const document = JSON.parse(readFileSync(fixture, "utf8"));
  assert.equal(document.paths["/health"].get.responses["200"].description, "Healthy");
});

test("generates the Company health contract", () => {
  const tempDirectory = mkdtempSync(join(tmpdir(), "dsh-company-contracts-"));
  const output = join(tempDirectory, "fixture-api.ts");

  try {
    generate(output);
    const types = readFileSync(output, "utf8");
    assert.match(types, /\/health/);
    assert.match(types, /HealthResponse/);
    assert.match(types, /status: "ok";/);
    assert.match(types, /service: "dsh-company";/);
  } finally {
    rmSync(tempDirectory, { force: true, recursive: true });
  }
});
test("generates deterministically", () => {
  const tempDirectory = mkdtempSync(join(tmpdir(), "dsh-company-contracts-"));
  const first = join(tempDirectory, "first.ts");
  const second = join(tempDirectory, "second.ts");

  try {
    generate(first);
    generate(second);
    assert.equal(readFileSync(first, "utf8"), readFileSync(second, "utf8"));
  } finally {
    rmSync(tempDirectory, { force: true, recursive: true });
  }
});

test("rejects field removal and enum changes", () => {
  for (const name of ["field-removed", "enum-changed"]) {
    const result = spawnSync(
      process.execPath,
      [
        compatibility,
        "--baseline",
        fixture,
        "--candidate",
        join(contractsRoot, "fixtures", "breaking", `${name}.openapi.json`),
      ],
      { encoding: "utf8" },
    );
    assert.equal(result.status, 1, `${name} should fail compatibility: ${result.stderr}`);
  }
});

test("captures the Company service snapshot with exact provenance", () => {
  const tempDirectory = mkdtempSync(join(tmpdir(), "dsh-company-contracts-"));
  const snapshot = join(tempDirectory, "openapi.json");
  const revision = join(tempDirectory, "source-revision.json");

  try {
    execFileSync(
      process.execPath,
      [
        capture,
        "--api-commit",
        "0123456789abcdef0123456789abcdef01234567",
        "--output",
        snapshot,
        "--revision-output",
        revision,
      ],
      { encoding: "utf8" },
    );
    const document = JSON.parse(readFileSync(snapshot, "utf8"));
    assert.ok(document.paths["/health"]);
    assert.deepEqual(JSON.parse(readFileSync(revision, "utf8")), {
      api_commit: "0123456789abcdef0123456789abcdef01234567",
      source_kind: "FastAPI app.openapi()",
    });
  } finally {
    rmSync(tempDirectory, { force: true, recursive: true });
  }
});
