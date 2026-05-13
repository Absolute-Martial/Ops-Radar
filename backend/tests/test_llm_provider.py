from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from app.services import llm


def test_openai_compatible_complete_uses_configured_base_url(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                    )
                )
            )

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI

    monkeypatch.setitem(sys.modules, "openai", fake_module)
    monkeypatch.setattr(llm, "_from_system_settings", lambda _key: None)
    monkeypatch.setenv("FLOWMINER_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.com/v1")

    assert llm.complete("system", "user") == "ok"
    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://llm.example.com/v1"


def test_openai_compatible_requires_base_url(monkeypatch):
    monkeypatch.setattr(llm, "_from_system_settings", lambda _key: None)
    monkeypatch.setenv("FLOWMINER_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    assert llm.is_llm_configured() is False
