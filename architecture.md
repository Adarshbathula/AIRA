# AIRA — AI Incident Resolution Assistant
### Architecture, subsystems, technology stack, and why it works without an LLM

Code you can verify: `backend/app/**` (67 files, 6,611 lines Python),
`frontend/src/**` (29 files, 3,441 lines TS/TSX), `backend/tests/**` (8 files, 69 tests),
`scripts/` (seed, smoke, maintenance, run.sh), `data/` (15 sample documents, 12 seeded incidents).

---

## 1. What it is, in one paragraph

A self-contained enterprise support system that takes an incident description in
natural language (*"Payment API returns HTTP 503 after deployment"*) and returns a
**cited, evidence-gated** resolution package: normalised incident attributes, ranked
root-cause hypotheses, ordered troubleshooting steps, similar past incidents with
similarity scores, an AI-confidence signal, and a full workflow trace — or an explicit
*"insufficient evidence → escalate to SRE"* result. It is deliberately **not** a chatbot
wrapped around an LLM: the retrieval, grading, validation and confidence logic are
deterministic, and the LLM (if configured) can only *re-word* claims that already exist
in the retrieved documents.

Monolith, not microservices: one FastAPI process owns REST API + RAG + ingestion +
analytics; the React SPA is served from the same origin (`app/core/static.py`).

---

## 2. Request lifecycle (end to end)

```
user text
  │  POST /api/chat (JWT bearer | X-Aira-Token | aira_session cookie)
  ▼
incident_service.answer()                 backend/app/services/incident_service.py
  │   conversation create/reuse · follow-up context
  ▼
run_workflow()                            backend/app/graph/workflow.py:143
  │   LangGraph StateGraph, conditional retry loop, _run_local() fallback
  ▼
12 nodes → final state (JSON-safe, persisted)
  │
  ├─ incidents row (analysis, quality, attempts, confidence)
  ├─ recommendations + evidence rows (chunk_ref, quote)
  ├─ conversations + messages
  ├─ document_access log (→ usage analytics)
  └─ audit log (actions, uploads, deletes)
  │
  ▼
RAG runtime syncs  →  PostgreSQL/SQLite (facts) + FAISS (2 indexes: documents, incidents)
```

---

## 3. The LangGraph workflow

`backend/app/graph/workflow.py:79-95` wires it; `backend/app/graph/nodes/` holds the
twelve node modules (`_SUBMODULES` list in `nodes/__init__.py:43-47`).

| # | node | what it does | deterministic core |
|---|------|--------------|--------------------|
| 1 | `analyze` (incident_analyzer) | extracts `service, error, environment, event, category, severity, keywords` | regex/keyword extraction over the service & taxonomy tables; LLM only *augments* |
| 2 | `construct_query` (query_constructor) | builds 1-3 retrieval queries from the analysis | template + keyword ordering |
| 3 | `retrieve` (retriever) | FAISS search, multi-source, per-category cap | `MultiSourceRetriever` union over categories/service |
| 4 | `grade_context` (context_grader) | GOOD / FAIR / POOR verdict | weighted score, see §5 |
| 5 | `rewrite_query` (query_rewriter) | **self-healing**: reformulates and re-retrieves | triggered only by the POOR branch |
| 6 | `similar_incidents` | past-incident discovery + similarity % | dedicated FAISS index over incident vectors |
| 7 | `root_cause` | hypotheses with `CONFIRMED/PROBABLE/POSSIBLE/INSUFFICIENT_EVIDENCE` | extraction gated on service match + score |
| 8 | `troubleshoot` (recommendations) | ordered steps, each citing chunks | imperative-sentence extraction from runbooks |
| 9 | `validate_evidence` (evidence_validator) | `SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE` | lexical overlap between claim and cited chunk |
| 10 | `estimate_confidence` | 0-1 AI Confidence Score + per-signal breakdown | weighted blend, see §5 |
| 11 | `summarize` | the final answer text | template composition from validated items only |
| 12 | `assemble` | response DTO, trace, `_engine` marker | — |

Routing: `grade_context` → `route_after_grader` decides `rewrite_query` (retry) or
forward; `max_retrieval_attempts = 3` (`core/config.py:110`). Every node is wrapped in
`_timed()` and emits a trace entry `{node, status, detail, ms}` — the UI shows that, never
chain-of-thought. If `langgraph` is unavailable or `invoke()` throws, `_run_local()`
(`workflow.py:105`) executes the identical node functions in sequence with the same retry
loop, so the product never degrades to "the graph library broke".

---

