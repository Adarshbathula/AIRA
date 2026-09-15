# Deploying AIRA for free

The measured footprint of this app (this repo, verified in-session):

| what | size |
|---|---|
| RAG stack on disk (faiss 24 + onnxruntime 66 + numpy 42 + langchain 6 + pypdf 4 MiB …) | **143 MiB** installed packages |
| ONNX MiniLM embedding model (downloaded on first use) | ~80-90 MiB, cached in `~/.cache/fastembed` |
| `frontend/dist` (built UI served by the API) | ~760 KiB |
| seeded SQLite DB + FAISS indexes (15 docs / 12 incidents) | ~420 KiB |
| **runtime RSS of the API in deterministic mode** | **297 MiB** (`ps -o rss= -p $(pgrep -f uvicorn)`, fastembed semantic mode, 29+23 vectors) |

So the hard constraint on free tiers is **512 MB RAM**, not disk: you land at ~300 MiB
before any request traffic, which is why `EMBEDDING_PROVIDER=lightweight` (see Route A)
is worth knowing about. Cold start measured on a fully cold cache: uvicorn bind →
`Application startup complete` in **4 s**, of which ~2 s was fastembed pulling
`Qdrant/all-MiniLM-L6-v2-onnx` from the Hub into `~/.cache/fastembed` (that directory, not
`~/.cache/huggingface`, holds the `.onnx` weights) - so bake the model into the image or
warm the cache in the build, otherwise every new container pays that download.

Four viable routes, in the order I would try them.

---

## Route A - Render, one free web service (recommended)

> Step-by-step version of this route (git → Blueprint → build → verify → what breaks):
> [`render-steps.md`](render-steps.md).
Free tier today: 512 MB RAM, 0.1 vCPU, 750 instance-hours/month per workspace,
spins down after 15 min idle with a ~1 min cold start, 5 GB/month bandwidth,
**unlimited static sites** (those never sleep), no credit card.

Files already in the repo: `Dockerfile.deploy` (repo root) and `render.yaml`.

1. Create a GitHub repo and push:
   ```bash
   cd ai-incident-resolution-assistant
   git init -q && git add -A && git commit -qm "AIRA"
   git branch -M main
   git remote add origin https://github.com/<you>/aira.git
   git push -u origin main
   ```
2. Render → **New → Blueprint** → pick the repo. It reads `render.yaml` and creates
   the service (Docker runtime, `plan: free`, health check `/api/health`).
3. In **Environment** set the two values you marked `sync: false`:
   `BOOTSTRAP_ADMIN_PASSWORD`, `BOOTSTRAP_USER_PASSWORD` (and `GROQ_API_KEY` only if
   you want fluent phrasing — everything works without it).
4. Deploy (~4-8 min: `npm ci`, `vite build`, `pip install`, seed baked into the image).
5. Open `https://aira.onrender.com`, sign in as `engineer@aira.test` / your password.

**Free-tier specifics that matter here**
- *Ephemeral disk*: uploads, new conversations and chat-created incidents are lost on
  restart/spin-down. Knowledge-base re-seeding is automatic because the DB + FAISS
  indexes were built **into the image**. Anything you want to keep → Route B's Postgres,
  or a nightly `pg_dump`/file copy.
