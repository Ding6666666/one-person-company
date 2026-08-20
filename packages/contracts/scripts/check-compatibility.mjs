import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function argumentsByName(argv) {
  const values = new Map();
  for (let index = 2; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || !value) {
      throw new Error(
        "Usage: node check-compatibility.mjs --baseline <openapi.json> --candidate <openapi.json>",
      );
    }
    values.set(key, value);
  }
  return values;
}

function schemas(document) {
  const value = document.components?.schemas;
  if (!value || typeof value !== "object") {
    throw new Error("OpenAPI document has no components.schemas section");
  }
  return value;
}

function isNullable(schema) {
  return schema?.nullable === true || (Array.isArray(schema?.type) && schema.type.includes("null"));
}

function signature(schema) {
  return JSON.stringify({
    ref: schema?.$ref ?? null,
    type: schema?.type ?? null,
    format: schema?.format ?? null,
    additionalProperties: schema?.additionalProperties ?? null,
  });
}

function compareSchema(path, baseline, candidate, failures) {
  if (!candidate) {
    failures.push(`${path}: schema was removed`);
    return;
  }
  if (signature(baseline) !== signature(candidate)) {
    failures.push(`${path}: type changed`);
  }
  if (isNullable(baseline) !== isNullable(candidate)) {
    failures.push(`${path}: nullable changed`);
  }
  if (JSON.stringify(baseline.enum ?? null) !== JSON.stringify(candidate.enum ?? null)) {
    failures.push(`${path}: enum changed`);
  }
  const baselineRequired = new Set(baseline.required ?? []);
  const candidateRequired = new Set(candidate.required ?? []);
  if (
    JSON.stringify([...baselineRequired].sort()) !==
    JSON.stringify([...candidateRequired].sort())
  ) {
    failures.push(`${path}: required properties changed`);
  }
  for (const [propertyName, property] of Object.entries(baseline.properties ?? {})) {
    const nextProperty = candidate.properties?.[propertyName];
    if (!nextProperty) {
      failures.push(`${path}.properties.${propertyName}: field was removed`);
      continue;
    }
    compareSchema(`${path}.properties.${propertyName}`, property, nextProperty, failures);
  }
}

const values = argumentsByName(process.argv);
const baselinePath = values.get("--baseline");
const candidatePath = values.get("--candidate");
if (!baselinePath || !candidatePath) {
  throw new Error(
    "Usage: node check-compatibility.mjs --baseline <openapi.json> --candidate <openapi.json>",
  );
}

const baseline = schemas(JSON.parse(readFileSync(resolve(baselinePath), "utf8")));
const candidate = schemas(JSON.parse(readFileSync(resolve(candidatePath), "utf8")));
const failures = [];
for (const [name, schema] of Object.entries(baseline)) {
  compareSchema(`components.schemas.${name}`, schema, candidate[name], failures);
}
if (failures.length > 0) {
  console.error(`Incompatible OpenAPI change(s):\n- ${failures.join("\n- ")}`);
  process.exitCode = 1;
} else {
  console.log("OpenAPI compatibility check passed.");
}
