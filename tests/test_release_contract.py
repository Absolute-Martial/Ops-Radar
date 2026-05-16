"""Release-contract tests for OpsRadar packaging.

These tests intentionally avoid building images. They assert the static
contracts that make the Docker Compose + GHCR publishing story reliable:

- the publish workflow runs from active branches and version tags,
- the workflow has package-write permissions,
- backend/frontend images are pushed to GHCR,
- compose accepts published image references through env vars,
- workflow lint uses an install/run path instead of a missing action tag,
- the release workflow creates GitHub releases for v* tags.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _on_config(workflow: dict) -> dict:
    # PyYAML's YAML 1.1 resolver can parse the key `on` as True.
    return workflow["on"] if "on" in workflow else workflow[True]


def test_publish_workflow_runs_on_active_branches_and_tags() -> None:
    workflow = _load_yaml(".github/workflows/publish-images.yml")
    on_config = _on_config(workflow)

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


def test_release_workflow_creates_github_release_for_version_tags() -> None:
    workflow = _load_yaml(".github/workflows/release.yml")
    workflow_text = (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    on_config = _on_config(workflow)

    assert "v*" in on_config["push"]["tags"]
    assert "workflow_dispatch" in on_config
    assert workflow["permissions"]["contents"] == "write"
    assert "softprops/action-gh-release@v2" in workflow_text
    assert "CHANGELOG.md" in workflow_text
    assert "QUICKSTART.md" in workflow_text
    assert "ghcr.io/${OWNER_LC}/ops-radar-backend:${TAG}" in workflow_text
    assert "ghcr.io/${OWNER_LC}/ops-radar-frontend:${TAG}" in workflow_text


def test_release_docs_exist_and_describe_tag_flow() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_doc = (ROOT / "RELEASE.md").read_text(encoding="utf-8")

    assert "0.1.0-preview" in changelog
    assert "Known limitations" in changelog
    assert "git tag v0.1.0-preview" in release_doc
    assert "GHCR" in release_doc
    assert "first registered user becomes the instance admin" in release_doc.lower()


def test_ci_lints_workflows_without_missing_actionlint_action_tag() -> None:
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "rhysd/actionlint@v1" not in ci_text
    assert "download-actionlint.bash" in ci_text
    assert "actionlint" in ci_text


def test_compose_exposes_image_override_env_vars() -> None:
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "${OPSRADAR_BACKEND_IMAGE:-opsradar-backend:local}" in compose_text
    assert "${OPSRADAR_FRONTEND_IMAGE:-opsradar-frontend:local}" in compose_text
    assert "OPSRADAR_BACKEND_IMAGE=" in env_text
    assert "OPSRADAR_FRONTEND_IMAGE=" in env_text
