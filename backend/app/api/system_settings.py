"""System settings API — admin-only configuration that outlives
process restarts and survives environment-variable changes.

The main surface today is the LLM provider configuration so an
operator can paste an OpenRouter / Anthropic / OpenAI API key into
the Settings page without editing ``.env`` and restarting the
backend. The stored value is Fernet-encrypted at rest and is never
returned in plaintext — responses that reference the API key carry
only a boolean ``has_api_key`` flag so a curl user can't trivially
exfiltrate the key through ``GET``.

This module also exposes ``GET /system-settings/health`` — a
richer admin-facing diagnostic that complements the operator-only
``/health/ready`` liveness probe by reporting on encryption,
LLM-provider, SMTP, and upload-dir state too.
"""

from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.config import settings
from app.database import get_db
from app.models import User
from app.services import llm, system_settings as settings_service

logger = logging.getLogger(__name__)

router = APIRouter()

OPSRADAR_DEFAULT_ROLE_BLUEPRINTS = [
    {
        "id": "super_admin",
        "name": "Super Admin",
        "description": "Full workspace control across users, intake, workflows, and audit.",
        "role_type": "system",
        "permissions": [
            "manage_users",
            "manage_roles",
            "manage_sources",
            "manage_integrations",
            "manage_workflow_templates",
            "publish_workflow_templates",
            "view_all_requests",
            "view_audit_logs",
            "export_audit_logs",
            "override_workflow",
            "manage_policy_rules",
            "view_policy_decisions",
        ],
        "scopes": {"workspace": "all"},
        "allowed_request_types": ["*"],
        "allowed_resources": ["*"],
        "approval_authority": ["all"],
        "audit_visibility": "all",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "it_admin",
        "name": "IT Admin",
        "description": "Runs access-oriented workflows and executes IT-managed actions.",
        "role_type": "system",
        "permissions": [
            "manage_sources",
            "manage_workflow_templates",
            "view_assigned_approvals",
            "approve_request",
            "reject_request",
            "request_more_info",
            "execute_access_grant",
            "view_audit_logs",
        ],
        "scopes": {"owner_team": ["IT"]},
        "allowed_request_types": ["access_request", "software_license_request"],
        "allowed_resources": ["Figma", "GitHub", "Jira", "Okta"],
        "approval_authority": ["it_managed_resources"],
        "audit_visibility": "it",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "manager",
        "name": "Manager",
        "description": "Approves requests raised by direct reports and tracks team delays.",
        "role_type": "system",
        "permissions": [
            "view_team_requests",
            "view_assigned_approvals",
            "approve_request",
            "reject_request",
            "request_more_info",
            "escalate_request",
        ],
        "scopes": {"relationship": ["direct_reports"]},
        "allowed_request_types": ["access_request", "jira_project_creation", "vendor_review"],
        "allowed_resources": [],
        "approval_authority": ["team_requests"],
        "audit_visibility": "team",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "approver",
        "name": "Approver",
        "description": "Handles assigned approvals for selected request types or resources.",
        "role_type": "system",
        "permissions": [
            "view_assigned_approvals",
            "approve_request",
            "reject_request",
            "request_more_info",
        ],
        "scopes": {},
        "allowed_request_types": ["access_request"],
        "allowed_resources": [],
        "approval_authority": ["assigned_only"],
        "audit_visibility": "assigned",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "requester",
        "name": "Requester",
        "description": "Submits and tracks requests.",
        "role_type": "system",
        "permissions": ["submit_request", "view_own_requests"],
        "scopes": {"relationship": ["self"]},
        "allowed_request_types": ["access_request", "jira_project_creation", "vendor_review"],
        "allowed_resources": [],
        "approval_authority": [],
        "audit_visibility": "self",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "auditor",
        "name": "Auditor",
        "description": "Read-only access to approvals, policy decisions, and audit history.",
        "role_type": "system",
        "permissions": ["view_audit_logs", "export_audit_logs", "view_policy_decisions"],
        "scopes": {},
        "allowed_request_types": ["*"],
        "allowed_resources": ["*"],
        "approval_authority": [],
        "audit_visibility": "all",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "workflow_designer",
        "name": "Workflow Designer",
        "description": "Creates and maintains request workflows without managing users.",
        "role_type": "system",
        "permissions": [
            "manage_workflow_templates",
            "publish_workflow_templates",
            "manage_policy_rules",
        ],
        "scopes": {},
        "allowed_request_types": ["*"],
        "allowed_resources": [],
        "approval_authority": [],
        "audit_visibility": "assigned",
        "is_system": True,
        "disabled": False,
    },
    {
        "id": "security_reviewer",
        "name": "Security Reviewer",
        "description": "Reviews high-risk access and sensitive resource requests.",
        "role_type": "system",
        "permissions": [
            "view_assigned_approvals",
            "approve_request",
            "reject_request",
            "request_more_info",
            "view_audit_logs",
        ],
        "scopes": {"resource_sensitivity": ["high"]},
        "allowed_request_types": ["access_request", "production_access_request"],
        "allowed_resources": ["ProductionDB", "AdminAccess"],
        "approval_authority": ["high_risk_requests"],
        "audit_visibility": "security",
        "is_system": True,
        "disabled": False,
    },
]


