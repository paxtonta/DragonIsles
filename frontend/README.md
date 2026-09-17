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

Deploy the repository root as the Vercel project root. The root package
delegates the Next.js build to `frontend/`, while `api/index.py` exposes the
FastAPI application under the same Vercel domain. No `DRAGONISLES_API_URL`
value is needed for this same-project deployment.

The local Next.js development server still proxies `/api/*` to
`http://127.0.0.1:8125` by default. Set `DRAGONISLES_API_URL` only when using
the frontend with a separately hosted API outside Vercel.
