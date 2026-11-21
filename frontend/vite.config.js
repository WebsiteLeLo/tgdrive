import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:3005',
      '/stream': 'http://127.0.0.1:3005',
      '/thumb': 'http://127.0.0.1:3005',
    }
  }
});
