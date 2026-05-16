# OpsRadar Quickstart

This is the fastest way to run OpsRadar locally with Docker Compose.

## Requirements

- Docker Engine 20.10+
- Docker Compose V2 (`docker compose`)
- At least 8 GB RAM available for the full stack

## 1. Clone the repository

```bash
git clone https://github.com/Absolute-Martial/Ops-Radar.git
cd Ops-Radar
```

## 2. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and set these required values:

```bash
SECRET_KEY=
POSTGRES_PASSWORD=
REDIS_PASSWORD=
OPS_RADAR_ENCRYPTION_KEY=
```

Generate values:

```bash
openssl rand -hex 32   # SECRET_KEY
openssl rand -hex 24   # POSTGRES_PASSWORD
openssl rand -hex 24   # REDIS_PASSWORD
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

## 3. Start OpsRadar

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:3000
```

## 4. Create the first admin account

On a fresh deployment, the first user who registers becomes the instance owner.

Internally this account receives the global `admin` role. Treat this first user as the **super admin** for the instance.

Every later self-registered user starts as a normal analyst-level user until an admin changes their role.

Recommended first-run flow:

1. Start the stack.
2. Open `http://localhost:3000`.
3. Register your own operator account first.
4. Use that account to configure workspaces, roles, intake sources, and users.

## 5. Optional: seed sample/demo data

For a reviewable local demo, set this in `.env`:

```bash
SEED_SAMPLE_DATA_ON_FIRST_BOOT=1
```

Then restart:

```bash
docker compose up -d --build
```

Use `DEMO_MODE=1` only when you want a locked-down public demo with anonymous demo login and write protection for the demo user.

## Useful commands

View services:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f backend frontend worker
```

Restart:

```bash
docker compose restart backend frontend worker
```

Stop:

```bash
docker compose down
```

Stop and delete all local data:

```bash
docker compose down -v
```

Only use `down -v` when you are okay deleting local database, Redis, Temporal, and upload data.

## More docs

See the full installation guide:

```text
docs/operators/installation.md
```

Or run the docs locally:

```bash
pip install -r docs/requirements.txt
mkdocs serve
```

Then open:

```text
http://127.0.0.1:8000
```
