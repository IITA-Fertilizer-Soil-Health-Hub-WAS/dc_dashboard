"""Draft a form spec from a protocol/questionnaire using an LLM (Tier 3).

Provider-agnostic: **Azure OpenAI** or **Anthropic Claude**, selected by
``FORM_AI_PROVIDER``. Given the plain text of a protocol, ask the model to
extract the questions, answer types and constraints into the same spec the form
builder + xlsform generator consume. Variable names are nudged toward the
Terminag vocabulary so a draft is standardised where possible.

Gated + fail-soft: nothing runs unless ``FORM_AI_ENABLED`` and the provider's
config are set, and any error raises ``FormAIError`` (the caller shows it, never
crashes). The output is always a *draft* for human review — never auto-published.
"""
from __future__ import annotations

import json
import re

import httpx
from django.conf import settings

from apps.vocabulary.models import VocabularyVariable

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_MAX_VOCAB_HINT = 250  # cap the vocabulary list we send to bound token use
_KNOWN_PROVIDERS = ("anthropic", "azure_openai")


class FormAIError(RuntimeError):
    """AI drafting failed or is unavailable."""


def _provider() -> str:
    return (getattr(settings, "FORM_AI_PROVIDER", "anthropic") or "anthropic").lower()


def is_enabled() -> bool:
    if not getattr(settings, "FORM_AI_ENABLED", False):
        return False
    provider = _provider()
    if provider == "azure_openai":
        return bool(getattr(settings, "AZURE_OPENAI_ENDPOINT", "")
                    and getattr(settings, "AZURE_OPENAI_API_KEY", "")
                    and getattr(settings, "AZURE_OPENAI_DEPLOYMENT", ""))
    if provider == "anthropic":
        return bool(getattr(settings, "FORM_AI_API_KEY", ""))
    # Unknown provider — treat as not configured rather than silently pretending
    # it's an Anthropic setup (which would fail confusingly at call time).
    return False


def _model_label() -> str:
    if _provider() == "azure_openai":
        return f"azure:{getattr(settings, 'AZURE_OPENAI_DEPLOYMENT', '')}"
    return getattr(settings, "FORM_AI_MODEL", "claude-opus-4-8")


def _call(system: str, user: str, *, max_tokens: int, json_mode: bool) -> str:
    """One system+user turn to the configured provider; returns the text output.
    Raises FormAIError on any transport/HTTP problem."""
    provider = _provider()
    if provider not in _KNOWN_PROVIDERS:
        raise FormAIError(
            f"Unknown FORM_AI_PROVIDER '{provider}' — set it to one of: "
            f"{', '.join(_KNOWN_PROVIDERS)}."
        )
    try:
        if provider == "azure_openai":
            base = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
            dep = settings.AZURE_OPENAI_DEPLOYMENT
            ver = getattr(settings, "AZURE_OPENAI_API_VERSION", "2024-10-21")
            url = f"{base}/openai/deployments/{dep}/chat/completions?api-version={ver}"
            body: dict = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            headers = {"api-key": settings.AZURE_OPENAI_API_KEY, "content-type": "application/json"}
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                raise FormAIError(f"AI service error (HTTP {resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            return (data["choices"][0]["message"]["content"] or "").strip()

        # default: Anthropic Claude (Messages API)
        body = {
            "model": _model_label(),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": settings.FORM_AI_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(ANTHROPIC_URL, headers=headers, json=body)
        if resp.status_code != 200:
            raise FormAIError(f"AI service error (HTTP {resp.status_code}): {resp.text[:200]}")
        blocks = resp.json().get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    except FormAIError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface as a clean message
        raise FormAIError(f"Could not reach the AI service: {exc}")


def _vocab_hint() -> str:
    # Best-effort: the vocabulary hint only improves mapping. A DB hiccup here
    # must not 500 the whole draft — fall back to no hint.
    try:
        names = list(
            VocabularyVariable.objects.order_by("category", "name")
            .values_list("name", flat=True)[:_MAX_VOCAB_HINT]
        )
    except Exception:  # noqa: BLE001 — hint is optional, never fatal
        return ""
    return ", ".join(names)


SYSTEM = (
    "You convert an agricultural field-research protocol or questionnaire into a "
    "digital data-collection form. Output ONLY a JSON object (no prose, no code "
    "fences) with this exact shape:\n"
    '{"settings": {"form_title": str}, '
    '"questions": [{"type": str, "name": str, "label": str, "required": bool, '
    '"list": str, "constraint": str}], '
    '"choices": {"<list_name>": [{"name": str, "label": str}]}}\n'
    "Rules: type is one of text, integer, decimal, select_one, select_multiple, "
    "date, time, geopoint, note. For select_one/select_multiple set 'list' to a "
    "choice-list name and define that list under 'choices'. 'name' must be a short "
    "snake_case identifier. Prefer these standard variable names where a question "
    "matches one (this is the Terminag vocabulary): {vocab}. Keep numeric ranges "
    "from the protocol as an ODK 'constraint' like '. >= 0 and . <= 100'. Include "
    "only questions the protocol actually asks."
)


def draft_spec(protocol_text: str) -> dict:
    """Call the LLM and return a validated spec dict. Raises FormAIError."""
    if not is_enabled():
        raise FormAIError("AI drafting is off — configure the provider and enable FORM_AI_ENABLED.")
    text = (protocol_text or "").strip()
    if not text:
        raise FormAIError("The protocol is empty — nothing to draft from.")
    system = SYSTEM.replace("{vocab}", _vocab_hint() or "(none available)")
    return _parse_spec(_call(system, text[:60000], max_tokens=8000, json_mode=True))


def check() -> dict:
    """A tiny live round-trip to confirm the config works, without drafting a
    whole form. Returns {ok, model, message}. Never raises."""
    model = _model_label()
    if not is_enabled():
        return {"ok": False, "model": model,
                "message": "Disabled — configure the provider and set FORM_AI_ENABLED."}
    try:
        _call("Reply with the single word: ok", "Are you reachable?",
              max_tokens=16, json_mode=False)
    except FormAIError as exc:
        return {"ok": False, "model": model, "message": str(exc)}
    return {"ok": True, "model": model, "message": "AI service reachable and the key works."}


def _parse_spec(text: str) -> dict:
    """Validate the model's text output into a spec dict."""
    text = _strip_fences(text).strip()
    if not text:
        raise FormAIError("The AI returned an empty draft.")
    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        raise FormAIError("The AI draft wasn't valid JSON — try again or build by hand.")
    if not isinstance(spec, dict) or not spec.get("questions"):
        raise FormAIError("The AI draft had no questions.")
    return spec


def _strip_fences(text: str) -> str:
    """Drop a leading ```json / ``` fence if the model wrapped its output."""
    m = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, flags=re.DOTALL)
    return m.group(1) if m else text