# ── Request / response schemas ───────────────────────────────────────


class LLMConfigResponse(BaseModel):
    """Current effective LLM config, exposing only booleans for the
    sensitive fields so a curl-to-JSON pipeline can't steal the key.

    ``source`` reports *where* each field's value is coming from —
    either ``"db"`` (set via the Settings UI), ``"env"`` (read from
    the backend's environment variables), or ``"unset"``.
    """

    provider: str
    provider_source: str
    model: str
    model_source: str
    base_url: str | None = None
    base_url_source: str
    has_api_key: bool
    api_key_source: str
    # Last 4 characters of the API key when set, so the operator
    # can tell at a glance whether they're looking at the right
    # key without actually leaking it.
    api_key_preview: str | None = None
    is_configured: bool


class LLMConfigUpdate(BaseModel):
    """Batch update for the LLM configuration.

    Every field is optional. Pass only what you want to change.
    Pass ``api_key=""`` (empty string) to CLEAR a stored key —
    omit the field entirely to leave it as-is.
    """

    provider: str | None = Field(
        None,
        description="One of anthropic | openai | openai_compatible | openrouter | ollama | null",
        pattern=r"^(anthropic|openai|openai_compatible|openrouter|ollama|null)$",
    )
    model: str | None = Field(
        None,
        description="Provider-specific model identifier.",
        max_length=256,
    )
    base_url: str | None = Field(
        None,
        description="Optional base URL for openai-compatible endpoints. Empty string clears the stored value.",
        max_length=2048,
    )
    api_key: str | None = Field(
        None,
        description="Raw API key. Empty string clears the stored key.",
        max_length=2048,
    )