## 4. Self-healing RAG, concretely

1. Retrieval returns chunks with cosine scores; the grader computes
   `0.30·top + 0.20·pass_ratio + 0.15·doc_coverage + 0.15·cat_coverage + 0.12·keyword_coverage + …`
   (`app/rag/grading/context_grader.py:37-43`).
   `context_good_threshold = 0.72` marks GOOD; **zero chunks is always POOR**
   (`app/graph/nodes/context_grader.py:22`).
2. POOR → `rewrite_query` broadens/re-terms the query and re-runs retrieval.
3. Retry cost is *visible*: confidence applies `-0.05` per extra attempt
   (`app/graph/nodes/confidence.py:94`), and the dashboard reports
   `avg_retrieval_attempts`.
4. Evaluation asserts the loop actually fires: `tests/test_rag.py` monkeypatches settings
   to force a POOR first pass and requires `attempt > 1` plus a `query_rewriter` trace node.

---

## 5. Evidence, citations, confidence

- **Citations.** Each chunk stores a human ref (`RUNBOOK-005`, `SOP-API-01`, `RCA-018`…)
  taken from `metadata_json["ref"]`, else `DOC-####`. Answer claims link to
  `document_chunks.chunk_ref` so the UI can open the exact excerpt.
- **Validation.** `evidence_validator` measures lexical overlap between a claim and its
  cited chunks → `SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE`; an unsupported
  claim is dropped, not softened.
- **Confidence** (`app/graph/nodes/confidence.py:86-94`):
  `0.24·retrieval + 0.16·document support + 0.18·cause consistency + 0.14·historical match
  + 0.10·grader + 0.18·evidence validation − 0.05·(attempts−1)`, capped 0.97, forced to
  `0.05` when nothing was retrieved, and labelled with `confidence_breakdown` — documented
  as a heuristic, never as a probability.
- **LLM can't override it.** `root_cause.py:160-200`: LLM suggestions are accepted only if
  every cited ref is in the retrieved set (`if not refs: continue  # unsupported LLM
  invention -> dropped by design`), and status/probability values outside the allowed
  enums are coerced.

---

## 6. Ingestion pipeline

`app/services/document_service.py`

```
file bytes → extension gate → parse_bytes() → clean_text() → split_sections()
           → recursive splitter (LangChain, with a built-in fallback) → chunk rows
           → embed → FAISS upsert → commit → (JSON/CSV incident rows → history store)
```

- **Formats:** PDF (`pypdf`), DOCX (`python-docx`), TXT/MD/LOG, HTML (`beautifulsoup4`),
  CSV, XLSX (`openpyxl`), JSON. `reportlab` builds sample PDFs in `scripts/`.
- **Structure-aware chunking** (`app/rag/ingestion/chunking.py`): headings must carry an
  explicit separator (`3.`, `2)`, `#`) so numbered *steps* are not mistaken for sections —
  a real bug caught by the suite (`test_api.py` asserts `chunk_count >= 1`).
- **Idempotent + duplicate-safe:** `content_hash = sha256(normalised text)`; re-seeding is a
  no-op, `POST /api/documents/upload` returns **409** on identical content, and deleting a
  seeded document never unlinks the sample file on disk.
- **Guards:** unsupported type 415, empty 400, too-small/parse failure 422, size limit 413.
- **Bulk ingest** over a directory is an admin endpoint too (`/api/documents/ingest-directory`).

## 7. Retrieval & vector store

- `app/rag/vectorstore/faiss_store.py`: FAISS `IndexFlatIP` over L2-normalised vectors
  (= cosine), side-car `metadata.jsonl` + `vectors.npy`, with a numpy fallback if FAISS
  is missing; `reset()/upsert()/commit()`; stores persisted under `data/vectorstore/`.
- **Two indexes**, one runtime (`app/rag/runtime.py`): `documents` and `incidents`.
- **Multi-source union** (`app/rag/retrieval/multi_source.py`): category filters
  (SOP, RUNBOOK, RCA, JIRA_INCIDENT, ARCHITECTURE, POSTMORTEM, LOG …), score threshold
  `retrieval_score_threshold = 0.28`, per-category cap to stop one runbook dominating.
- **Embeddings** auto-select `fastembed` MiniLM (384-d) and fall back to a deterministic
  hashed embedder — so the same code runs offline on a CPU-only box (`EMBEDDING_PROVIDER=auto`).
- **Similar incidents** (`app/rag/retrieval/incident_store.py`): vector built from
  description + service + category + known root cause; supports `exclude_public_id`, so an
  incident is never listed as its own "past occurrence".

