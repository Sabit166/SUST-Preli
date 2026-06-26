"""QueueStorm Investigator AI agent.

Async entrypoint: `handle_ticket(ticket)` performs an optional Bangla/Banglish
translation pass before running the investigator prompt from
`system_prompt.py`. The agent itself is a single Groq chat completion call.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Provider selection. Defaults to Groq (already wired in run_agent_tests.py).
# Set LLM_PROVIDER=xai to route to xAI Grok instead — same code path.
# ---------------------------------------------------------------------------
try:
    from groq import AsyncGroq  # type: ignore
    _HAS_GROQ = True
except Exception:  # noqa: BLE001
    _HAS_GROQ = False

from system_prompt import System_Prompt
from translator import translation_prompt


# ---------------------------------------------------------------------------
# Environment / client
# ---------------------------------------------------------------------------

_ENV_LOADED = False


def _load_env() -> None:
    """Load the .env file once (no external dependency)."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    _ENV_LOADED = True


def _get_client():
    """Return an async chat-completions client.

    Provider is selected by env var `LLM_PROVIDER`:
      - "groq" (default): returns `groq.AsyncGroq` — needs `GROQ_API_KEY`.
      - "xai":   returns a tiny shim around xAI's [redacted]-compatible API,
                  needs `XAI_API_KEY`. Uses only `urllib` from stdlib so we
                  don't pull in a second SDK.

    Both clients expose the same `.chat.completions.create(...)` coroutine
    with the kwargs we use below, so the rest of agent.py is provider-agnostic.
    """
    _load_env()
    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "xai":
        return _XaiClient()

    if provider == "groq":
        if not _HAS_GROQ:
            raise RuntimeError(
                "groq SDK is not installed. Run: pip install groq"
            )
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
        return AsyncGroq(api_key=api_key)

    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'groq' or 'xai'."
    )


def _get_model() -> str:
    _load_env()
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "xai":
        return os.getenv("model_name") or os.getenv("MODEL") or "grok-2"
    return os.getenv("model_name") or os.getenv("MODEL") or "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# xAI (Grok) — minimal async client over their [redacted]-compatible API.
# We avoid adding the `xai` SDK so the dependency surface stays small.
# ---------------------------------------------------------------------------

class _XaiChatCompletions:
    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> "_XaiChatResponse":
        import urllib.request

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # xAI accepts response_format={"type":"json_object"} the same way.
        if response_format:
            body["response_format"] = response_format

        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        loop = asyncio.get_running_loop()

        def _do_request() -> str:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")

        raw = await loop.run_in_executor(None, _do_request)
        parsed = json.loads(raw)
        return _XaiChatResponse(parsed)


class _XaiChatResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    @property
    def choices(self) -> list["_XaiChoice"]:
        return [_XaiChoice(c) for c in self._payload.get("choices", [])]


class _XaiChoice:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.message = _XaiMessage(payload.get("message", {}))


class _XaiMessage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = payload.get("content", "") or ""


class _XaiClient:
    """xAI Grok client with the same surface as `groq.AsyncGroq`."""

    def __init__(self) -> None:
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY is not set. Add it to your .env file.")
        base_url = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
        self.chat = type("Chat", (), {"completions": _XaiChatCompletions(api_key, base_url)})()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_OUTPUT_FIELDS = (
    "ticket_id",
    "relevant_transaction_id",
    "evidence_verdict",
    "case_type",
    "severity",
    "department",
    "agent_summary",
    "recommended_next_action",
    "customer_reply",
    "human_review_required",
)

ALLOWED_CASE_TYPES = {
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
}

