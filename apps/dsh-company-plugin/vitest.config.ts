import ts from 'typescript'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [{
    name: 'company-standard-decorators',
    enforce: 'pre',
    transform(code, id) {
      const file = id.split('?', 1)[0]!
      if (!/\.[cm]?tsx?$/.test(file) || !/^\s*@[A-Za-z_$][\w$]*/m.test(code)) return
      return ts.transpileModule(code, {
        fileName: file,
        compilerOptions: {
          target: ts.ScriptTarget.ES2024,
          module: ts.ModuleKind.ESNext,
        },
      }).outputText
    },
  }],
  test: { include: ['tests/**/*.spec.ts'], restoreMocks: true },
})
