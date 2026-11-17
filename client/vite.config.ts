import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api/hexa': { target: process.env.HEXA_API_PROXY || 'http://127.0.0.1:4010', changeOrigin: false } } },
});
