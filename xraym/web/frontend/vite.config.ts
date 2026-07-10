import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/login': {
        target: 'http://localhost:2053',
        changeOrigin: true,
      },
      '/logout': {
        target: 'http://localhost:2053',
        changeOrigin: true,
      },
      '/panel/api': {
        target: 'http://localhost:2053',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:2053',
        changeOrigin: true,
      },
    },
  },
});
