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

The repository-level `vercel.json` defines one Vercel project with two
services: Next.js from `frontend/` and FastAPI from the repository root.
Requests under `/api/*` route to FastAPI; all other requests route to Next.js.
No `DRAGONISLES_API_URL` value is needed for this setup.

The local Next.js development server still proxies `/api/*` to
`http://127.0.0.1:8125` by default. Set `DRAGONISLES_API_URL` only when using
the frontend outside the Vercel Services deployment.
