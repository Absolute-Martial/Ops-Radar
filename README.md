# OpsRadar

OpsRadar is a lightweight internal service desk, approval orchestrator, audit engine, and friction radar.

This repository is the hackathon implementation being prepared for:

- https://internal-tools-hacks.devpost.com/

OpsRadar is not just a dashboard. It is meant to become the system of record for internal requests such as access requests, Jira project creation, vendor review, onboarding support, and other approval-heavy internal operations.

## Problem It Solves

Internal operations often fail because the request state is fragmented across Slack, email, Jira, and direct messages.

Common failure modes:

- no single canonical record for a request
- buried approval requests
- unclear current owner
- missing SLA visibility
- weak auditability
- no measurable view of workflow friction

OpsRadar addresses that by creating one tracked lifecycle for each request:

`request -> owner -> approval -> fulfillment -> audit -> completion`

The current implementation is focused on proving that coordination loop end to end.

## Current Product State

OpsRadar currently provides:

- Request Catalog
- Approval Inbox
- Intake Sources
- Workflow Templates
- Role Builder
- Friction Dashboards
- real request lifecycle records
- approval and request event tracking
- simulated fulfillment tasks
- controlled intake-source handling
- structured Slack intake
- operator documentation with MkDocs Material
- CI, GHCR image publishing, and docs publishing workflows

Current product claim:

> OpsRadar is an early internal request coordination system. It has real request records, controlled intake, role-routed approvals, simulated fulfillment, and audit-friendly lifecycle tracking.

## What Is Implemented Now

The implemented runtime includes:

- database-backed request records
- request events / timeline records
- approval records
- comments
- policy result records
- fulfillment tasks
- simulated access grants
- intake source configuration
- intake event ingestion
- friction metrics from request lifecycle data

Supported lifecycle actions include:

- create request
- submit request
- search for duplicate requests
- approve / reject
- request more info
- provide info
- mark fulfillment complete
- close with audit trail

## What Is Not Yet Claimed As Live

These are not yet fully active runtime systems in the current build:

- Temporal durable workflow engine
- Novu notification delivery
- Casbin runtime authorization engine
- OPA policy execution
- OpenFGA relationship authorization
- Google Workspace real provisioning
- arbitrary Slack message parsing

Those may be added later, but they should not be claimed as completed in the current hackathon state.

## Architecture

OpsRadar uses a process-mining-shaped application structure and extends it with an internal request lifecycle layer.

### Core stack

- Frontend: React, TypeScript, Vite, Zustand
- Backend: FastAPI, SQLAlchemy, Celery
- Database: PostgreSQL
- Queue/cache: Redis
- Deployment: Docker Compose
- Auth: JWT-based session flow

### Runtime shape

```text
React SPA
  ->
FastAPI backend
  ->
PostgreSQL
  ->
Redis + Celery
```

### OpsRadar-specific runtime layer

On top of the core workflow stack, OpsRadar adds:

- request lifecycle tables
- approval records
- request event timeline
- role-routed approval handling
- controlled intake-source management
- Slack structured intake
- simulated fulfillment
- friction metrics based on request events

### Data flow

```text
request form or configured intake source
-> ops request record
-> policy / routing decision
-> approval record(s)
-> request events timeline
-> fulfillment task
-> simulated access grant
-> completed audit trail
```

## Architecture References

OpsRadar uses a lightweight request-operations stack with these open-source references:

### Workflow engine

- Temporal
- https://github.com/temporalio/temporal

Temporal is the durable workflow reference for long-running request execution and escalation handling.

### Process-mining foundation

- PM4Py
- https://github.com/process-intelligence-solutions/pm4py

PM4Py is the process-mining reference for event-log and workflow analysis primitives.

## Local Run

Requirements:

- Docker Engine with `docker compose`

Start the full local test stack:

```bash
docker compose up -d --build
```

Open:

- `http://localhost:3000`

For local dev with bind mounts and hot reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

If you want the host-published frontend without hot reload, use:

```bash
docker compose -f docker-compose.yml -f docker-compose.localhost.yml up -d --build
```

For a production-shaped stack with the edge Nginx proxy and the
Temporal worker included, use:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

That profile publishes the public edge on port 80 by default. Override
`OPS_RADAR_PUBLIC_PORT` if your deployment needs a different host port.

## Documentation

Operator docs are provided with MkDocs Material.

Install docs dependencies:

```bash
pip install -r docs/requirements.txt
```

Run docs locally:

```bash
mkdocs serve
```

Then open:

- `http://127.0.0.1:8000`

Main docs files:

- [`mkdocs.yml`](./mkdocs.yml)
- [`docs/index.md`](./docs/index.md)
- [`docs/operators/overview.md`](./docs/operators/overview.md)
- [`docs/operators/request-lifecycle.md`](./docs/operators/request-lifecycle.md)
- [`docs/operators/roles-and-ownership.md`](./docs/operators/roles-and-ownership.md)
- [`docs/operators/slack-intake.md`](./docs/operators/slack-intake.md)



