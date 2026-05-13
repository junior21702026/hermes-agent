from __future__ import annotations

from typing import Any


def clamp(value: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def _items(value: Any) -> list[Any]:
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_claims(extraction: dict[str, Any]) -> bool:
    for claim in _items(extraction.get("claims")):
        if isinstance(claim, dict):
            text = claim.get("claim") or claim.get("text")
        else:
            text = claim
        if _text(text).lower() not in {"", "none", "n/a", "unknown", "tbd", "—", "-"}:
            return True
    return False


def _substantial_cfg(config: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "workflow_min_steps": 3,
        "workflow_alt_steps_with_stack": 2,
        "workflow_alt_min_stack": 2,
        "automation_requires_value": True,
        "hermes_idea_min_rationale_chars": 40,
        "tool_stack_min_named": 2,
        "pattern_min_snippet_chars": 30,
    }
    defaults.update(config.get("scoring", {}).get("substantial", {}) or {})
    return defaults


def has_substantial_workflow(extraction: dict[str, Any], config: dict[str, Any]) -> bool:
    cfg = _substantial_cfg(config)
    for workflow in _items(extraction.get("workflows")):
        if not isinstance(workflow, dict):
            continue
        steps = [s for s in _items(workflow.get("steps")) if _text(s)]
        stack = [s for s in _items(workflow.get("stack")) if _text(s)]
        if len(steps) >= int(cfg["workflow_min_steps"]):
            return True
        if len(steps) >= int(cfg["workflow_alt_steps_with_stack"]) and len(stack) >= int(cfg["workflow_alt_min_stack"]):
            return True
    return False


def has_substantial_automation(extraction: dict[str, Any], config: dict[str, Any]) -> bool:
    cfg = _substantial_cfg(config)
    for automation in _items(extraction.get("automations_for_small_business")):
        if not isinstance(automation, dict):
            continue
        use_case = _text(automation.get("use_case"))
        trigger = _text(automation.get("trigger"))
        tools = [t for t in _items(automation.get("tools")) if _text(t)]
        value = _text(automation.get("estimated_value"))
        if use_case and (trigger or tools) and (value or not cfg.get("automation_requires_value", True)):
            return True
    return False


def has_substantial_hermes_idea(extraction: dict[str, Any], config: dict[str, Any]) -> bool:
    min_chars = int(_substantial_cfg(config)["hermes_idea_min_rationale_chars"])
    for idea in _items(extraction.get("hermes_openclaw_codex_ideas")):
        if isinstance(idea, dict):
            rationale = idea.get("rationale") or idea.get("why") or idea.get("description")
        else:
            rationale = idea
        if len(_text(rationale)) >= min_chars:
            return True
    return False


def has_substantial_tool_stack(extraction: dict[str, Any], config: dict[str, Any]) -> bool:
    min_named = int(_substantial_cfg(config)["tool_stack_min_named"])
    named: set[str] = set()
    for tool in _items(extraction.get("tools_models_stacks")):
        if not isinstance(tool, dict):
            continue
        name = _text(tool.get("name"))
        role = _text(tool.get("role"))
        if name and role:
            named.add(name.lower())
    return len(named) >= min_named


def has_substantial_pattern(extraction: dict[str, Any], config: dict[str, Any]) -> bool:
    min_chars = int(_substantial_cfg(config)["pattern_min_snippet_chars"])
    for pattern in _items(extraction.get("prompts_and_patterns")):
        if isinstance(pattern, dict):
            snippet = pattern.get("snippet") or pattern.get("instruction") or pattern.get("description")
        else:
            snippet = pattern
        if len(_text(snippet)) >= min_chars:
            return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _limited_reasons(signals: list[str], penalties: list[str], caps: list[str]) -> list[str]:
    ordered = _dedupe(signals + penalties)
    cap_reasons = _dedupe(caps)
    room = max(0, 4 - len(cap_reasons))
    result = ordered[:room] + cap_reasons
    return result or ["Low operational signal in transcript/metadata."]


def score_extraction(extraction: dict[str, Any], config: dict[str, Any], *, transcript_missing: bool = False, creator_weight: float = 1.0) -> dict[str, Any]:
    topics = set(extraction.get("topics", []))
    base = 3.0
    signal_reasons: list[str] = []
    penalty_reasons: list[str] = []
    cap_reasons: list[str] = []
    caps_applied: list[str] = []

    score_inputs = {
        "substantial_workflow": has_substantial_workflow(extraction, config),
        "substantial_automation": has_substantial_automation(extraction, config),
        "substantial_hermes_idea": has_substantial_hermes_idea(extraction, config),
        "substantial_tool_stack": has_substantial_tool_stack(extraction, config),
        "substantial_pattern": has_substantial_pattern(extraction, config),
    }
    if score_inputs["substantial_workflow"]:
        base += 1.5
        signal_reasons.append("Contains a substantial workflow/pattern that can be reviewed for copying.")
    if score_inputs["substantial_automation"]:
        base += 1.2
        signal_reasons.append("Contains actionable small-business automation signal.")
    if score_inputs["substantial_hermes_idea"]:
        base += 0.8
        signal_reasons.append("Includes a developed Hermes/Claude Code/Codex implementation idea.")
    if score_inputs["substantial_tool_stack"]:
        base += 0.5
        signal_reasons.append("Names a clear multi-tool stack with roles.")
    if score_inputs["substantial_pattern"]:
        base += 0.5
        signal_reasons.append("Includes a concrete prompt/pattern snippet.")
    if extraction.get("hype_vs_actionable") == "hype":
        base -= 1.5
        penalty_reasons.append("Hype-heavy relative to actionable details.")
    if topics == {"hype"}:
        base -= 0.5
        penalty_reasons.append("Only hype topic identified.")

    weights = config.get("scoring", {}).get("weights", {})
    signals = {
        "workflow_explicit": 1 if score_inputs["substantial_workflow"] else 0,
        "automation_actionable": 1 if score_inputs["substantial_automation"] else 0,
        "hermes_or_claude_code_pattern": 1 if score_inputs["substantial_hermes_idea"] else 0,
        "tool_stack_clarity": 1 if score_inputs["substantial_tool_stack"] else 0,
        "novelty_vs_known": 0.5 if topics else 0,
        "hype_penalty": 1 if extraction.get("hype_vs_actionable") == "hype" else 0,
    }
    adjustment = sum(float(weights.get(k, 0)) * v for k, v in signals.items())
    base += min(1.0, adjustment)
    final = clamp(base)
    if (
        score_inputs["substantial_workflow"]
        and score_inputs["substantial_automation"]
        and score_inputs["substantial_hermes_idea"]
        and score_inputs["substantial_tool_stack"]
        and extraction.get("hype_vs_actionable") != "hype"
    ):
        final = max(final, 8.0)

    caps_cfg = {
        "unverified_stub_with_claims": 8.5,
        "unverified_stub_no_claims": 9.0,
        "not_run_with_unverified_claims": 9.0,
        "non_perfect_unless_multi_signal": 9.7,
    }
    caps_cfg.update(config.get("scoring", {}).get("caps", {}) or {})

    if transcript_missing:
        final = min(final, 5.0)
        caps_applied.append("transcript_missing")
        cap_reasons.append("Transcript missing/too short; score capped at 5.")
    duration = extraction.get("duration_s") or 0
    if duration and duration < 300:
        final = min(final, 7.0)
        caps_applied.append("short_duration")
        cap_reasons.append("Short duration; score capped at 7 unless manually reviewed.")

    confidence = _text((extraction.get("verification") or {}).get("confidence"))
    has_claims = _has_claims(extraction)
    if confidence == "unverified_stub" and has_claims:
        final = min(final, float(caps_cfg["unverified_stub_with_claims"]))
        caps_applied.append("unverified_stub_with_claims")
        cap_reasons.append("Researcher verification pending; capped at 8.5.")
    elif confidence == "unverified_stub":
        final = min(final, float(caps_cfg["unverified_stub_no_claims"]))
        caps_applied.append("unverified_stub_no_claims")
        cap_reasons.append("Researcher verification pending; capped at 9.0.")
    elif confidence == "not_run" and has_claims:
        final = min(final, float(caps_cfg["not_run_with_unverified_claims"]))
        caps_applied.append("not_run_with_unverified_claims")
        cap_reasons.append("Claims need verification before a perfect score; capped at 9.0.")

    perfect_eligible = (
        sum(1 for k in ["substantial_workflow", "substantial_automation", "substantial_hermes_idea", "substantial_tool_stack"] if score_inputs[k]) >= 3
        and confidence in {"verified", "not_run", ""}
        and not (confidence == "not_run" and has_claims)
        and confidence != "unverified_stub"
        and not transcript_missing
        and (not duration or duration >= 300)
    )
    if not perfect_eligible:
        final = min(final, float(caps_cfg["non_perfect_unless_multi_signal"]))
        if final >= float(caps_cfg["non_perfect_unless_multi_signal"]):
            caps_applied.append("non_perfect_unless_multi_signal")
            cap_reasons.append("Perfect score reserved for high-confidence multi-signal items.")

    if creator_weight < 0.8:
        final = final * 0.95

    final = clamp(round(final, 1))
    reasons = _limited_reasons(signal_reasons, penalty_reasons, cap_reasons)
    return {
        "score": final,
        "score_breakdown": signals,
        "score_reasons": reasons,
        "topics": sorted(topics),
        "hype_vs_actionable": extraction.get("hype_vs_actionable", "unknown"),
        "score_band": score_band(final, config),
        "score_caps_applied": _dedupe(caps_applied),
        "score_inputs": score_inputs,
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
