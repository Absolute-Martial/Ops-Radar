# OpsRadar Release Checklist

Use this checklist before cutting a public preview release.

## 1. Pick a version

For hackathon and preview releases, use a pre-1.0 tag such as:

- v0.1.0-preview
- v0.1.1-preview
- v0.2.0-preview

Recommended first release: v0.1.0-preview

## 2. Update release notes

Before tagging:

1. Update CHANGELOG.md.
2. Move finished items from Unreleased into the target version section.
3. Keep limitations honest.
4. Mention whether fulfillment is simulated or live.

## 3. Verify local install

From a clean checkout:

1. Copy .env.example to .env.
2. Set SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, and OPS_RADAR_ENCRYPTION_KEY.
3. Run docker compose up -d --build.
4. Open http://localhost:3000.
5. Register the first account and verify it becomes the instance admin.

## 4. Run checks

Backend:

- cd backend
- python -m pytest -q --tb=short

Frontend:

- cd frontend
- npm ci
- npx tsc --noEmit
- npx vite build

Docs:

- pip install -r docs/requirements.txt
- mkdocs build --strict

Release contract tests:

- python -m pip install pytest pyyaml
- python -m pytest -q tests/test_release_contract.py

Compose:

- docker compose config >/dev/null
- docker compose -f docker-compose.yml -f docker-compose.production.yml config >/dev/null

## 5. Merge release branch

Merge the release-ready branch into develop or the target release branch.

## 6. Create and push a tag

Example:

- git tag v0.1.0-preview
- git push origin v0.1.0-preview

Pushing a v* tag triggers:

- GitHub Release creation
- GHCR backend image publishing
- GHCR frontend image publishing

Expected image names:

- ghcr.io/absolute-martial/ops-radar-backend
- ghcr.io/absolute-martial/ops-radar-frontend

## 7. Make GHCR packages public

After the first successful image publish, GitHub may mark packages private.

Open each package in GitHub, go to Package settings, and change visibility to Public.

Do this for:

- ops-radar-backend
- ops-radar-frontend

## 8. Verify install from published images

Set these in .env:

- OPSRADAR_BACKEND_IMAGE=ghcr.io/absolute-martial/ops-radar-backend:v0.1.0-preview
- OPSRADAR_FRONTEND_IMAGE=ghcr.io/absolute-martial/ops-radar-frontend:v0.1.0-preview

Then run:

- docker compose pull
- docker compose up -d

## 9. Release description template

Title:

OpsRadar v0.1.0-preview

Summary:

OpsRadar is an internal request coordination system for teams whose requests, approvals, fulfillment steps, and audit trails are scattered across Slack, Jira, email, and manual follow-up.

Highlights:

- Request Catalog for structured internal access requests
- Approval Inbox for role-routed decisions
- Request lifecycle timeline and audit trail
- Simulated fulfillment and access grants
- Friction Dashboards for operational bottlenecks
- Docker Compose quickstart
- First-user admin bootstrap
- GHCR backend/frontend images

Install:

1. Clone the repository.
2. Copy .env.example to .env.
3. Set required secrets.
4. Run docker compose up -d.
5. Open http://localhost:3000.

The first registered user becomes the instance admin.

Known limitations:

- Fulfillment is simulated in this preview.
- Real SaaS provisioning connectors are not claimed as live.
- Arbitrary Slack message parsing is intentionally not claimed as live.

## 10. Post-release sanity checks

- Release page exists.
- Backend image exists in GHCR.
- Frontend image exists in GHCR.
- Packages are public.
- docker compose pull works with tag-pinned images.
- Quickstart instructions still match the release.
