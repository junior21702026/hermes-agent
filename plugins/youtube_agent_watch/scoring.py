from __future__ import annotations

from typing import Any


def clamp(value: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def score_extraction(extraction: dict[str, Any], config: dict[str, Any], *, transcript_missing: bool = False, creator_weight: float = 1.0) -> dict[str, Any]:
    topics = set(extraction.get("topics", []))
    base = 4.0
    reasons: list[str] = []
    if extraction.get("workflows"):
        base += 2.0
        reasons.append("Contains a workflow/pattern that can be reviewed for copying.")
    if extraction.get("automations_for_small_business"):
        base += 1.5
        reasons.append("Contains small-business automation signal.")
    if extraction.get("hermes_openclaw_codex_ideas"):
        base += 1.0
        reasons.append("Mentions Hermes/Claude Code/Codex-style implementation ideas.")
    if extraction.get("tools_models_stacks"):
        base += 0.8
        reasons.append("Names tools/models/stacks explicitly.")
    if "hype" in topics and extraction.get("hype_vs_actionable") == "hype":
        base -= 1.5
        reasons.append("Hype-heavy relative to actionable details.")
    if not reasons:
        reasons.append("Low operational signal in transcript/metadata.")

    weights = config.get("scoring", {}).get("weights", {})
    signals = {
        "workflow_explicit": 1 if extraction.get("workflows") else 0,
        "automation_actionable": 1 if extraction.get("automations_for_small_business") else 0,
        "hermes_or_claude_code_pattern": 1 if extraction.get("hermes_openclaw_codex_ideas") else 0,
        "tool_stack_clarity": 1 if extraction.get("tools_models_stacks") else 0,
        "novelty_vs_known": 0.5 if topics else 0,
        "hype_penalty": 1 if extraction.get("hype_vs_actionable") == "hype" else 0,
    }
    adjustment = sum(float(weights.get(k, 0)) * v for k, v in signals.items())
    final = clamp(round(base + adjustment, 1))
    if transcript_missing:
        final = min(final, 5.0)
        reasons.append("Transcript missing/too short; score capped at 5.")
    duration = extraction.get("duration_s") or 0
    if duration and duration < 300:
        final = min(final, 7.0)
        reasons.append("Short duration; score capped at 7 unless manually reviewed.")
    if creator_weight < 0.8:
        final = round(final * 0.95, 1)
    return {
        "score": final,
        "score_breakdown": signals,
        "score_reasons": reasons[:3],
        "topics": sorted(topics),
        "hype_vs_actionable": extraction.get("hype_vs_actionable", "unknown"),
        "score_band": score_band(final, config),
    }


def score_band(score: float, config: dict[str, Any]) -> str:
    thresholds = config.get("scoring", {}).get("thresholds", {})
    if score >= float(thresholds.get("obsidian_and_discord", 8)):
        return "archive"
    if score >= float(thresholds.get("discord_short", 6)):
        return "short"
    if score <= float(thresholds.get("seen_only_max", 5)):
        return "seen"
    return "below"
