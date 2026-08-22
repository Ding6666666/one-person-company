import { access, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import * as tar from 'tar'

const CARRIER_ENTRY = join(
  'node_modules',
  '@deepseek-ai',
  'dsh-sdk-jsonrpc-demo',
  'lib',
  'packaged-bin.js',
)

export async function ensurePackagedRuntime(
  archivePath: string,
  runtimeDirectory: string,
): Promise<void> {
  try {
    await access(join(runtimeDirectory, CARRIER_ENTRY))
    return
  } catch {
    // Git packages carry the node closure as an archive because npm excludes nested node_modules.
  }
  const parent = dirname(runtimeDirectory)
  await mkdir(parent, { recursive: true })
  await tar.x({ cwd: parent, file: archivePath })
  await access(join(runtimeDirectory, CARRIER_ENTRY))
}