## Just Describing


## Quick installation (local development)

Requirements:

- Docker Engine 20.10+ with the Compose V2 plugin
  (`docker compose`, not the legacy `docker-compose`)
- ~8 GB RAM free for the containers
- A copy of this repo

Steps:

```bash
# 1. Clone
https://github.com/Absolute-Martial/Ops-Radar.git
cd Ops-Radar

# 2. Create your .env from the template
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY, and
# OPS_RADAR_ENCRYPTION_KEY. Commands that generate strong values
# are inside .env.example.

# 3. Start the full stack with hot-reload for dev
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 4. Wait ~30s for migrations to finish, then open
#    http://localhost:3000 in a browser.
#    The first user to register is auto-promoted to admin. To
#    promote a later user, use the ops CLI:
docker compose exec backend python -m app.cli user promote \
  --email you@example.com
```

That's it — edits under `./backend` and `./frontend` hot-reload
without rebuilding.

---

## Repo layout

```
opsradar/
├── backend/            # FastAPI + Celery
│   ├── app/
│   │   ├── api/        # FastAPI routers, one file per resource
│   │   ├── models/     # SQLAlchemy ORM models
│   │   ├── schemas/    # Pydantic request/response models
│   │   ├── services/   # Business logic (mining, LLM, connectors, ...)
│   │   ├── workers/    # Celery tasks (beat schedule, background jobs)
│   │   ├── mcp/        # Model Context Protocol server (stdio)
│   │   ├── config.py   # Pydantic-settings env loader
│   │   ├── database.py # Async + sync SQLAlchemy engines
│   │   └── main.py     # FastAPI app, middleware wiring, router registration
│   ├── alembic/        # DB migrations
│   ├── scripts/        # One-off dev scripts (prompt tuning, bench, etc.)
│   └── tests/
├── frontend/           # React + Vite + Zustand + Tailwind
│   ├── src/
│   │   ├── api/        # API client (auth, mining, ai, ...)
│   │   ├── components/ # Reusable UI grouped by feature
│   │   ├── pages/      # Top-level routed pages
│   │   ├── store/      # Zustand slices (ui, auth, filters, ...)
│   │   ├── types/      # Shared TypeScript types
│   │   └── hooks/      # Custom React hooks
│   └── nginx.conf      # Serves the built SPA + proxies /api to backend
├── docs/               # User + contributor documentation
│   ├── examples/       # Sample event logs (OCEL, XES, CSV)
│   ├── deploy/             # Kubernetes / helm / BI integration stubs
├── docker-compose.yml       # Production-safe default
├── docker-compose.dev.yml   # Dev override (hot-reload, bind mounts)
├── Makefile
└── README.md
```

---

## Coding standards

### Backend (Python)

- **Python 3.11.** Use type hints on all new public functions.
- **PEP 8** via `ruff check`. Line length is 100 (not 79).
- **Imports**: stdlib → third-party → local, blank line between groups.
- **Docstrings**: every public module and function. Prefer a
  one-sentence summary followed by a paragraph explaining *why*
  something is the way it is, not just *what* it does. The rest of
  the codebase is written this way — match the tone.
- **No `print()`** in production code. Use the `logging` module
  (structlog is wired up in `services/logging_setup.py`).
- **Error handling**: catch at the boundary, not the middle. Inside
  a service function it's usually fine to let exceptions propagate.
- **DB access**: async session via `Depends(get_db)` for request
  handlers. Sync engine (`app.database.sync_engine`) only for
  subprocess paths and the MCP server.
- **Tests**: pytest + async. Add tests alongside new features under
  `backend/tests/`.

### Frontend (TypeScript / React)

- **TypeScript strict mode.** No `any` without a `// eslint-disable`
  comment explaining why.
- **Functional components only.** No class components.
- **Zustand for state.** Don't add a new state manager; split the
  existing store into more slices if it's getting unwieldy.
- **Tailwind utility classes.** No CSS files (except the one Vite
  entry). Keep class lists legible — multi-line ternaries are fine.
- **API calls via `@/api/client`.** Don't call `fetch` directly from
  components.
- **File naming**: PascalCase for components and pages, camelCase
  for hooks and utilities.
- **Imports**: react / third-party / `@/` (internal) / relative.

## Containers and Publishing

This repo includes GitHub Actions for:

- CI validation
- backend/frontend image publishing to `ghcr.io`
- docs publishing to GitHub Pages

Published images can be used with compose through:

- `OPSRADAR_BACKEND_IMAGE`
- `OPSRADAR_FRONTEND_IMAGE`

## Repo Notes

- The active implementation work is in the current OpsRadar checkout.
- Some lower-level legacy naming still remains in compatibility surfaces such as role settings endpoints. That is known and currently tolerated where changing it would risk breakage.

## License

MIT. See [`LICENSE`](./LICENSE).
