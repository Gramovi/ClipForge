"""Tolerant JSON extraction/repair for LLM output (especially small local models)."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_SMART = str.maketrans({"“": '"', "”": '"', "„": '"'})


class JSONRepairError(ValueError):
    pass


def _balanced_slice(text: str, start: int) -> str:
    """Return the text from *start* to its matching closing bracket (or to the end)."""
    stack: list[str] = []
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack and stack[-1] == ch:
            stack.pop()
            if not stack:
                return text[start : i + 1]
    return text[start:]


def _close_truncated(s: str) -> str:
    """Close an output truncated mid-way: drop the incomplete tail item and close brackets."""
    stack: list[str] = []
    in_str = False
    esc = False
    last_safe = 0  # index after last complete value at depth >= 1
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            last_safe = i + 1
    if not stack and not in_str:
        return s
    head = s[:last_safe].rstrip().rstrip(",")
    # recompute open brackets for the safe head
    stack = []
    in_str = False
    esc = False
    for ch in head:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return head + "".join(reversed(stack))


def _loads(s: str) -> Any:
    return json.loads(s, strict=False)  # strict=False tolerates raw newlines inside strings


def parse_json_loose(text: str) -> Any:
    """Parse JSON from arbitrary model text, repairing common defects."""
    if not text or not text.strip():
        raise JSONRepairError("prázdná odpověď")
    candidates: list[str] = []
    m = _FENCE.search(text)
    if m:
        candidates.append(m.group(1))
    candidates.append(text)
    last_err: Exception | None = None
    for cand in candidates:
        cand = cand.strip()
        idx = min([i for i in (cand.find("{"), cand.find("[")) if i >= 0], default=-1)
        if idx < 0:
            continue
        body = _balanced_slice(cand, idx)
        attempts = [
            body,
            _TRAILING_COMMA.sub(r"\1", body),
            _TRAILING_COMMA.sub(r"\1", body.translate(_SMART)),
            _close_truncated(_TRAILING_COMMA.sub(r"\1", body)),
        ]
        # python-literal style output: single quotes, True/False/None
        py = body.replace("True", "true").replace("False", "false").replace("None", "null")
        if "'" in py and '"' not in py:
            attempts.append(py.replace("'", '"'))
        for a in attempts:
            try:
                return _loads(a)
            except json.JSONDecodeError as e:
                last_err = e
    raise JSONRepairError(f"nevalidní JSON: {last_err}")
