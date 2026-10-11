import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/worker/',
  build: {
    outDir: '../app/static/worker-ui',
    emptyOutDir: true,
  },
})