class OpsRadarRoleBlueprint(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    role_type: str = Field(default="custom", pattern=r"^(system|custom)$")
    permissions: list[str] = Field(default_factory=list)
    scopes: dict = Field(default_factory=dict)
    allowed_request_types: list[str] = Field(default_factory=list)
    allowed_resources: list[str] = Field(default_factory=list)
    approval_authority: list[str] = Field(default_factory=list)
    audit_visibility: str = Field(default="assigned", max_length=64)
    is_system: bool = False
    disabled: bool = False


class OpsRadarRoleBlueprintsResponse(BaseModel):
    roles: list[OpsRadarRoleBlueprint]


class OpsRadarRoleBlueprintsUpdate(BaseModel):
    roles: list[OpsRadarRoleBlueprint]


# ── Helpers ──────────────────────────────────────────────────────────


def _source_for(setting_key: str, env_key: str) -> str:
    """Return ``"db"`` / ``"env"`` / ``"unset"`` for a given setting."""
    import os as _os

    db_val = settings_service.get_setting(setting_key)
    if db_val:
        return "db"
    if _os.getenv(env_key, "").strip():
        return "env"
    return "unset"


def _current_llm_response() -> LLMConfigResponse:
    """Build the current-config response WITHOUT exposing the key."""
    provider = llm._provider()
    model = llm._model(provider)
    base_url = llm._base_url(provider) or None
    api_key = llm._api_key(provider)

    # Provider-specific env var for source attribution.
    env_key_map = {
        "anthropic": ("ANTHROPIC_MODEL", "ANTHROPIC_API_KEY"),
        "openai": ("OPENAI_MODEL", "OPENAI_API_KEY"),
        "openai_compatible": ("OPENAI_MODEL", "OPENAI_API_KEY"),
        "openrouter": ("OPENROUTER_MODEL", "OPENROUTER_API_KEY"),
        "ollama": ("OLLAMA_MODEL", ""),
        "null": ("", ""),
    }
    model_env, api_env = env_key_map.get(provider, ("", ""))

    preview = None
    if api_key:
        # Show last 4 characters prefixed with a gap so the operator
        # can match it against their provider dashboard without
        # exposing enough to be useful to an attacker.
        preview = f"…{api_key[-4:]}" if len(api_key) >= 4 else "…"

    return LLMConfigResponse(
        provider=provider,
        provider_source=_source_for("llm.provider", "OPS_RADAR_LLM_PROVIDER")
        if os.getenv("OPS_RADAR_LLM_PROVIDER", "").strip()
        else _source_for("llm.provider", "FLOWMINER_LLM_PROVIDER"),
        model=model,
        model_source=_source_for("llm.model", model_env) if model_env else "unset",
        base_url=base_url,
        base_url_source=_source_for("llm.base_url", "OPENAI_BASE_URL")
        if provider in {"openai", "openai_compatible"}
        else "unset",
        has_api_key=bool(api_key),
        api_key_source=_source_for("llm.api_key", api_env) if api_env else "unset",
        api_key_preview=preview,
        is_configured=llm.is_llm_configured(),
    )


def _current_opsradar_role_blueprints() -> OpsRadarRoleBlueprintsResponse:
    raw = settings_service.get_setting("opsradar.role_blueprints")
    if raw is None:
        raw = settings_service.get_setting("flowfix.role_blueprints")
    if isinstance(raw, dict) and isinstance(raw.get("roles"), list):
        roles = raw["roles"]
    elif isinstance(raw, list):
        roles = raw
    else:
        roles = OPSRADAR_DEFAULT_ROLE_BLUEPRINTS
    return OpsRadarRoleBlueprintsResponse(
        roles=[OpsRadarRoleBlueprint.model_validate(role) for role in roles]
    )


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config(
    _admin: User = Depends(require_admin),
) -> LLMConfigResponse:
    """Return the current LLM configuration.

    Admin-only — the response only contains booleans and a last-4
    preview for the key, but it still reveals which provider is
    configured which we don't want to broadcast to non-admins.
    """
    return _current_llm_response()


@router.put("/llm", response_model=LLMConfigResponse)
async def update_llm_config(
    body: LLMConfigUpdate,
    admin: User = Depends(require_admin),
) -> LLMConfigResponse:
    """Batch-update the LLM configuration.

    Every field is independently optional. Passing an empty string
    for ``api_key`` CLEARS the stored key; omitting the field
    entirely leaves it alone.

    Changes take effect immediately — the in-process cache in
    ``system_settings`` is invalidated on write.
    """
    # Explicit-None detection (Pydantic coerces missing → None, so we
    # can't distinguish "clear" from "don't touch" without a sentinel).
    # The convention here: None = don't touch, empty string = clear.
    fields_set = body.model_fields_set  # which fields the client actually sent

    if "provider" in fields_set:
        settings_service.set_setting(
            "llm.provider",
            body.provider,  # None clears
            user_id=admin.id,
        )
    if "model" in fields_set:
        settings_service.set_setting(
            "llm.model",
            body.model,  # None clears
            user_id=admin.id,
        )
    if "base_url" in fields_set:
        cleared = not body.base_url
        settings_service.set_setting(
            "llm.base_url",
            None if cleared else body.base_url,
            user_id=admin.id,
        )
    if "api_key" in fields_set:
        # Empty string and None both clear; any other string sets.
        cleared = not body.api_key
        settings_service.set_setting(
            "llm.api_key",
            None if cleared else body.api_key,
            user_id=admin.id,
        )
        logger.info(
            "LLM api_key %s by user id=%s",
            "cleared" if cleared else "updated",
            admin.id,
        )

    # Fall through to return the now-updated effective config.
    return _current_llm_response()


@router.get("/opsradar/roles", response_model=OpsRadarRoleBlueprintsResponse)
async def get_opsradar_role_blueprints(
    _admin: User = Depends(require_admin),
) -> OpsRadarRoleBlueprintsResponse:
    """Return OpsRadar role blueprints for the role builder UI."""
    return _current_opsradar_role_blueprints()


@router.put("/opsradar/roles", response_model=OpsRadarRoleBlueprintsResponse)
async def update_opsradar_role_blueprints(
    body: OpsRadarRoleBlueprintsUpdate,
    admin: User = Depends(require_admin),
) -> OpsRadarRoleBlueprintsResponse:
    """Persist OpsRadar role blueprints in encrypted system settings."""
    payload = {"roles": [role.model_dump() for role in body.roles]}
    settings_service.set_setting(
        "opsradar.role_blueprints",
        payload,
        user_id=admin.id,
    )
    settings_service.set_setting(
        "flowfix.role_blueprints",
        payload,
        user_id=admin.id,
    )
    logger.info("OpsRadar role blueprints updated by user id=%s", admin.id)
    return _current_opsradar_role_blueprints()


@router.get("/flowfix/roles", response_model=OpsRadarRoleBlueprintsResponse)
async def get_flowfix_role_blueprints_alias(
    _admin: User = Depends(require_admin),
) -> OpsRadarRoleBlueprintsResponse:
    return _current_opsradar_role_blueprints()


@router.put("/flowfix/roles", response_model=OpsRadarRoleBlueprintsResponse)
async def update_flowfix_role_blueprints_alias(
    body: OpsRadarRoleBlueprintsUpdate,
    admin: User = Depends(require_admin),
) -> OpsRadarRoleBlueprintsResponse:
    return await update_opsradar_role_blueprints(body, admin)


# ── System health (admin-only diagnostics) ───────────────────────────


class ComponentStatus(BaseModel):
    """Per-component status entry. ``ok`` is the boolean status; ``detail``
    carries a human-readable explanation (configured source, error
    message, etc.). The endpoint never includes secrets in ``detail`` —
    just enough to tell the operator what to fix."""

    ok: bool
    detail: str


class SystemHealthResponse(BaseModel):
    """Aggregated system-health snapshot — same shape as the corresponding
    TS interface in the frontend client."""

    database: ComponentStatus
    redis: ComponentStatus
    encryption: ComponentStatus
    temporal: ComponentStatus
    llm_provider: ComponentStatus
    smtp: ComponentStatus
    upload_dir: ComponentStatus


def _truncate_error(exc: Exception) -> str:
    """Cap exception messages so a verbose stack-string doesn't blow up
    the JSON payload or leak internals beyond what's useful."""
    return str(exc)[:200]


async def _check_database(db: AsyncSession) -> ComponentStatus:
    try:
        await db.execute(text("SELECT 1"))
        return ComponentStatus(ok=True, detail="connected")
    except Exception as exc:  # pragma: no cover — defensive
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


def _check_redis() -> ComponentStatus:
    try:
        import redis as _redis

        client = _redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_timeout=2
        )
        client.ping()
        return ComponentStatus(ok=True, detail="connected")
    except Exception as exc:
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


