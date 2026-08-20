import { defineConfig } from 'tsdown'

export default defineConfig(({ env }) => {
  const client = env?.DSH_BUILD_FACE === 'client'
  return {
    entry: client ? { client: 'lib/types/client/index.js' } : ['lib/types/index.js'],
    outDir: 'dist',
    format: client ? ['cjs'] : ['esm'],
    platform: client ? 'browser' : 'node',
    target: 'es2024',
    dts: false,
    clean: !client,
    ...(client ? {
      outputOptions: {
        entryFileNames: 'client.js',
        banner: 'window.__ModuleLoader__.load({ id: "@dsh/company-plugin", factory: (require) => {',
        footer: 'return module.exports; } });',
        intro: 'var module = { exports: {} }; var exports = module.exports;',
      },
    } : {}),
  }
})
