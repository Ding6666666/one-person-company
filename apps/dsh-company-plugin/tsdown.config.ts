import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import * as path from 'node:path'
import { transform } from 'lightningcss'
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
    ...(client ? { deps: { alwaysBundle: ['zod'], onlyAllowBundle: ['zod'] } } : {}),
    ...(client ? {
      outputOptions: {
        entryFileNames: 'client.js',
        banner: 'window.__ModuleLoader__.load({ id: "@dsh/company-plugin", factory: (require) => {',
        footer: 'return module.exports; } });',
        intro: 'var module = { exports: {} }; var exports = module.exports;',
      },
    } : {}),
    plugins: !client ? [] : [{
      name: 'company-image-assets',
      resolveId(source, importer) {
        if (!source.endsWith('.png') || importer === undefined) return null
        const emitted = path.resolve(path.dirname(importer), source)
        const sourceFile = existsSync(emitted)
          ? emitted
          : path.resolve('src', path.relative(path.resolve('lib/types'), emitted))
        return `\0company-image:${sourceFile}`
      },
      async load(id) {
        if (!id.startsWith('\0company-image:')) return null
        const fileId = id.slice('\0company-image:'.length)
        this.addWatchFile(fileId)
        const source = await readFile(fileId)
        return `export default ${JSON.stringify(`data:image/png;base64,${source.toString('base64')}`)};`
      },
    }, {
      name: 'company-css-modules',
      resolveId(source, importer) {
        if (!source.endsWith('.module.css')) return null
        const emitted = importer === undefined ? source : path.resolve(path.dirname(importer), source)
        const sourceFile = existsSync(emitted)
          ? emitted
          : path.resolve('src', path.relative(path.resolve('lib/types'), emitted))
        return `\0company-css:${sourceFile}.mjs`
      },
      async load(id) {
        if (!id.startsWith('\0company-css:')) return null
        const fileId = id.slice('\0company-css:'.length, -'.mjs'.length)
        this.addWatchFile(fileId)
        const source = await readFile(fileId)
        const result = transform({ filename: fileId, code: source, cssModules: true, minify: true })
        const classes = Object.fromEntries(Object.entries(result.exports ?? {}).map(([name, value]) => [name, value.name]))
        const tagId = `@dsh/company-plugin/${path.basename(fileId)}`
        return [
          `const css = ${JSON.stringify(result.code.toString())};`,
          `const tagId = ${JSON.stringify(tagId)};`,
          'if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(tagId) + "]") === null) {',
          '  const tag = document.createElement("style");',
          '  tag.dataset.plugin = "@dsh/company-plugin";',
          '  tag.dataset.pluginCss = tagId;',
          '  tag.textContent = css;',
          '  document.head.appendChild(tag);',
          '}',
          `export default ${JSON.stringify(classes)};`,
        ].join('\n')
      },
    }],
  }
})
