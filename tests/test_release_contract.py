"""Release-contract tests for OpsRadar packaging.

These tests intentionally avoid building images. They assert the static
contracts that make the Docker Compose + GHCR publishing story reliable:

- the publish workflow runs from active branches and version tags,
- the workflow has package-write permissions,
- backend/frontend images are pushed to GHCR,
- compose accepts published image references through env vars,
- workflow lint uses a pinned actionlint install path,
- the release workflow creates GitHub releases for v* tags.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
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


def test_ci_lints_workflows_with_pinned_actionlint_install() -> None:
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "rhysd/actionlint@v1" not in ci_text
    assert re.search(r'ACTIONLINT_REF="v\d+\.\d+\.\d+"', ci_text), "Expected ACTIONLINT_REF with semantic version pattern"
    assert "ACTIONLINT_VERSION=\"${ACTIONLINT_REF#v}\"" in ci_text
    assert "rhysd/actionlint/${ACTIONLINT_REF}" in ci_text
    assert "download-actionlint.bash" in ci_text
    assert "bash /tmp/download-actionlint.bash \"${ACTIONLINT_VERSION}\"" in ci_text
    assert "${HOME}/.local/bin" in ci_text
    assert "actionlint" in ci_text
    assert "rhysd/actionlint/main" not in ci_text


def test_compose_exposes_image_override_env_vars() -> None:
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "${OPSRADAR_BACKEND_IMAGE:-opsradar-backend:local}" in compose_text
    assert "${OPSRADAR_FRONTEND_IMAGE:-opsradar-frontend:local}" in compose_text
    assert "OPSRADAR_BACKEND_IMAGE=" in env_text
    assert "OPSRADAR_FRONTEND_IMAGE=" in env_text


# ---------------------------------------------------------------------------
# Tests for _on_config() helper (new in this PR)
# ---------------------------------------------------------------------------


def test_on_config_returns_value_for_string_on_key() -> None:
    """_on_config should return workflow['on'] when the key is the string 'on'."""
    workflow = {"on": {"push": {"branches": ["main"]}}, "jobs": {}}
    result = _on_config(workflow)
    assert result == {"push": {"branches": ["main"]}}


def test_on_config_returns_value_for_boolean_true_key() -> None:
    """_on_config should fall back to workflow[True] when PyYAML parses 'on' as True."""
    workflow = {True: {"push": {"branches": ["develop"]}}, "jobs": {}}
    result = _on_config(workflow)
    assert result == {"push": {"branches": ["develop"]}}


def test_on_config_prefers_string_key_over_boolean_key() -> None:
    """String 'on' key takes precedence over boolean True key."""
    workflow = {
        "on": {"push": {"branches": ["main"]}},
        True: {"push": {"branches": ["other"]}},
        "jobs": {},
    }
    result = _on_config(workflow)
    assert result["push"]["branches"] == ["main"]


def test_on_config_raises_key_error_when_neither_key_present() -> None:
    """_on_config raises KeyError if neither 'on' nor True key is present."""
    workflow = {"jobs": {}}
    with pytest.raises(KeyError):
        _on_config(workflow)


# ---------------------------------------------------------------------------
# Tests for CI workflow changes (new in this PR)
# ---------------------------------------------------------------------------


def test_ci_push_trigger_includes_features_wildcard_branch() -> None:
    """CI should trigger on push to features/** branches (added in this PR)."""
    ci = _load_yaml(".github/workflows/ci.yml")
    on_config = _on_config(ci)

    push_branches = on_config["push"]["branches"]
    assert any("features" in b for b in push_branches), (
        "Expected a 'features/**' pattern in CI push branches"
    )
    assert "features/**" in push_branches


def test_ci_push_trigger_still_includes_main_and_develop() -> None:
    """Adding features/** must not drop the pre-existing main and develop triggers."""
    ci = _load_yaml(".github/workflows/ci.yml")
    on_config = _on_config(ci)

    push_branches = on_config["push"]["branches"]
    assert "main" in push_branches
    assert "develop" in push_branches


def test_ci_pr_trigger_does_not_include_features_branch() -> None:
    """PR trigger should only target main and develop, not features/**."""
    ci = _load_yaml(".github/workflows/ci.yml")
    on_config = _on_config(ci)

    pr_branches = on_config["pull_request"]["branches"]
    assert "main" in pr_branches
    assert "develop" in pr_branches
    assert not any("features" in b for b in pr_branches), (
        "features/** should not be in pull_request trigger branches"
    )


def test_ci_backend_job_sets_redis_url_env() -> None:
    """Backend job must declare REDIS_URL so SlowAPI uses in-process storage."""
    ci = _load_yaml(".github/workflows/ci.yml")
    backend_env = ci["jobs"]["backend"]["env"]
    assert "REDIS_URL" in backend_env


def test_ci_backend_job_redis_url_uses_memory_scheme() -> None:
    """REDIS_URL in the CI backend job must point to the in-memory backend."""
    ci = _load_yaml(".github/workflows/ci.yml")
    backend_env = ci["jobs"]["backend"]["env"]
    assert backend_env["REDIS_URL"] == "memory://"


def test_ci_actionlint_install_step_adds_to_github_path() -> None:
    """Install step must add the download directory to GITHUB_PATH so the binary is found."""
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "GITHUB_PATH" in ci_text


def test_ci_actionlint_install_step_uses_bash_shell() -> None:
    """Install step must specify bash shell for the process-substitution syntax."""
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "shell: bash" in ci_text


def test_ci_actionlint_download_script_url_is_present() -> None:
    """CI must reference the official actionlint download script URL."""
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "rhysd/actionlint" in ci_text
    assert "download-actionlint.bash" in ci_text


# ---------------------------------------------------------------------------
# Tests for backend/tests/conftest.py REDIS_URL change (new in this PR)
# ---------------------------------------------------------------------------


def test_ci_backend_job_also_sets_database_urls() -> None:
    """Regression: DATABASE_URL and SYNC_DATABASE_URL must still be present alongside REDIS_URL."""
    ci = _load_yaml(".github/workflows/ci.yml")
    backend_env = ci["jobs"]["backend"]["env"]
    assert "DATABASE_URL" in backend_env
    assert "SYNC_DATABASE_URL" in backend_env
    assert "SECRET_KEY" in backend_env


def test_ci_backend_job_env_database_url_uses_sqlite_aiosqlite() -> None:
    """Backend CI job must use the same in-memory SQLite URL as conftest.py defaults."""
    ci = _load_yaml(".github/workflows/ci.yml")
    backend_env = ci["jobs"]["backend"]["env"]
    assert backend_env["DATABASE_URL"] == "sqlite+aiosqlite:///:memory:"
    assert backend_env["SYNC_DATABASE_URL"] == "sqlite:///:memory:"
