import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../', import.meta.url))

const forbidden = [
  /(^|\/)\.env(?:\.|$)/u,
  /\.log$/u,
  /(^|\/)docs\/superpowers\/plans\//u,
  /(^|\/)\.venv\//u,
  /(^|\/)node_modules\//u,
  /(^|\/)dsh-company\.db(?:-shm|-wal)?$/u,
  /(^|\/)dsh-company-data\//u,
]

async function manifestSummary() {
  const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  return {
    name: manifest.name,
    patch: manifest.dsh?.bundle?.patch,
    host: manifest.exports?.['.']?.default,
    client: manifest.exports?.['./client']?.default,
  }
}

function normalizeFileName(value) {
  return value.trim().replaceAll('\\', '/')
}

function auditFileNames(fileNames) {
  const rejected = fileNames
    .map(normalizeFileName)
    .filter(Boolean)
    .filter(fileName => forbidden.some(pattern => pattern.test(fileName)))
  if (rejected.length === 0) return
  for (const fileName of rejected) process.stderr.write(`${fileName}\n`)
  process.exitCode = 1
}

async function filesFromPackJson(path) {
  const parsed = JSON.parse(await readFile(path, 'utf8'))
  const rows = Array.isArray(parsed) ? parsed : [parsed]
  return rows.flatMap(row => Array.isArray(row.files) ? row.files : [])
    .map(file => typeof file === 'string' ? file : file.path)
    .filter(file => typeof file === 'string')
}

async function main(arguments_) {
  const [mode, value] = arguments_
  if (mode === '--manifest-only') {
    process.stdout.write(`${JSON.stringify(await manifestSummary())}\n`)
    return
  }
  if (mode === '--file-list' && value !== undefined) {
    auditFileNames((await readFile(value, 'utf8')).split(/\r?\n/u))
    return
  }
  if (mode === '--pack-json' && value !== undefined) {
    auditFileNames(await filesFromPackJson(value))
    if (process.exitCode === undefined) {
      process.stdout.write(`${JSON.stringify(await manifestSummary())}\n`)
    }
    return
  }
  throw new Error(`usage: node ${ROOT}tools/audit-plugin-package.mjs --manifest-only|--file-list <path>|--pack-json <path>`)
}

await main(process.argv.slice(2))
