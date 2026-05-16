# OpsRadar

OpsRadar is a lightweight internal service desk, approval orchestrator, audit engine, and friction radar.

This repository is the hackathon implementation being prepared for:

- https://internal-tools-hacks.devpost.com/

OpsRadar is not just a dashboard. It is meant to become the system of record for internal requests such as access requests, Jira project creation, vendor review, onboarding support, and other approval-heavy internal operations.

## Quick Start

For the fastest Docker Compose setup, see:

- [`QUICKSTART.md`](./QUICKSTART.md)
- [`docs/operators/installation.md`](./docs/operators/installation.md)

Short version:

```bash
git clone https://github.com/Absolute-Martial/Ops-Radar.git
cd Ops-Radar
cp .env.example .env
# Edit .env and set SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, OPS_RADAR_ENCRYPTION_KEY
docker compose up -d --build
```

Open:

```text
http://localhost:3000
```

On a fresh deployment, the **first user who registers becomes the instance super admin**. Internally, this account receives the global `admin` role. Every later self-registered user starts as an analyst-level user until an admin changes their role.

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
- [`docs/operators/installation.md`](./docs/operators/installation.md)
- [`docs/operators/overview.md`](./docs/operators/overview.md)
- [`docs/operators/request-lifecycle.md`](./docs/operators/request-lifecycle.md)
- [`docs/operators/roles-and-ownership.md`](./docs/operators/roles-and-ownership.md)
- [`docs/operators/slack-intake.md`](./docs/operators/slack-intake.md)

## Repo layout

```text
opsradar/
├── backend/            # FastAPI + Celery
│   ├── app/
│   │   ├── api/        # FastAPI routers, one file per resource
│   │   ├── models/     # SQLAlchemy ORM models
│   │   ├── schemas/    # Pydantic request/response models
│   │   ├── services/   # Business logic (mining, LLM, connectors, ...)
│   │   ├── workers/    # Celery tasks (beat schedule, background jobs)
│   │   ├── mcp/        # Model Context Protocol server
│   │   ├── config.py   # Pydantic-settings env loader
│   │   ├── database.py # Async + sync SQLAlchemy engines
│   │   └── main.py     # FastAPI app, middleware wiring, router registration
│   ├── alembic/        # DB migrations
│   ├── scripts/        # One-off dev scripts
│   └── tests/
├── frontend/           # React + Vite + Zustand
│   ├── src/
│   │   ├── api/        # API client
│   │   ├── components/ # Reusable UI grouped by feature
│   │   ├── pages/      # Top-level routed pages
│   │   ├── store/      # Zustand slices
│   │   ├── types/      # Shared TypeScript types
│   │   └── hooks/      # Custom React hooks
├── docs/               # User + operator documentation
│   └── examples/       # Sample event logs
├── docker-compose.yml       # Production-safe default
├── docker-compose.dev.yml   # Dev override
├── QUICKSTART.md
├── Makefile
└── README.md
```

## Containers and Publishing

This repo includes GitHub Actions for:

- CI validation
- backend/frontend image publishing to `ghcr.io`
- docs publishing to GitHub Pages

Published images can be used with compose through:

- `OPSRADAR_BACKEND_IMAGE`
- `OPSRADAR_FRONTEND_IMAGE`

For Dokploy, use [`docker-compose.dokploy.yml`](./docker-compose.dokploy.yml).
It pulls the GHCR images directly, keeps the app off host port bindings, and
includes a `cloudflared` service on the shared `dokploy-network` so the tunnel
can resolve Dokploy routing.

Set `CLOUDFLARE_TUNNEL_TOKEN` in the Dokploy environment when you use the
bundled tunnel service.

## Repo Notes

- The active implementation work is in the current OpsRadar checkout.
- Some lower-level legacy naming still remains in compatibility surfaces such as role settings endpoints. That is known and currently tolerated where changing it would risk breakage.

## License

MIT. See [`LICENSE`](./LICENSE).