ALLOWED_SEVERITY = {"low", "medium", "high", "critical"}
ALLOWED_DEPARTMENT = {
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
}
ALLOWED_VERDICT = {"consistent", "inconsistent", "insufficient_data"}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    return False


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM response."""
    if not text:
        return {}

    # Strip markdown fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        candidate = text

    # Try a direct parse first, then fall back to the first {...} span.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    return {}


def _coerce_result(result: dict[str, Any], ticket_id: str) -> dict[str, Any]:
    """Normalise LLM output to the schema documented in system_prompt.py."""
    case_type = result.get("case_type")
    if case_type not in ALLOWED_CASE_TYPES:
        case_type = "other"

    severity = result.get("severity")
    if severity not in ALLOWED_SEVERITY:
        severity = "medium"

    department = result.get("department")
    if department not in ALLOWED_DEPARTMENT:
        department = "customer_support"

    verdict = result.get("evidence_verdict")
    if verdict not in ALLOWED_VERDICT:
        verdict = "insufficient_data"

    relevant_tx = result.get("relevant_transaction_id")
    if isinstance(relevant_tx, str):
        relevant_tx = relevant_tx.strip()
        if not relevant_tx or relevant_tx.lower() in {"null", "none"}:
            relevant_tx = None
    else:
        relevant_tx = None

    confidence = _coerce_confidence(result.get("confidence", 0.0))
    human_review = _coerce_bool(result.get("human_review_required", False))

    # Safety rule: low confidence forces escalation.
    if confidence < 0.7:
        human_review = True

    reason_codes = result.get("reason_codes") or []
    if not isinstance(reason_codes, list):
        reason_codes = [str(reason_codes)]
    reason_codes = [str(code) for code in reason_codes if code]

    return {
        "ticket_id": ticket_id,
        "relevant_transaction_id": relevant_tx,
        "evidence_verdict": verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": str(result.get("agent_summary") or "").strip(),
        "recommended_next_action": str(result.get("recommended_next_action") or "").strip(),
        "customer_reply": str(result.get("customer_reply") or "").strip(),
        "human_review_required": human_review,
        "confidence": round(confidence, 4),
        "reason_codes": reason_codes,
    }


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------


async def _translate_complaint(complaint: str, model: str) -> str:
    """Translate a Bangla / Banglish / mixed complaint into English."""
    if not complaint:
        return complaint

    client = _get_client()
    user_prompt = translation_prompt.format(complaint=complaint)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You translate user text faithfully."},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=512,
    )
    translated = (response.choices[0].message.content or "").strip()
    return translated or complaint


async def _run_investigator(ticket: dict[str, Any], model: str) -> dict[str, Any]:
    """Single-shot investigator call using the system prompt."""
    client = _get_client()

    user_payload = json.dumps(ticket, ensure_ascii=False)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": System_Prompt},
            {"role": "user", "content": user_payload},
        ],
        temperature=0.1,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    parsed = _extract_json(raw)
    return parsed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def handle_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    """Analyse a support ticket and return a structured response dict."""
    if not isinstance(ticket, dict):
        raise TypeError("ticket must be a dict")

    ticket_id = str(ticket.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("ticket.ticket_id is required")

    complaint = ticket.get("complaint") or ""
    language = str(ticket.get("language") or "en").strip().lower()

    model = _get_model()

    # Step 1: translate if needed (separate LLM call).
    if language in {"bn", "mixed"} and complaint.strip():
        try:
            translated = await _translate_complaint(complaint, model)
        except Exception:
            # Translation is best-effort; fall back to the original text.
            translated = complaint
        ticket_for_agent = {**ticket, "complaint": translated, "_original_complaint": complaint}
    else:
        ticket_for_agent = {**ticket}

    # Step 2: run the investigator agent with (English) complaint.
    raw_result = await _run_investigator(ticket_for_agent, model)
    return _coerce_result(raw_result, ticket_id)


# ---------------------------------------------------------------------------
# Optional CLI for quick local testing
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the investigator on a sample case.")
    parser.add_argument("--case", default="SAMPLE-01", help="Case id inside SUST_Preli_Sample_Cases.json")
    parser.add_argument("--file", default="SUST_Preli_Sample_Cases.json")
    args = parser.parse_args()

    cases_path = Path(__file__).resolve().parent / args.file
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    case = next(c for c in data["cases"] if c["id"] == args.case)

    result = asyncio.run(handle_ticket(case["input"]))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _cli()
