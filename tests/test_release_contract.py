"""Release-contract tests for OpsRadar packaging.

These tests intentionally avoid building images. They assert the static
contracts that make the Docker Compose + GHCR publishing story reliable:

- the publish workflow runs from the active default branch,
- the workflow has package-write permissions,
- backend/frontend images are pushed to GHCR,
- compose accepts published image references through env vars,
- the quickstart documents first-user bootstrap behavior.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_publish_workflow_runs_on_default_branch_and_tags() -> None:
    workflow = _load_yaml(".github/workflows/publish-images.yml")
    on_config = workflow["on"] if "on" in workflow else workflow[True]

    branches = on_config["push"]["branches"]
    tags = on_config["push"]["tags"]

    assert "develop" in branches
    assert "main" in branches
    assert "v*" in tags
    assert "workflow_dispatch" in on_config


def test_publish_workflow_has_ghcr_write_permissions() -> None:
    workflow = _load_yaml(".github/workflows/publish-images.yml")

    assert workflow["permissions"]["contents"] == "read"
    assert workflow["permissions"]["packages"] == "write"


def test_publish_workflow_pushes_backend_and_frontend_images() -> None:
    workflow_text = (ROOT / ".github/workflows/publish-images.yml").read_text(
        encoding="utf-8"
    )

    assert "docker/login-action@v3" in workflow_text
    assert "docker/metadata-action@v5" in workflow_text
    assert "docker/build-push-action@v6" in workflow_text
    assert "ops-radar-backend" in workflow_text
    assert "ops-radar-frontend" in workflow_text
    assert "push: true" in workflow_text
    assert "ghcr.io" in workflow_text


def test_compose_exposes_image_override_env_vars() -> None:
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "${OPSRADAR_BACKEND_IMAGE:-opsradar-backend:local}" in compose_text
    assert "${OPSRADAR_FRONTEND_IMAGE:-opsradar-frontend:local}" in compose_text
    assert "OPSRADAR_BACKEND_IMAGE=" in env_text
    assert "OPSRADAR_FRONTEND_IMAGE=" in env_text


def test_quickstart_documents_first_user_bootstrap() -> None:
    quickstart = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8").lower()
    installation = (ROOT / "docs/operators/installation.md").read_text(
        encoding="utf-8"
    ).lower()

    assert "first user" in quickstart
    assert "super admin" in quickstart
    assert "first user" in installation
    assert "super admin" in installation
    assert "admin" in installation
