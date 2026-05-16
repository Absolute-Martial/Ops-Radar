# Installation

This guide is for judges, reviewers, and operators who want to run OpsRadar with Docker Compose.

## What you need

- Docker Engine 20.10+
- Docker Compose V2 (`docker compose`, not the old `docker-compose` command)
- A machine with at least 8 GB RAM for the full stack
- Ports `3000` and optionally `80` available

The default compose stack includes:

- React frontend
- FastAPI backend
- PostgreSQL
- Redis
- Celery worker and beat
- Temporal server, Temporal UI, and Temporal worker

## Fastest local install

```bash
git clone https://github.com/Absolute-Martial/Ops-Radar.git
cd Ops-Radar
cp .env.example .env
```

Edit `.env` and set the required secrets:

```bash
SECRET_KEY=
POSTGRES_PASSWORD=
REDIS_PASSWORD=
OPS_RADAR_ENCRYPTION_KEY=
```

Generate safe values:

```bash
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 24   # POSTGRES_PASSWORD
openssl rand -hex 24   # REDIS_PASSWORD
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Start the stack:

```bash
docker compose up -d --build
```

Open the app:

```text
http://localhost:3000
```

Check backend health:

```bash
curl http://localhost:3000/api/health || curl http://localhost:3000/api/v1/demo/status
```

If your frontend proxy does not expose health that way, check the backend container directly:

```bash
docker compose ps
docker compose logs backend --tail=100
```

## First user becomes the super admin

On a fresh deployment, the first account created through the registration page becomes the instance owner.

Internally, this account receives the global `admin` role. In operator language, treat this first `admin` user as the **super admin** because it can bootstrap the instance, manage users, configure workspaces, and promote or demote later users.

Every later self-registered user starts with the normal analyst-level role unless an existing admin changes that user’s role.

Recommended first-run flow:

1. Start Docker Compose.
2. Open `http://localhost:3000`.
3. Register your own account first.
4. Log in with that account.
5. Use it to configure workspaces, roles, intake sources, and other users.

If the wrong person creates the first account, an existing admin can promote the correct operator later from the UI or CLI.

Example CLI promotion:

```bash
docker compose exec backend python -m app.cli user promote --email you@example.com
```

## Demo/sample data mode

For a reviewable demo instance, you can seed sample data.

In `.env`:

```bash
SEED_SAMPLE_DATA_ON_FIRST_BOOT=1
```

Then restart:

```bash
docker compose up -d --build
```

Use `DEMO_MODE=1` only for a locked-down public demo. Demo mode enables anonymous demo login and blocks most writes for the demo user.

## Development mode with hot reload

For local development:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Use this when editing backend or frontend source code.

## Production-shaped local run

For a production-shaped stack with the edge proxy:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
```

The public edge defaults to port `80`. Override it in `.env`:

```bash
OPS_RADAR_PUBLIC_PORT=8080
```

## Using published images

If GitHub Container Registry images are available, set these in `.env`:

```bash
OPSRADAR_BACKEND_IMAGE=ghcr.io/absolute-martial/ops-radar-backend:latest
OPSRADAR_FRONTEND_IMAGE=ghcr.io/absolute-martial/ops-radar-frontend:latest
```

Then run:

```bash
docker compose pull
docker compose up -d
```

If images are not published or you want the latest local code, use:

```bash
docker compose up -d --build
```

## Useful commands

View running services:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f backend frontend worker
```

Restart the app:

```bash
docker compose restart backend frontend worker
```

Stop the stack:

```bash
docker compose down
```

Stop and delete local volumes:

```bash
docker compose down -v
```

Only use `down -v` when you are okay deleting local PostgreSQL, Redis, Temporal, and upload data.

## Backup reminder

Docker volumes contain the important data:

- `postgres_data`
- `upload_data`
- `temporal_postgres_data`

RAID or disk redundancy is not a backup. For any real deployment, back up the PostgreSQL volume and uploaded files to external storage.

## Troubleshooting

### Compose refuses to start

Check that required `.env` values are set:

```bash
SECRET_KEY
POSTGRES_PASSWORD
REDIS_PASSWORD
```

### Frontend opens but API fails

Check backend logs:

```bash
docker compose logs backend --tail=200
```

### Login/register does not work

Confirm the database and backend are healthy:

```bash
docker compose ps
docker compose logs db --tail=100
docker compose logs backend --tail=100
```

### You accidentally created the first admin with the wrong account

Log in as that admin and promote the correct user, or use the backend CLI if available:

```bash
docker compose exec backend python -m app.cli user promote --email correct@example.com
```

Then demote or deactivate the accidental account from the UI.