def _check_encryption() -> ComponentStatus:
    """Report which encryption-key source is in effect.

    A dedicated ``OPS_RADAR_ENCRYPTION_KEY`` is preferred because it
    decouples connector-credential decryption from JWT signing —
    rotating ``SECRET_KEY`` won't silently invalidate stored secrets.
    Fallback to the SECRET_KEY-derived key is still ``ok=True`` (it
    works) but the detail string warns about the rotation footgun.
    """
    try:
        # Re-import in case the secret_box module has been reloaded.
        from app.services import secret_box as _secret_box  # noqa: F401

        dedicated = os.getenv("OPS_RADAR_ENCRYPTION_KEY", "").strip()
        legacy = os.getenv("FLOWMINER_ENCRYPTION_KEY", "").strip()
        if dedicated:
            return ComponentStatus(
                ok=True,
                detail="dedicated key configured (OPS_RADAR_ENCRYPTION_KEY)",
            )
        if legacy:
            return ComponentStatus(
                ok=True,
                detail="legacy key configured (FLOWMINER_ENCRYPTION_KEY)",
            )
        # If we got here, secret_box derived a key from SECRET_KEY.
        # The module logs a warning when no key is available at all;
        # surface that case as not-ok so the admin sees it.
        if _secret_box._FERNET is None:
            return ComponentStatus(
                ok=False,
                detail="no encryption key available — set OPS_RADAR_ENCRYPTION_KEY or SECRET_KEY",
            )
        return ComponentStatus(
            ok=True,
            detail=(
                "derived from SECRET_KEY (rotating SECRET_KEY will invalidate "
                "stored secrets)"
            ),
        )
    except Exception as exc:
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