## 8. Data model (10 tables)

`users`, `roles` (user/admin + permissions), `conversations`, `messages`, `incidents`
(analysis fields, `pipeline_state` JSON, retrieval quality/attempts, confidence, evidence
status, `public_id` `INC-####`), `documents`, `document_chunks` (`chunk_ref`, section,
`content_hash`-bearing parent), `recommendations`, `evidence` (citation + quote +
`chunk_ref`), `document_access` (usage analytics), `audit_log` (actor, action, target, meta).
Portable across **PostgreSQL and SQLite** because every query stays on the SQLAlchemy
expression layer — the suite runs the whole product on SQLite.

## 9. Auth & RBAC

`app/core/security.py`: bcrypt hashes, HS256 JWT (`sub`, `role`, `iat/exp`, `jti`),
`OAuth2PasswordBearer(auto_error=False)` + `extract_token()` accepting **bearer header,
`X-Aira-Token`, or the `aira_session` cookie** (set by login, cleared by
`POST /api/auth/logout`) — added because some reverse proxies strip `Authorization`.
`require_admin` guards admin routes; `ensure_user_ownership` gives users row-level access to
their own conversations/incidents and admins to all. Bootstrap accounts come from
`BOOTSTRAP_*` env, never hard-coded; a disabled account gets 403.

## 10. REST API (29 routes, `/api` prefix, OpenAPI at `/docs`)

auth `login, logout, me, register` · chat `POST /chat` · conversations `GET list, GET id,
PATCH, DELETE` · incidents `POST, GET list, GET id, GET by-public-id, POST similar,
POST {id}/resolution, DELETE {id}` · documents `GET list, GET id, POST upload,
PATCH, DELETE, GET categories, POST ingest-directory` · knowledge `POST /knowledge/search`
· dashboard `overview, incidents, root-causes, confidence, documents, retrieval, usage,
system, audit` · users `GET, POST, PATCH, DELETE` · `GET /api/health`.

## 11. React UI

`frontend/src` — Vite + React 18 + TypeScript (strict) + Tailwind + React Router 6 +
Axios + Recharts. Pages: Login (demo quick-fill), Dashboard (KPIs + charts), Assistant
(chat, workflow trace, confidence meter, evidence panel, escalation card, follow-ups),
History, Incidents, IncidentDetail, Knowledge (search + upload), admin Overview /
Documents / Users. `services/api.ts` holds one axios instance with the token interceptor,
401-aware session watchdog (distinguishes *token rejected* from *server unreachable*) and
`apiError()` message mapping; `context/AuthContext.tsx` treats the login response as
authoritative. Theme: dark-first `#171717 / #262626` with a persisted light/dark toggle
(`src/utils/theme.ts`, `index.css` variables also drive recharts).

## 12. Technology stack

| layer | technology | why here |
|---|---|---|
| orchestration | **LangGraph** `StateGraph`, conditional edges, timed nodes | explicit, traceable retry loop instead of a hidden chain |
| embeddings | **fastembed** (all-MiniLM-L6-v2, 384-d) → hashed fallback | offline-capable, no GPU |
| vector store | **FAISS** `IndexFlatIP` + `.npy`/`.jsonl` persistence; numpy fallback | exact cosine, no server dependency |
| chunking | **langchain-text-splitters** (fallback splitter included) | standard recursive sizing after section split |
| LLM (optional) | **Groq** `llama-3.3-70b-versatile` via `app/rag/llm.py` | re-phrasing only; output gated on citations |
| API | **FastAPI** + Pydantic v2 + `pydantic-settings`, python-multipart, email-validator | typed DTOs, auto OpenAPI |
| persistence | **SQLAlchemy 2.0**, **PostgreSQL 16** (docker) / **SQLite** (dev/tests), `psycopg2-binary` | same ORM both ways |
| parsing | pypdf, python-docx, openpyxl, beautifulsoup4 + lxml, csv/json stdlib, reportlab | multi-format ingestion |
| security | PyJWT, bcrypt | stateless tokens, salted hashes |
| frontend | React 18, TypeScript, Vite 5, Tailwind CSS 3, React Router 6, Axios, Recharts 2 | typed SPA + charts |
| testing | pytest (+ asyncio), FastAPI `TestClient`, httpx, custom eval assertions in `test_eval.py` | unit + e2e + quality metrics |
| ops | docker-compose (postgres/backend/nginx), `scripts/run.sh` supervisor, `.vscode` tasks/launch | one-command local + container runs |

