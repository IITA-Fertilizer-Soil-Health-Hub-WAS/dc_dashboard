"""Draft a form spec from a protocol/questionnaire using an LLM (Tier 3).

Given the plain text of a protocol, ask Claude to extract the questions,
answer types and constraints into the same spec the form builder + xlsform
generator consume. The variable names are nudged toward the Terminag vocabulary
so a draft is standardised where possible; whatever doesn't match is reported.

Gated + fail-soft: nothing runs unless ``FORM_AI_ENABLED`` and a key are set, and
any error raises ``FormAIError`` (the caller shows it, never crashes). The output
is always a *draft* for human review in the builder — it is never auto-published.
"""
from __future__ import annotations

import json
import re

import httpx
from django.conf import settings

from apps.vocabulary.models import VocabularyVariable

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_MAX_VOCAB_HINT = 250  # cap the vocabulary list we send to bound token use


class FormAIError(RuntimeError):
    """AI drafting failed or is unavailable."""


def is_enabled() -> bool:
    return bool(getattr(settings, "FORM_AI_ENABLED", False)
                and getattr(settings, "FORM_AI_API_KEY", ""))


def _vocab_hint() -> str:
    names = list(
        VocabularyVariable.objects.order_by("category", "name")
        .values_list("name", flat=True)[:_MAX_VOCAB_HINT]
    )
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
        raise FormAIError("AI drafting is off — set FORM_AI_API_KEY and FORM_AI_ENABLED.")
    text = (protocol_text or "").strip()
    if not text:
        raise FormAIError("The protocol is empty — nothing to draft from.")

    body = {
        "model": getattr(settings, "FORM_AI_MODEL", "claude-opus-4-8"),
        "max_tokens": 8000,
        "system": SYSTEM.replace("{vocab}", _vocab_hint()),
        "messages": [{"role": "user", "content": text[:60000]}],
    }
    headers = {
        "x-api-key": settings.FORM_AI_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(ANTHROPIC_URL, headers=headers, json=body)
    except Exception as exc:  # noqa: BLE001 — surface as a clean message
        raise FormAIError(f"Could not reach the AI service: {exc}")
    if resp.status_code != 200:
        raise FormAIError(f"AI service error (HTTP {resp.status_code}): {resp.text[:200]}")

    return _parse(resp.json())


def _parse(payload: dict) -> dict:
    """Extract the JSON spec from an Anthropic Messages API response."""
    try:
        blocks = payload.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    except (AttributeError, TypeError):
        raise FormAIError("Unexpected AI response shape.")
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
