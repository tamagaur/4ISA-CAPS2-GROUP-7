import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The part of the Content Security Policy that depends on where the backend
// is. vercel.json's header cannot read an environment variable, so a header
// that named the backend would have to be edited by hand whenever it moved
// (it was pinned to one onrender.com hostname). This is built from
// VITE_API_URL, the same variable src/auth.js sends every request to, so the
// two can never disagree. The browser applies both policies and a request has
// to pass each one, so this tag carries connect-src ONLY. vercel.json holds
// everything else, default-src 'self' included, plus frame-ancestors (which a
// <meta> tag cannot carry), and a broad connect-src ('self' https:) that this
// tag narrows to the one API origin.
//
// It used to say "default-src 'self'; connect-src ...": that default applied
// to every other kind of request as well, so it refused what vercel.json
// allows (Google Fonts, the select boxes' data: arrow images, Supabase
// avatars) and the deployed site showed none of them (audit NEW-SEC-1,
// 2026-10-21). Build only: a dev server needs inline scripts and a websocket
// this would block.
// Where profile pictures are served from (backend/avatar.py public_url):
// the same Supabase Storage path vercel.json's img-src names. "Adjust
// picture" reads the saved picture back with fetch() to crop it again, and
// fetch() is connect-src, so this tag has to allow it too; without it the
// tool said "Couldn't open the picture" (audit NEW-SEC-2, 2026-10-21).
// Storage answers with Access-Control-Allow-Origin: *.
const AVATAR_STORAGE = 'https://dsdxemtmbbmdtccwxzyk.supabase.co/storage/v1/object/public/'

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
          content: `connect-src 'self' ${new URL(apiUrl).origin} ${AVATAR_STORAGE}`,
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
