from __future__ import annotations

from typing import Iterable

from app.api.system_settings import OPSRADAR_DEFAULT_ROLE_BLUEPRINTS
from app.config import settings
from app.models import OpRequest, User, UserRole
from app.services import system_settings as settings_service


def _request_type_matches(allowed: list[str], request_type: str) -> bool:
    if not allowed or "*" in allowed:
        return True
    return request_type in allowed


def _resource_matches(allowed: list[str], request_row: OpRequest) -> bool:
    if not allowed or "*" in allowed:
        return True
    values = {
        (request_row.resource_name or "").strip().lower(),
        (request_row.resource_key or "").strip().lower(),
    }
    return any(item.strip().lower() in values for item in allowed)


def current_opsradar_role_blueprints() -> list[dict]:
    raw = settings_service.get_setting("opsradar.role_blueprints")
    if raw is None:
        raw = settings_service.get_setting("flowfix.role_blueprints")
    if isinstance(raw, dict) and isinstance(raw.get("roles"), list):
        return raw["roles"]
    if isinstance(raw, list):
        return raw
    return OPSRADAR_DEFAULT_ROLE_BLUEPRINTS


def required_role_keys_for_request(request_row: OpRequest) -> list[str]:
    required: list[str] = []
    for blueprint in current_opsradar_role_blueprints():
        if blueprint.get("disabled"):
            continue
        permissions = blueprint.get("permissions") or []
        authorities = blueprint.get("approval_authority") or []
        if "approve_request" not in permissions and not authorities:
            continue
        if not _request_type_matches(blueprint.get("allowed_request_types") or [], request_row.request_type):
            continue

        role_key = str(blueprint.get("id") or "").strip()
        if not role_key or role_key == "super_admin":
            continue

        allowed_resources = blueprint.get("allowed_resources") or []
        scopes = blueprint.get("scopes") or {}
        matches = False
        for authority in authorities:
            if authority in {"all", "team_requests", "assigned_only"}:
                matches = True
            elif authority == "it_managed_resources":
                matches = _resource_matches(allowed_resources, request_row) or request_row.request_type in {
                    "access_request",
                    "production_access_request",
                    "software_license_request",
                }
            elif authority == "high_risk_requests":
                matches = request_row.risk_level == "high"
            if matches:
                break
        if not matches and scopes.get("resource_sensitivity") and request_row.risk_level in scopes.get("resource_sensitivity", []):
            matches = True
        if matches:
            required.append(role_key)

    if request_row.request_type in {"access_request", "production_access_request", "software_license_request"}:
        for fallback_role in ("manager", "it_admin"):
            if fallback_role not in required:
                required.append(fallback_role)
    if request_row.risk_level == "high" and "security_reviewer" not in required:
        required.append("security_reviewer")
    if not required:
        required.append("super_admin")
    return list(dict.fromkeys(required))


def _permission_policies_for_roles(required_roles: list[str]) -> list[tuple[str, str, str]]:
    policies: list[tuple[str, str, str]] = []
    for role_key in required_roles:
        policies.append((role_key, "op_request", "approve"))
        policies.append((role_key, "op_request", "request_more_info"))
    for role_key in {"it_admin", "super_admin"}:
        policies.append((role_key, "op_request", "fulfill"))
    policies.append(("requester", "op_request", "submit"))
    policies.append(("requester", "op_request", "provide_info"))
    return list(dict.fromkeys(policies))


def _can_with_casbin(subjects: Iterable[str], *, obj: str, act: str, policies: list[tuple[str, str, str]]) -> bool:
    try:
        import casbin
    except ImportError:
        return False

    model = casbin.Model()
    model.load_model_from_text(
        """
        [request_definition]
        r = sub, obj, act

        [policy_definition]
        p = sub, obj, act

        [role_definition]
        g = _, _

        [policy_effect]
        e = some(where (p.eft == allow))

        [matchers]
        m = (r.sub == p.sub || g(r.sub, p.sub)) && r.obj == p.obj && r.act == p.act
        """
    )
    enforcer = casbin.Enforcer(model)
    for sub, policy_obj, policy_act in policies:
        enforcer.add_policy(sub, policy_obj, policy_act)
    for subject in subjects:
        if enforcer.enforce(subject, obj, act):
            return True
    return False


def evaluate_request_policy(
    request_row: OpRequest,
    *,
    actor: User | None = None,
    actor_role_keys: list[str] | None = None,
) -> dict:
    required_roles = required_role_keys_for_request(request_row)
    reasons: list[str] = []
    access_level = (request_row.access_level or "").strip().lower()

    if access_level in {"admin", "owner", "super_admin"}:
        reasons.append("Admin-level access requires explicit approval.")
    if request_row.request_type in {"access_request", "production_access_request", "software_license_request"}:
        reasons.append("Software and production access must be routed to accountable approvers.")
    if request_row.risk_level == "high":
        reasons.append("High-risk requests require a security-aware review path.")
    if not reasons:
        reasons.append("Standard request routing requires at least one accountable approver.")

    actor_roles = actor_role_keys or []
    if actor and actor.id == request_row.requester_user_id:
        actor_roles = [*actor_roles, "requester"]
    policies = _permission_policies_for_roles(required_roles)
    allowed_actions: list[str] = []
    for action in ("submit", "approve", "request_more_info", "provide_info", "fulfill"):
        if _can_with_casbin(actor_roles, obj="op_request", act=action, policies=policies):
            allowed_actions.append(action)

    engine = settings.OPSRADAR_POLICY_ENGINE if settings.OPSRADAR_POLICY_ENGINE else "internal"
    return {
        "engine": engine,
        "policy_version": settings.OPSRADAR_POLICY_VERSION,
        "decision": "approval_required",
        "risk_level": request_row.risk_level,
        "required_roles": required_roles,
        "allowed_actions": allowed_actions,
        "reasons": reasons,
    }


def authorize_request_action(
    request_row: OpRequest,
    *,
    actor: User,
    actor_role_keys: list[str],
    action: str,
) -> dict:
    if actor.role == UserRole.admin:
        return {"allowed": True, "reason": "Global admin access", "matched_roles": ["admin"]}

    policy = evaluate_request_policy(request_row, actor=actor, actor_role_keys=actor_role_keys)
    matched_roles = list(actor_role_keys)
    if actor.id == request_row.requester_user_id:
        matched_roles.append("requester")

    allowed = _can_with_casbin(
        matched_roles,
        obj="op_request",
        act=action,
        policies=_permission_policies_for_roles(policy["required_roles"]),
    )
    if not allowed:
        required_roles = set(policy["required_roles"])
        actor_role_set = set(matched_roles)
        if action in {"approve", "request_more_info"}:
            allowed = bool(required_roles & actor_role_set)
        elif action == "fulfill":
            allowed = bool({"it_admin", "super_admin"} & actor_role_set)
        elif action in {"submit", "provide_info"}:
            allowed = "requester" in actor_role_set
    reason = (
        f"Authorized via roles: {', '.join(matched_roles)}"
        if allowed
        else f"Action '{action}' is not allowed for roles: {', '.join(matched_roles) or 'none'}"
    )
    return {"allowed": allowed, "reason": reason, "matched_roles": matched_roles, "policy": policy}
