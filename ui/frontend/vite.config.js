import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    chunkSizeWarningLimit: 650,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules/three')) return undefined
          if (id.includes('OrbitControls')) return 'three-controls'
          if (id.includes('GLTFLoader') || id.includes('meshopt_decoder')) return 'three-loaders'
          return 'three-core'
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
