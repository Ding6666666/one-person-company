import { defineConfig } from 'tsdown'

export default defineConfig({
  entry: ['lib/types/index.js'],
  outDir: 'dist',
  format: ['esm'],
  platform: 'neutral',
  target: 'es2024',
  dts: false,
  clean: true,
})