def _check_temporal() -> ComponentStatus:
    """Probe the configured Temporal address without requiring the SDK.

    The backend and worker already know how to speak Temporal if the
    socket is reachable. This admin health check just gives the operator
    a quick connected/not-connected indicator.
    """
    try:
        address = (
            settings.TEMPORAL_ADDRESS.strip()
            or getattr(settings, "TEMPORAL_SERVER_URL", "").strip()
            or os.getenv("TEMPORAL_SERVER_URL", "").strip()
        )
        if not address:
            return ComponentStatus(ok=False, detail="not configured")

        host = address
        port = 7233
        if "://" in address:
            parsed = urlparse(address)
            host = parsed.hostname or host
            port = parsed.port or 7233
        elif ":" in address:
            maybe_host, maybe_port = address.rsplit(":", 1)
            if maybe_port.isdigit():
                host, port = maybe_host, int(maybe_port)

        with socket.create_connection((host, port), timeout=2):
            return ComponentStatus(ok=True, detail=f"connected to {host}:{port}")
    except Exception as exc:
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


def _check_llm_provider() -> ComponentStatus:
    """Report on the effective LLM provider configuration.

    Uses the same resolution helpers as ``GET /system-settings/llm`` so
    the two endpoints can never disagree. Crucially, the api-key
    *value* is never included in the response — only its presence and
    source.
    """
    try:
        cfg = _current_llm_response()
        provider = cfg.provider
        # Translate the source codes to a one-line phrase.
        source_phrase = {
            "db": "configured via Settings UI",
            "env": "configured via env var",
            "unset": "not set",
        }
        if provider == "null":
            return ComponentStatus(
                ok=True,
                detail="null — fallback (templated responses, no real LLM)",
            )
        if provider == "ollama":
            # Ollama doesn't need an api key; provider source is what matters.
            return ComponentStatus(
                ok=True,
                detail=(
                    f"ollama — {source_phrase.get(cfg.provider_source, 'unknown source')}"
                ),
            )
        # Hosted providers — needs a key to be considered ok.
        if cfg.has_api_key:
            return ComponentStatus(
                ok=True,
                detail=(
                    f"{provider} — "
                    f"{source_phrase.get(cfg.api_key_source, 'configured')}"
                ),
            )
        return ComponentStatus(
            ok=False,
            detail=f"{provider} — no API key set",
        )
    except Exception as exc:
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


def _check_smtp() -> ComponentStatus:
    """SMTP is optional — empty SMTP_HOST is reported as ok-but-disabled
    rather than an error, since email alerts are an opt-in feature."""
    try:
        host = (settings.SMTP_HOST or "").strip()
        if not host:
            return ComponentStatus(
                ok=True,
                detail="disabled (no SMTP_HOST configured)",
            )
        return ComponentStatus(
            ok=True,
            detail=f"configured: {host}:{settings.SMTP_PORT}",
        )
    except Exception as exc:
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


def _check_upload_dir() -> ComponentStatus:
    try:
        path = settings.UPLOAD_DIR
        if not path:
            return ComponentStatus(ok=False, detail="UPLOAD_DIR is empty")
        if not os.path.isdir(path):
            return ComponentStatus(ok=False, detail=f"{path} (does not exist)")
        if not os.access(path, os.W_OK):
            return ComponentStatus(ok=False, detail=f"{path} (not writable)")
        return ComponentStatus(ok=True, detail=path)
    except Exception as exc:
        return ComponentStatus(ok=False, detail=_truncate_error(exc))


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> SystemHealthResponse:
    """Admin-facing system-health snapshot.

    Distinct from ``/health/ready`` (the operator/k8s liveness probe)
    in two ways: it is auth-gated to admins, and it covers the full
    operator-relevant surface (encryption, LLM provider, SMTP,
    upload-dir) on top of the DB/Redis pair.

    Each component is checked independently and any failure is
    captured as ``ok=False`` with the truncated error message — one
    broken dependency must not 500 the whole endpoint, otherwise the
    page becomes unusable in exactly the deployment where it matters
    most.
    """
    return SystemHealthResponse(
        database=await _check_database(db),
        redis=_check_redis(),
        encryption=_check_encryption(),
        temporal=_check_temporal(),
        llm_provider=_check_llm_provider(),
        smtp=_check_smtp(),
        upload_dir=_check_upload_dir(),
    )