- *Cold start*: the first request after 15 idle minutes waits ~1 min (Render's wake) +
  the ~4 s boot above while FAISS
  and the embedding model load (if the cache is empty). The UI handles it gracefully (amber *"Cannot reach the
  API - it may be restarting"* banner, session kept, **Retry** button).
- *512 MB cap*: set `EMBEDDING_PROVIDER=lightweight` to drop onnxruntime+MiniLM
  (~90 MiB of RAM and the model download at first start). Retrieval becomes lexical
  instead of semantic - grading, evidence validation, citations and the escalation path
  all still work; expect lower recall on paraphrased queries.
- *Free Postgres expires* (30-90 days). If you attach one:
  `DATABASE_URL=postgresql://…` (add `psycopg2-binary` to
  `backend/requirements.deploy.txt`) and re-run the seed inside the container:
  `docker compose run`-equivalent on Render = **Shell** (paid) or a temporary
  `docker compose run backend python ../scripts/seed_demo.py` locally against the
  external DB URL.

## Route B - Koyeb free web service (no sleep, has local disk)
Free: **1 web service, 512 MB RAM, 0.1 vCPU, 2 GB SSD**, always awake (no 15-min spin
down), 5 custom domains; regions Frankfurt / Washington DC. The 2 GB SSD lets SQLite +
FAISS files live on the container filesystem for the service's lifetime, which is the
nicest fit for this app.
```bash
docker login registry.koyeb.com
docker build -f Dockerfile.deploy -t registry.koyeb.com/<you>/aira:v1 .
docker push registry.koyeb.com/<you>/aira:v1
koyeb service create aira --app aira \
  --image registry.koyeb.com/<you>/aira:v1 \
  -e SECRET_KEY=$(openssl rand -hex 32) -e DATA_DIR=/tmp/data \
  -e BOOTSTRAP_ADMIN_EMAIL=admin@aira.test -e BOOTSTRAP_ADMIN_PASSWORD='Admin@12345' \
  -e BOOTSTRAP_USER_EMAIL=engineer@aira.test -e BOOTSTRAP_USER_PASSWORD='Engineer@123'
koyeb domain create aira.app          # or attach your own domain
```
Koyeb also accepts the repo directly (GitHub app + buildpack/Dockerfile) if you prefer
push-to-deploy; free instances can't run background workers, so keep everything in the
one web service (which is exactly how this app is built).

## Route C - static frontend + separate API (zero cold start for the UI)
Render's **free static sites never spin down**, so host the SPA there and the API
elsewhere:
- `frontend/` → Render Static Site (build `npm run build`, publish `dist`) or
  Cloudflare Pages / Netlify / Vercel free tier.
- Add a rewrite so the SPA's **relative** `/api/...` calls reach the API — no code
  change, because `frontend/src/services/api.ts` already uses relative URLs:
  ```
  /*  /YOUR-API-URL/api/:splat  200
  ```
  (Render: `public/_redirects`-style rule in the site config; Netlify:
  `_redirects` with `/*  https://aira.onrender.com/api/:splat  200`; Cloudflare Pages:
  `_routes`/functions proxy.)
- API service = Route A/B image with `SERVE_FRONTEND=false`.
- Set `CORS_ORIGINS=https://your-frontend.example` (or leave default `*` for a demo).
Only worth it if a ~1 min wake-up on the *page load itself* bothers you; the API still
sleeps in Route A.

## Route D - a free VM, if you have one
Oracle Cloud "Always Free" (Arm, up to 4 OCPU / 24 GB) or Google Cloud `e2-micro` run
this comfortably and permanently:
```bash
git clone <your repo> && cd <repo>
python3 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python ../scripts/seed_demo.py && cd ..
cd frontend && npm ci && npm run build && cd ..
nohup bash scripts/run.sh > /var/log/aira.log 2>&1 &      # supervised, auto-restarts
```
Then put Caddy/nginx in front for TLS, or use `docker compose up -d` (postgres + api +
nginx) which is already configured in `docker-compose.yml`. Free VMs have persistent
disks, so uploads/conversations survive restarts - the one thing the PaaS free tiers
cannot promise.

## Not free / not suitable
- **PythonAnywhere free**: 1 concurrent process, *no outbound network*, no npm - the
  frontend build and embedding-model download both break.
- **Vercel/Netlify serverless functions**: the API keeps process state (FAISS indexes,
  lazy RAG runtime) and writes files; Lambda-style timeouts and read-only filesystems
  fight it. Use them for the static frontend only.
- **Hugging Face Spaces**: works (SDK `docker`, port 7860 - override with
  `PORT=7860`) but the 16 GB ephemeral RAM is overkill for this and it dislikes
  non-ML repo layouts.

## Post-deploy checklist
```bash
curl -s https://<host>/api/health | python3 -m json.tool   # llm.mode, embeddings, vectors
curl -s -X POST https://<host>/api/auth/login -H 'Content-Type: application/json' \
     -d '{"email":"engineer@aira.test","password":"..."}' | head -c 80
curl -s https://<host>/ | grep -o '<div id="root">'       # SPA shell served
```
Then in the browser: sign in → Assistant → ask
`Payment API returns HTTP 503 after deployment.` → expect an incident id,
`GOOD`/`POOR` retrieval quality, `SUPPORTED`/`INSUFFICIENT_EVIDENCE`, citations,
and an 11-12 step workflow trace.

## Things to change before it is public
`SECRET_KEY` (32+ random bytes), non-default `BOOTSTRAP_*` passwords, `environment=production`
(set cookies `Secure`), and HTTPS-only. If you skip these, anyone who finds the URL can
read every conversation.
