import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The API is proxied rather than called cross-origin in development, so the
    // dev setup matches production (same-origin behind one domain) and CORS
    // problems surface in staging rather than only after deploy.
    proxy: {
      '/api': {
        // Configurable because 8000 is a popular port: running a second project
        // alongside this one is enough to collide, and the failure looks like a
        // broken app rather than a busy socket.
        //
        //   VITE_DEV_API=http://127.0.0.1:8010 npm run dev
        target: process.env.VITE_DEV_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
