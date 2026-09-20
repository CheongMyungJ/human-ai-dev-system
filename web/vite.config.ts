import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발 서버는 제어부 API로 프록시한다. 빌드 산출물(dist/)은 제어부가 직접 서빙하므로
// 일반 설치 사용자는 Node 로 화면을 빌드할 필요가 없다(implementation-baseline 1절).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.HADS_CONTROLLER_URL ?? 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
