# Route A, step by step: Render free web service

Everything below is already committed in this repo (`Dockerfile.deploy`,
`.dockerignore`, `render.yaml`, `backend/requirements.deploy.txt`) - you only run
commands and click. **Docker is not required on your machine**: Render builds the image.

## 0. Prerequisites
```bash
git --version                       # need 2.x
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"   # GitHub must see this address
```
Plus: a GitHub account and a Render account (Google login works; **no credit card** for
`plan: free`). Optional: `gh` CLI, which replaces the "create repo in the browser" step.

## 1. Commit the project
```bash
cd ai-incident-resolution-assistant
git init -q && git add -A
git status --short | head -20        # sanity check BEFORE committing
```
You should see `backend/`, `frontend/src`, `frontend/package-lock.json`, `scripts/`,
`docs/`, `README.md`, `data/documents/*.md|pdf|...`, `.vscode/`, `Dockerfile.deploy`,
`.dockerignore`, `render.yaml`, `docker-compose.yml`.
You must **not** see `node_modules/`, `frontend/dist/`, `data/aira.db`,
`data/vectorstore/`, `backend/.env` (all excluded by `.gitignore`). The `.vscode/` folder is
intentionally tracked (fresh clone = runnable); drop it if you dislike that.

```bash
git commit -qm "AIRA: self-healing RAG incident assistant"
git branch -M main
```

## 2. Push to GitHub
Browser route: github.com → **New repository** → name `aira` → **Do not** add a README or
`.gitignore` (they would collide) → **Create** → then:
```bash
git remote add origin https://github.com/<you>/aira.git
git push -u origin main
```
CLI route: `gh repo create aira --private --source=. --remote=origin --push`.
`--private` keeps your sample runbooks off the internet.

## 3. Create the Render Blueprint
Render dashboard → **New +** → **Blueprint** → **Build a New Service from a Repository** →
select `aira` → Render shows a preview listing **1 service: `aira` (Docker, free)** because
it parsed `render.yaml` → **Apply**.
It then asks for the variables marked `sync: false`:
`BOOTSTRAP_ADMIN_PASSWORD`, `BOOTSTRAP_USER_PASSWORD`, `GROQ_API_KEY`,
`SECRET_KEY` (auto-generated, leave as is).
- `GROQ_API_KEY`: click **Skip** - the product is designed to run with no LLM.
- Use passwords you will remember; these become your logins on the public URL.

## 4. Watch the build (5-10 min)
Stages, in order, and what each means:
1. `npm ci` in the node stage (~1-3 min) - `package-lock.json` must be committed or this fails.
2. `npm run build` → `dist/` (Vite, ~20 s).
3. `pip install -r backend/requirements.deploy.txt` in the python stage (~1-2 min).
4. `COPY` of `backend/`, `scripts/`, `data/documents/`, `data/incidents/`, `dist`.
5. **Embedding warm-up** - prints `embeddings ready: sentence-transformers/all-MiniLM-L6-v2
   384 dim`; this bakes the ~90 MB ONNX model into the image so a cold container never
   downloads it at boot (verified locally, 1.2 s).
6. **Seed** - `python ../scripts/seed_demo.py`, expect `documents: stored=15`, `incidents=12`
   and `DB: documents = 15 | incidents = 12` written **into the image**.

If a step fails, **Logs** tab shows the exact line; the four usual causes are in §7.

## 5. Live URL + health check
`https://aira.onrender.com`. Render polls `/api/health` (set in `render.yaml`); Events
should show *Deployed* then health passing. Verify from your shell:
```bash
curl -s https://aira.onrender.com/api/health | python3 -m json.tool
# expect llm.mode="deterministic-grounded", embeddings.provider="fastembed",
#        vector_store.vectors>=29, database="ok"

curl -s -X POST https://aira.onrender.com/api/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"engineer@aira.test","password":"<what you typed>"}' | head -c 60
# expect {"access_token":"eyJ...","token_type":"bearer","role":"user"}

curl -s https://aira.onrender.com/ | grep -o '<div id="root">'   # SPA shell
```
Then in the browser: sign in → **Incident Assistant** → ask
`Payment API returns HTTP 503 after deployment.` → incident id, retrieval `GOOD`/`POOR`,
`SUPPORTED`, citations, workflow trace.

## 6. Know the two free-tier properties you just accepted
- **Sleep:** after 15 idle minutes the service spins down; the next request waits ~1 min
  while it boots (~4 s of that is our own startup). The SPA shows an amber *"Cannot reach
  the API - it may be restarting"* banner and keeps your session, with a **Retry** button.
- **No persistent disk:** anything written at runtime - uploads, new conversations,
  chat-created incidents, FAISS changes - lives on the container's scratch space and is
  **gone after a restart/redeploy**. The knowledge base survives because it is baked into
  the image (§4.5-6). Treat the URL as a demo, or move to a $7 plan / free VM when you
  want durability.

## 7. Failure modes, in the order people hit them
| symptom | fix |
|---|---|
| Blueprint screen: "*Select a repository* and nothing" | Render's GitHub app isn't installed - **Dashboard → Account settings → Git Providers → Install** and grant the repo |
| `npm ci` error `package-lock.json not found` | you committed without the lockfile: `git add frontend/package-lock.json` (no `!` rule in `.gitignore`, so it should be tracked) |
| Build uploads a huge context / takes forever | `.dockerignore` missing from your commit (it is required) |
| `ModuleNotFoundError: app` at boot | the `WORKDIR /app` + `cd /app/backend` lines were edited out of `Dockerfile.deploy` |
| Deploy fails health check, log shows `Read-only file system` while creating `data/documents/uploads` | set `DATA_DIR=/tmp/data` in the Render env vars (config derives paths from it, and `/tmp` is writable) |
| 502/516 while waking | normal for the first ~60 s; hard-refresh once the log says `Application startup complete` |
| login returns `Invalid credentials` | the `BOOTSTRAP_*` password you typed is not what you are using; change it in **Environment** and **Deploy** again (accounts are created at boot only if absent) |
| OOM (`Killed`, exit 137) | set `EMBEDDING_PROVIDER=lightweight` (drops ~90 MB of ONNX runtime; semantic recall falls back to lexical, everything else keeps working) |

## 8. Redeploys
Every `git push` to `main` triggers a new build automatically (Blueprint owns that
setting). Local preview before pushing:
```bash
docker build -f Dockerfile.deploy -t aira:local .
docker run --rm -p 8000:8000 aira:local     # then open http://localhost:8000
```
