from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent import handle_ticket


BASE_DIR = Path(__file__).resolve().parent
SUPPORTED_MODEL = "llama-3.3-70b-versatile"

os.environ["model_name"] = SUPPORTED_MODEL
os.environ["MODEL"] = SUPPORTED_MODEL


def _strip_json_comments(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = []
        in_string = False
        escaped = False
        i = 0
        while i < len(raw_line):
            char = raw_line[i]
            if in_string:
                line.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                i += 1
                continue

            if char == '"':
                in_string = True
                line.append(char)
                i += 1
                continue

            if char == '/' and i + 1 < len(raw_line) and raw_line[i + 1] == '/':
                break

            line.append(char)
            i += 1

        lines.append("".join(line))

    text = "\n".join(lines)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def load_test_cases(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    cleaned = _strip_json_comments(raw)
    payload = json.loads(cleaned)
    return payload["test_cases"]


def _contains_any(text: str, needles: list[str]) -> list[str]:
    lower_text = text.lower()
    return [needle for needle in needles if needle.lower() in lower_text]


def _check_expected(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []

    if "case_type" in expected and actual.get("case_type") != expected["case_type"]:
        failures.append(f"case_type expected {expected['case_type']!r} got {actual.get('case_type')!r}")

    if "case_type_one_of" in expected and actual.get("case_type") not in expected["case_type_one_of"]:
        failures.append(
            f"case_type expected one of {expected['case_type_one_of']!r} got {actual.get('case_type')!r}"
        )

    if "department" in expected and actual.get("department") != expected["department"]:
        failures.append(f"department expected {expected['department']!r} got {actual.get('department')!r}")

    if "department_one_of" in expected and actual.get("department") not in expected["department_one_of"]:
        failures.append(
            f"department expected one of {expected['department_one_of']!r} got {actual.get('department')!r}"
        )

    if "evidence_verdict" in expected and actual.get("evidence_verdict") != expected["evidence_verdict"]:
        failures.append(
            f"evidence_verdict expected {expected['evidence_verdict']!r} got {actual.get('evidence_verdict')!r}"
        )

    if "relevant_transaction_id" in expected and actual.get("relevant_transaction_id") != expected["relevant_transaction_id"]:
        failures.append(
            "relevant_transaction_id expected "
            f"{expected['relevant_transaction_id']!r} got {actual.get('relevant_transaction_id')!r}"
        )

    if "relevant_transaction_id_one_of" in expected and actual.get("relevant_transaction_id") not in expected["relevant_transaction_id_one_of"]:
        failures.append(
            "relevant_transaction_id expected one of "
            f"{expected['relevant_transaction_id_one_of']!r} got {actual.get('relevant_transaction_id')!r}"
        )

    if "human_review_required" in expected and bool(actual.get("human_review_required")) != bool(expected["human_review_required"]):
        failures.append(
            f"human_review_required expected {expected['human_review_required']!r} got {actual.get('human_review_required')!r}"
        )

    if "severity_one_of" in expected and actual.get("severity") not in expected["severity_one_of"]:
        failures.append(f"severity expected one of {expected['severity_one_of']!r} got {actual.get('severity')!r}")

    if "customer_reply_must_not_contain" in expected:
        matches = _contains_any(actual.get("customer_reply", ""), expected["customer_reply_must_not_contain"])
        if matches:
            failures.append(f"customer_reply contained disallowed phrases: {matches!r}")

    if "customer_reply_should_contain_tone" in expected:
        phrase = expected["customer_reply_should_contain_tone"]
        if phrase.lower() not in actual.get("customer_reply", "").lower():
            failures.append(f"customer_reply did not contain required phrase {phrase!r}")

    if "customer_reply_must_direct_to" in expected:
        phrase = expected["customer_reply_must_direct_to"]
        if phrase.lower() not in actual.get("customer_reply", "").lower():
            failures.append(f"customer_reply did not direct to {phrase!r}")

    return (not failures), failures


@dataclass
class FailureRecord:
    test_id: str
    label: str
    section: str
    expected_checks: dict[str, Any]
    actual_result: dict[str, Any]
    failed_checks: list[str]
    input: dict[str, Any]


async def run_tests() -> dict[str, Any]:
    cases = load_test_cases(BASE_DIR / "agent_test_cases.json")
    failed_cases: list[FailureRecord] = []

    for case in cases:
        test_id = str(case.get("test_id") or "")
        label = str(case.get("label") or "")
        section = str(case.get("section") or "")
        expected_checks = case.get("expected_checks") or {}
        ticket = case.get("input") or {}

        actual = await handle_ticket(ticket)
        passed, failures = _check_expected(actual, expected_checks)
        if not passed:
            failed_cases.append(
                FailureRecord(
                    test_id=test_id,
                    label=label,
                    section=section,
                    expected_checks=expected_checks,
                    actual_result=actual,
                    failed_checks=failures,
                    input=ticket,
                )
            )

    return {
        "_meta": {
            "source": "agent_test_cases.json",
            "total_cases": len(cases),
            "failed_cases": len(failed_cases),
        },
        "failed_cases": [record.__dict__ for record in failed_cases],
    }


def main() -> None:
    result = asyncio.run(run_tests())
    output_path = BASE_DIR / "failed_cases.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["_meta"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()