## 13. **Why it works without an LLM**

This is the design, not a fallback mode. Today `GET /api/health` reports:

```json
"llm": {"provider": "none", "model": null,
        "mode": "deterministic-grounded",
        "note": "No GROQ_API_KEY configured - answers are evidence-derived (deterministic mode)"}
```

and the full pipeline still returns `INC-…` answers at 0.88-0.96 confidence with citations.

1. **Analysis is extraction, not generation.** Service/environment/error/severity/category/
   keywords are recognised by rules over known vocabularies, and `analyze` is *deterministic
   first, LLM second* — `llm_used` is only a flag recording that an optional enrichment
   happened (`incident_analyzer.py:203-215`).
2. **Retrieval needs no LLM.** Queries are templates over the extracted keywords; similarity
   is cosine over MiniLM/hashed embeddings inside FAISS.
3. **Self-healing needs no LLM.** The grader is a weighted arithmetic score
   (§4); the rewriter applies rule-based reformulations (keyword rotation, synonym
   expansion, category broadening).
4. **Root causes are lifted, not invented.** `extract_causes_from_chunks` reads explicit
   cause sentences ("Root cause: …", "Confirmed via …") from runbooks/RCAs and only marks a
   cause CONFIRMED when the service matches and the chunk scores well.
5. **Recommendations are selected, not composed.** Imperative steps already written in the
   runbook become the ordered plan, each carrying the `chunk_ref` it came from.
6. **Validation is lexical, therefore machine-checkable.** Claim-vs-evidence overlap decides
   `SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE`. The
   `insufficient_evidence` flag then drives the escalation card (`summarizer.py:106`).
7. **Confidence is a published formula** over signals it actually measured (§5) — nothing
   to hallucinate.
8. **Summarisation is template rendering.** The final text composes verified analysis,
   causes, steps and citations. With no LLM the answer reads mechanical; with one it reads
   fluent — the *facts, order and citations stay identical*.
9. **When an LLM is enabled it stays fenced in.** `llm.py` is only consulted if
   `available`; every suggestion must cite refs from the retrieved set or it is dropped
   (`root_cause.py:166-182`), and enum values are coerced. So an LLM can never add a
   document, a cause, or a confidence boost.
10. **Offline dependencies are optional by design:** `langgraph` → `_run_local()`; FAISS →
    numpy store; fastembed → hashed embeddings; Groq → deterministic grounded mode. Each
    substitution keeps the API contract identical — which is exactly what
    `python3 -m pytest tests/` (69 tests) exercises on a CPU-only box with no keys.

**Practical consequence:** you can run the whole system in an air-gapped network or without
an API budget and still get cited, verifiable guidance; the LLM is a *presentation* upgrade,
not a correctness dependency. To enable it: set `GROQ_API_KEY` (and optionally
`LLM_ENABLED=true`); health then reports `mode: llm-grounded` and `llm_used: true` per answer.

## 14. Testing & evaluation

- `tests/test_auth.py` (10) RBAC, ownership, bootstrap accounts, header/cookie transports.
- `tests/test_ingestion.py` (12+) parsers per format, chunking provenance, idempotency,
  corpus preservation, error codes.
- `tests/test_rag.py` vector store persistence, category union + caps, grader thresholds,
  self-healing retry, similar-incident search.
- `tests/test_graph.py` node contracts, grounded root-cause extraction.
- `tests/test_evidence.py` validator statuses, citation integrity.
- `tests/test_api.py` (12+) every endpoint incl. SPA hosting, upload 409/415/400/422.
- `tests/test_eval.py` (spec §34): retrieval precision/recall ≥ 0.75 against a labelled
  set, evidence faithfulness, grader alignment, latency budget, similar-incident proxy.
- `scripts/smoke_api.py`: 46 live end-to-end checks against a running server.
- Repro: `python3 -m pytest tests/` → **69 passed**; `python3 ../scripts/smoke_api.py` →
  **ALL 46 API SMOKE CHECKS PASSED**.

## 15. Run it

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python ../scripts/seed_demo.py        # 15 docs, 12 incidents
../.venv/bin/python -m uvicorn app.main:app --port 8000           # serves frontend/dist
cd ../frontend && npm install && npm run build                   # or: npm run dev (HMR, :5173)
bash scripts/run.sh                                              # supervised, auto-restarts
docker compose up --build                                         # postgres + api + nginx
```
Demo logins: `admin@aira.test / Admin@12345`, `engineer@aira.test / Engineer@123`.
Details and troubleshooting: [`docs/setup.md`](setup.md).
