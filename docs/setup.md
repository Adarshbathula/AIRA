# Setup & recovery

Everything below runs from a normal Python (>= 3.11) + Node (>= 18) install. **No
virtualenv is required** - the app only needs the packages in
`backend/requirements.txt`.

## 1. Install

```bash
# backend
python3 -m pip install -r backend/requirements.txt

# frontend (only needed to (re)build the UI or to run the dev server)
cd frontend && npm install && npm run build && cd ..
```

`npm run build` produces `frontend/dist`. The API serves that build itself, so a
running system needs **one process, one origin**.

## 2. Seed the demo data

```bash
cd backend
python3 ../scripts/seed_demo.py            # incremental - safe to re-run
python3 ../scripts/seed_demo.py --fresh    # wipe DB + FAISS indexes first
```

Expected tail of a healthy run:

```
documents: stored=15 skipped=0 errors=0
incident history: files=2 incidents=12 errors=0
DB: documents = 15 | incidents = 12
```

## 3. Run

```bash
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` → the React app is served by the same process;
`/api/*` is the REST layer, so there is no proxy and no CORS to configure.

Dev mode with hot reload (optional, two processes):

```bash
cd backend  && python3 -m uvicorn app.main:app --port 8000
cd frontend && npm run dev            # http://localhost:5173, proxies /api -> :8000
```

## 4. Configuration

Settings live in `backend/app/core/config.py` and are read, in order of
precedence:

1. real environment variables (`export DATABASE_URL=...`)
2. `backend/.env` (git-ignored, for local secrets)
3. `backend/.env.dev` (committed demo defaults)
4. in-code defaults

`.env.dev` is what makes the repo runnable out of the box, and it is also the
reason the demo survives an ephemeral sandbox: the database path, data dir and
bootstrap accounts are absolute/derived, never relative to the current working
directory. `AIRA_ENV=test` swaps in `backend/.env.test` (SQLite in `/tmp`,
lightweight embeddings, LLM off) for the test suite.

| key | demo default | notes |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///…/data/aira.db` | `postgresql://…` in docker-compose |
| `DATA_DIR` | repo `data/` | documents, incidents, `vectorstore/` |
| `SECRET_KEY` | `local-dev-secret-change-me` | **change in production**: tokens are invalidated when it changes |
| `BOOTSTRAP_ADMIN_EMAIL/PASSWORD` | `admin@aira.test` / `Admin@12345` | created only when the users table is empty |
| `BOOTSTRAP_USER_EMAIL/PASSWORD` | `engineer@aira.test` / `Engineer@123` | created idempotently by seed/startup |
| `GROQ_API_KEY`, `LLM_ENABLED` | empty, `auto` | without a key the assistant answers in deterministic grounded mode |
| `SERVE_FRONTEND` | `true` | set `false` for API-only deployments |

## 5. Verify

```bash
cd backend
python3 -m pytest tests/                # 68 tests: auth/RBAC, ingestion, RAG, graph, evidence, API, eval
python3 ../scripts/smoke_api.py         # 46 end-to-end API checks against the live app
```

## 6. Troubleshooting

**Signed in, then bounced straight back to the sign-in screen.** That is the
preview/reverse proxy dropping the `Authorization` header: `/api/auth/login`
returns 200 (it needs no header) while every authenticated call returns 401. The
API therefore accepts the token through three equivalent transports - the bearer
header, `X-Aira-Token`, and the `aira_session` cookie set by `/api/auth/login`
(SameSite=Lax, cleared by `POST /api/auth/logout`) - and the SPA mirrors the token
into that cookie and replays a request via `X-Aira-Token` if a call comes back 401.
`test_token_survives_stripped_authorization_header` in `tests/test_auth.py` covers it.

**"Not authenticated" on the login screen.** The API answers that string when a
request reaches a protected route with no bearer token. Causes, in order of
likelihood:

- the API is not running - the Login screen now shows an explicit
  *"The API is not reachable from this page"* banner because `GET /api/health`
  failed; start it (step 3);
- the API restarted mid-session, so the JWT (signed with `SECRET_KEY`) no longer
  validates. Sign in again; keep `SECRET_KEY` fixed if a restart must not log
  everyone out;
- the browser blocks `localStorage` (sandboxed iframe, private mode). The client
  falls back to an in-memory token, so sign-in still works within the tab.

A failed profile refresh after a successful login no longer bounces you back to
the form: the token response (`access_token`, `role`) is authoritative for
authentication, so the session is established from it and the header is filled in
later.

**Login says *Invalid email or password* on a fresh database.** No accounts exist
yet for that email: `python3 ../scripts/seed_demo.py` (creates admin + demo
engineer), or register a new engineer from the login screen.

**Different behaviour depending on where uvicorn was started from.** That was a
real footgun with a relative `DATABASE_URL`; the default is now absolute (derived
from `DATA_DIR`). Check which file is in play with:

```bash
cd backend && python3 -c "import sys; sys.path.insert(0,'.'); \
from app.core.config import get_settings; print(get_settings().database_url)"
```

**Workspace/sandbox restarted and `node_modules` vanished.** Only the UI build
needs Node, and `frontend/dist` is a plain artefact: the API keeps serving the
last build with no `node_modules` present. Re-run `npm install && npm run build`
only when you change frontend code.

**DB has duplicate documents after repeated seeding.** It cannot: ingestion is
content-hashed, re-seeding is a no-op, and a duplicate upload returns `409`.
`python3 ../scripts/maintenance.py status` prints row counts and duplicate
hashes; `… dedupe` cleans up databases created by older builds.
