from __future__ import annotations

from contextvars import ContextVar, Token

from app.models import User

_current_mcp_user: ContextVar[User | None] = ContextVar("current_mcp_user", default=None)


def set_current_mcp_user(user: User) -> Token:
    return _current_mcp_user.set(user)


def reset_current_mcp_user(token: Token) -> None:
    _current_mcp_user.reset(token)


def get_current_mcp_user() -> User | None:
    return _current_mcp_user.get()


def require_current_mcp_user() -> User:
    user = get_current_mcp_user()
    if user is None:
        raise RuntimeError("No authenticated OpsReader MCP user is bound to this request.")
    return user
