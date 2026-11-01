import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  
  // Для development режима (npm run dev)
  server: {
    host: '0.0.0.0', // Разрешаем доступ со всех IP
    port: 5173,
    
    // Прокси для разработки
    proxy: {
      '/api': {
        target: 'http://localhost:5000', 
        changeOrigin: true,
        secure: false,
      },
      '/cover': {
        target: 'http://localhost:5000/api',
        changeOrigin: true,
        secure: false,
      }
    }
  },
  
  // Для production сборки (npm run build)
  build: {
    outDir: 'dist', // Папка для сборки
    emptyOutDir: true, // Очищать папку перед сборкой
    sourcemap: false, // Не создавать sourcemaps для production
    
    // Оптимизация
    rollupOptions: {
      output: {
        manualChunks: undefined, // Один бандл для простоты
      }
    }
  },
  
  // Базовый путь для production
  base: '/',
})
