# Changelog

All notable changes to OpsRadar are documented here.

This project uses date-based pre-1.0 releases for hackathon and preview builds.

## [Unreleased]

### Added

- OpsReader remote MCP groundwork for authenticated AI-client access to OpsRadar context.
- Docker Compose installation guide for local, demo, and production-shaped deployments.
- Root `QUICKSTART.md` for reviewers and operators.
- GHCR Docker image publishing workflow for backend and frontend images.
- Release-contract tests for image publishing, compose image overrides, and workflow linting.
- First-user bootstrap tests proving the first registered account becomes the instance admin.
- In-memory rate limiting for backend tests so CI does not require Redis.

### Changed

- CI now runs workflow linting through a direct `actionlint` install path instead of a missing GitHub Action tag.
- CI validates compose with GHCR-style backend/frontend image references.
- Backend test environment now sets `REDIS_URL=memory://`.
- Release publishing now targets the active development flow instead of only `main`.

### Fixed

- Fixed backend auth bootstrap tests failing in CI because SlowAPI attempted to connect to `redis:6379`.
- Fixed GitHub Actions workflow lint failure caused by unresolved `rhysd/actionlint@v1`.

## [0.1.0-preview] - 2026-05-16

### Added

- Request Catalog for structured internal request creation.
- Approval Inbox for role-routed request decisions.
- Request lifecycle records for submission, approval, fulfillment, and completion.
- Request event timeline and audit-friendly history.
- Simulated fulfillment tasks and simulated access grants.
- Controlled intake-source configuration.
- Structured Slack intake foundation.
- Friction Dashboards based on request lifecycle data.
- Operator documentation with MkDocs Material.
- Docker Compose stack for backend, frontend, PostgreSQL, Redis, Celery, and Temporal scaffolding.

### Known limitations

- Fulfillment is simulated; real Google Workspace, Okta, GitHub, or Figma provisioning is not claimed as live.
- Arbitrary Slack message parsing is not claimed as live; OpsRadar favors controlled intake.
- Temporal, Novu, and Casbin may exist as scaffolding or partial integrations, but should not be described as fully production-hardened unless verified in runtime.
