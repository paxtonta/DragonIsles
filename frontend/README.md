# DragonIsles frontend

This Next.js app replaces the former inline browser UI while keeping the
Python game server and JSON API unchanged.

## Local development

From this directory:

```bash
npm install
npm run dev
```

Run the Python API separately on port `8125`. The Next.js rewrite proxies
`/api/*` to `http://127.0.0.1:8125` by default. Set `DRAGONISLES_API_URL` to
another API origin when needed.

## Vercel

Configure the frontend Vercel project root directory as `frontend` and set
`DRAGONISLES_API_URL` to the public URL of a separate Vercel project using the
FastAPI framework preset. Both projects can use this repository; the backend
project should use the repository root and the `app:app` entrypoint.

The local Next.js development server still proxies `/api/*` to
`http://127.0.0.1:8125` by default. Set `DRAGONISLES_API_URL` only when using
the frontend with a separately hosted API.
