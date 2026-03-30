import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: resolve(__dirname, '../src/stardrifter_orchestration_mvp/static'),
    emptyOutDir: false,
    rollupOptions: {
      input: {
        console: resolve(__dirname, 'console.html'),
      },
      output: {
        entryFileNames: '[name].bundle.js',
        chunkFileNames: '[name].chunk.js',
        assetFileNames: '[name].[ext]',
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    // SPA fallback: redirect all non-API, non-static requests to index
    historyApiFallback: true,
  },
});
