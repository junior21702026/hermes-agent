from __future__ import annotations

import re
from typing import Any

_PLACEHOLDERS = {"", "none", "n/a", "unknown", "tbd", "—", "-"}
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def is_placeholder(text: Any) -> bool:
    return str(text or "").strip().lower() in _PLACEHOLDERS


def _apply_replacements(segment: str, replacements: list[tuple[re.Pattern[str], str]]) -> str:
    out = segment
    for pattern, repl in replacements:
        out = pattern.sub(repl, out)
    return out


def normalize_hermes_terms(text: Any, extra_map: dict[str, str] | None = None) -> str:
    """Normalize common Hermes/OpenClaw terminology while leaving URLs untouched."""
    raw = str(text or "")
    replacements: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bKua\b"), "Cua"),
        (re.compile(r"\bkua-driver\b"), "cua-driver"),
        (re.compile(r"\bComputer Use\b"), "computer-use"),
        (re.compile(r"\bOpen Claw\b"), "OpenClaw"),
        (re.compile(r"\bopen[-_ ]?claw\b", re.IGNORECASE), "OpenClaw"),
        (re.compile(r"\bClaude code\b"), "Claude Code"),
        (re.compile(r"\bn 8 n\b|\bn-8-n\b", re.IGNORECASE), "n8n"),
        (re.compile(r"\bHermes Agent\b(?!\s+(?:plugin|repo)\b)"), "Hermes"),
    ]
    if extra_map:
        for src, dst in extra_map.items():
            if src:
                replacements.append((re.compile(rf"\b{re.escape(str(src))}\b"), str(dst)))

    parts: list[str] = []
    last = 0
    for match in _URL_RE.finditer(raw):
        parts.append(_apply_replacements(raw[last:match.start()], replacements))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_apply_replacements(raw[last:], replacements))
    return "".join(parts)


def collapse_blank_lines(text: str) -> str:
    stripped_lines = [line.rstrip() for line in str(text or "").splitlines()]
    collapsed = re.sub(r"\n\s*\n(?:\s*\n)+", "\n\n", "\n".join(stripped_lines))
    return collapsed.rstrip()


def friendly_kind(kind: Any) -> str:
    value = str(kind or "idea").strip()
    mapping = {
        "parallel": "Parallel pattern",
        "skill": "Skill",
        "agent": "Agent",
        "workflow": "Workflow",
        "prompt": "Prompt",
    }
    key = value.lower()
    return mapping.get(key, value.replace("_", " ").title() or "Idea")


def confidence_label(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "unverified_stub": "unverified (researcher pending)",
        "not_run": "not run",
        "verified": "verified by researcher",
    }
    return mapping.get(raw, "")


def transcript_source_label(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "unknown":
        return ""
    if raw == "whisper-fallback":
        return "whisper-fallback transcript"
    return raw


def card_footer(extraction: dict[str, Any]) -> str | None:
    source = transcript_source_label(extraction.get("transcript_source"))
    verification = confidence_label((extraction.get("verification") or {}).get("confidence"))
    parts: list[str] = []
    if source:
        parts.append(f"Source: {source}")
    if verification:
        parts.append(f"verification: {verification}")
    return f"_{' • '.join(parts)}_" if parts else None
