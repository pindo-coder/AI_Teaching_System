import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: [
      { find: '@', replacement: fileURLToPath(new URL('./src', import.meta.url)) },
      { find: /^element-plus$/, replacement: fileURLToPath(new URL('./src/plugins/elementPlusExports.ts', import.meta.url)) },
    ],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/vue') || id.includes('node_modules/@vue') || id.includes('node_modules/pinia')) return 'vue'
          if (id.includes('node_modules/element-plus') || id.includes('node_modules/@element-plus')) return 'element'
          if (id.includes('node_modules/axios')) return 'http'
        },
      },
    },
  },
})
