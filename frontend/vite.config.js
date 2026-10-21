import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The part of the Content Security Policy that depends on where the backend
// is. vercel.json's header cannot read an environment variable, so a header
// that named the backend would have to be edited by hand whenever it moved
// (it was pinned to one onrender.com hostname). This is built from
// VITE_API_URL, the same variable src/auth.js sends every request to, so the
// two can never disagree. vercel.json keeps the rest of the policy plus
// frame-ancestors (which a <meta> tag cannot carry); the browser applies both
// policies and a request has to pass each one. Build only: a dev server needs
// inline scripts and a websocket this would block.
const csp = () => {
  let apiUrl
  return {
    name: 'csp-from-api-url',
    apply: 'build',
    configResolved(config) {
      // Vercel's project settings arrive as process.env; a local .env as config.env.
      apiUrl = process.env.VITE_API_URL || config.env.VITE_API_URL || 'http://localhost:8000'
    },
    transformIndexHtml() {
      return [{
        tag: 'meta',
        attrs: {
          'http-equiv': 'Content-Security-Policy',
          content: `default-src 'self'; connect-src 'self' ${new URL(apiUrl).origin}`,
        },
        injectTo: 'head-prepend',
      }]
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), csp()],
})
