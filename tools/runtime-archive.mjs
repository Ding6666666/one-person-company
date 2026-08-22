import { mkdir } from 'node:fs/promises'
import { basename, dirname } from 'node:path'
import * as tar from 'tar'

function isRuntimeFile(path) {
  const normalized = path.replaceAll('\\', '/')
  return !normalized.split('/').includes('__pycache__')
    && !/\.(?:pyc|pyo)$/.test(normalized)
}

async function main([mode, source, destination]) {
  if (mode === '--create' && source !== undefined && destination !== undefined) {
    await mkdir(dirname(destination), { recursive: true })
    tar.c({
      cwd: dirname(source),
      file: destination,
      gzip: true,
      portable: true,
      sync: true,
      filter: isRuntimeFile,
    }, [basename(source)])
    return
  }
  if (mode === '--extract' && source !== undefined && destination !== undefined) {
    await mkdir(destination, { recursive: true })
    await tar.x({ cwd: destination, file: source })
    return
  }
  throw new Error('usage: runtime-archive.mjs --create <directory> <archive> | --extract <archive> <directory>')
}

await main(process.argv.slice(2))
