import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', rewrite: path => path.replace(/^\/api/, '') },
      '/documents': 'http://127.0.0.1:7860',
      '/start': 'http://127.0.0.1:7860',
      '/sessions': 'http://127.0.0.1:7860',
    },
  },
});
