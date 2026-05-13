from __future__ import annotations

import json
import re
from typing import Any

from .discord_out import make_discord_sender
from .obsidian import ObsidianWriter
from .text_quality import card_footer, collapse_blank_lines, friendly_kind, is_placeholder, normalize_hermes_terms

_EMPTY_LABEL_RE = re.compile(r"^\*\*[^*]+\*\* —\s*$")


def _term_map(extraction: dict[str, Any]) -> dict[str, str]:
    return ((extraction.get("config") or {}).get("discord") or {}).get("term_normalization") or {}


def render_discord_card(extraction: dict[str, Any], short: bool = False, mode: str | None = None, topic: str | None = None) -> str | None:
    if short:
        text = f"**{extraction.get('creator_name', extraction.get('creator_id'))}: {extraction.get('title')}**\nScore {extraction.get('score')} — {extraction.get('url')}\n{'; '.join(extraction.get('score_reasons', [])[:2])}"
        return normalize_hermes_terms(text, _term_map(extraction))
    mode = mode or "full"
    if mode == "topic" and topic:
        return render_topic_card(extraction, topic)
    if mode == "intelligence":
        return render_intelligence_card(extraction)
    return render_full_learning_card(extraction)


def _finish_card(lines: list[str], extraction: dict[str, Any], *, header_count: int) -> str | None:
    norm = [normalize_hermes_terms(line, _term_map(extraction)) for line in lines]
    while norm and norm[-1] == "":
        norm.pop()
    body = norm[header_count:]
    if not any(line.startswith("- ") for line in body):
        return None
    text = collapse_blank_lines("\n".join(norm))
    footer = card_footer(extraction)
    if footer:
        text = f"{text}\n{footer}" if text else footer
    return trim_card(text)


def render_full_learning_card(extraction: dict[str, Any]) -> str | None:
    topics = ", ".join(extraction.get("topics", [])) or "none"
    lines = [
        f"**{extraction.get('title')}**",
        f"Creator: {extraction.get('creator_name', extraction.get('creator_id'))}",
        f"Score: {extraction.get('score')} | Topics: {topics}",
        str(extraction.get("url")),
        "",
    ]
    core = bullet_lines(extraction.get("tldr"), limit=3)
    if core:
        lines += ["**Core learnings**", *core]
    lines += section_lines("Workflows to copy", format_workflow, extraction.get("workflows"), limit=2)
    lines += section_lines("Small-business automations", format_automation, extraction.get("automations_for_small_business"), limit=2)
    lines += section_lines("Tools / stack", format_tool, extraction.get("tools_models_stacks"), limit=4)
    lines += section_lines("Prompts / patterns", format_pattern, extraction.get("prompts_and_patterns"), limit=2)
    lines += section_lines("Hermes follow-ups", format_idea, extraction.get("hermes_openclaw_codex_ideas"), limit=2)
    return _finish_card(lines, extraction, header_count=5)


def render_intelligence_card(extraction: dict[str, Any]) -> str | None:
    lines = [
        f"**Learning extracted: {extraction.get('title')}**",
        f"{extraction.get('creator_name', extraction.get('creator_id'))} | Score {extraction.get('score')} | {extraction.get('url')}",
        "",
    ]
    why = bullet_lines(extraction.get("tldr"), limit=2)
    if why:
        lines += ["**Why it matters**", *why]
    lines += section_lines("Copyable workflows", format_workflow_compact, extraction.get("workflows"), limit=2)
    lines += section_lines("Follow-up actions", format_idea, extraction.get("hermes_openclaw_codex_ideas"), limit=2)
    return _finish_card(lines, extraction, header_count=3)


def _has_claims(extraction: dict[str, Any]) -> bool:
    return bool([c for c in normalize_items(extraction.get("claims")) if not is_placeholder(format_claim(c))])


def render_topic_card(extraction: dict[str, Any], topic: str) -> str | None:
    if topic == "hype" and extraction.get("hype_vs_actionable") != "hype" and not _has_claims(extraction):
        return None
    title = f"**{topic.replace('_', ' ').title()}: {extraction.get('title')}**"
    header = [title, f"{extraction.get('creator_name', extraction.get('creator_id'))} | Score {extraction.get('score')} | {extraction.get('url')}", ""]
    if topic == "automation_ideas":
        body = section_lines("Automations", format_automation, extraction.get("automations_for_small_business"), limit=4)
    elif topic == "workflows":
        body = section_lines("Workflows", format_workflow, extraction.get("workflows"), limit=3)
    elif topic == "skills_to_build":
        body = section_lines("Skills / Hermes follow-ups", format_idea, extraction.get("hermes_openclaw_codex_ideas"), limit=4)
    elif topic == "tool_stack":
        body = section_lines("Tools / stack", format_tool, extraction.get("tools_models_stacks"), limit=8)
    elif topic == "hype":
        body = section_lines("Signal vs hype", format_claim, extraction.get("claims"), limit=4)
        if not body and extraction.get("hype_vs_actionable") == "hype":
            reason = extraction.get("low_signal_reason")
            body = ["**Signal vs hype**", f"- hype: {reason}"] if not is_placeholder(reason) else []
    else:
        bullets = bullet_lines(extraction.get("tldr"), limit=3)
        body = ["**Core learnings**", *bullets] if bullets else []
    if not body:
        return None
    return _finish_card(header + body, extraction, header_count=3)


def bullet_lines(items: Any, *, limit: int) -> list[str]:
    lines: list[str] = []
    for value in normalize_items(items):
        text = format_scalar(value).strip()
        if is_placeholder(text):
            continue
        lines.append(f"- {text}")
        if len(lines) >= limit:
            break
    return lines


def section_lines(title: str, formatter, items: Any, *, limit: int) -> list[str]:
    formatted: list[str] = []
    for value in normalize_items(items):
        text = str(formatter(value) or "").strip()
        if is_placeholder(text) or _EMPTY_LABEL_RE.match(text):
            continue
        formatted.append(f"- {text}")
        if len(formatted) >= limit:
            break
    if not formatted:
        return []
    return ["", f"**{title}**", *formatted]


def normalize_items(items: Any) -> list[Any]:
    if not items:
        return []
    if isinstance(items, list):
        return items
    return [items]


def format_scalar(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items() if v)
    return str(value or "")


def format_workflow(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    title = item.get("title") or "Workflow"
    stack = [str(s) for s in (item.get("stack") or []) if not is_placeholder(s)]
    steps = [str(s) for s in (item.get("steps") or []) if not is_placeholder(s)]
    if not steps and not stack:
        return ""
    if steps:
        step_text = " → ".join(steps[:4])
        stack_text = f" Stack: {', '.join(stack[:5])}." if stack else ""
        return f"**{title}** — {step_text}.{stack_text}".replace("..", ".")
    return f"**{title}** — Stack: {', '.join(stack[:5])}"


def format_workflow_compact(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    steps = [s for s in (item.get("steps") or []) if not is_placeholder(s)]
    stack = [s for s in (item.get("stack") or []) if not is_placeholder(s)]
    if not steps and not stack:
        return ""
    return f"**{item.get('title', 'Workflow')}** — {len(steps)} steps; difficulty: {item.get('copy_difficulty', 'unknown')}"


def format_automation(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    use_case = item.get("use_case") or ""
    trigger = item.get("trigger") or ""
    tools = [str(t) for t in (item.get("tools") or []) if not is_placeholder(t)]
    value = item.get("estimated_value") or ""
    if is_placeholder(use_case) and is_placeholder(trigger) and not tools:
        return ""
    use_case = "Automation" if is_placeholder(use_case) else str(use_case).replace("unknown", "unspecified")
    trigger = "unspecified" if is_placeholder(trigger) else str(trigger).replace("unknown", "unspecified")
    value = "unspecified" if is_placeholder(value) else str(value).replace("unknown", "unspecified")
    return f"**{use_case}** — trigger: {trigger}; tools: {', '.join(tools[:5]) or 'unspecified'}; value: {value}"


def format_tool(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    name = item.get("name") or ""
    if is_placeholder(name):
        return ""
    role = item.get("role") or ""
    return f"**{name}**" if is_placeholder(role) else f"**{name}** — {role}"


def format_pattern(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    name = item.get("name") or item.get("pattern") or "Pattern"
    snippet = item.get("snippet") or item.get("instruction") or item.get("description") or ""
    if is_placeholder(snippet):
        return ""
    return f"**{name}** — {snippet}"


def format_idea(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    name = item.get("name") or item.get("title") or ""
    rationale = item.get("rationale") or item.get("why") or item.get("description") or ""
    if is_placeholder(name) and is_placeholder(rationale):
        return ""
    label = friendly_kind(item.get("kind") or "idea")
    heading = f"**{label}: {name or 'Follow-up'}**"
    return heading if is_placeholder(rationale) else f"{heading} — {rationale}"


def format_claim(item: Any) -> str:
    if not isinstance(item, dict):
        return normalize_hermes_terms(format_scalar(item))
    claim = item.get("claim") or item.get("text") or json.dumps(item, ensure_ascii=False)
    status = item.get("status") or item.get("confidence") or "unverified"
    return normalize_hermes_terms(f"{claim} ({status})")


def trim_card(content: str, limit: int = 1900) -> str:
    if len(content) <= limit:
        return content
    return content[: limit - 14].rstrip() + "\n… truncated"


def _bullet_set(card: str | None) -> set[str]:
    if not card:
        return set()
    return {re.sub(r"\s+", " ", line.strip()) for line in card.splitlines() if line.startswith("- ")}


def route_plan(extraction: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    score = float(extraction.get("score") or 0)
    creator = next((c for c in config.get("creators", []) if c["id"] == extraction.get("creator_id")), {})
    thresholds = config.get("scoring", {}).get("thresholds", {})
    archive_t = float(thresholds.get("obsidian_and_discord", 8))
    short_t = float(thresholds.get("discord_short", 6))
    sinks: list[dict[str, Any]] = []
    extraction_for_render = {**extraction, "config": config}
    if score >= archive_t:
        full_card = render_full_learning_card(extraction_for_render)
        intel_card = render_intelligence_card(extraction_for_render)
        if full_card:
            sinks.append({"type": "discord", "target": creator.get("discord_channel", "ai-research"), "mode": "full"})
        if intel_card:
            sinks.append({"type": "discord", "target": config["intelligence_channels"]["primary"], "mode": "intelligence"})
        intel_bullets = _bullet_set(intel_card)
        viable_topics: list[tuple[int, int, dict[str, Any]]] = []
        for idx, topic in enumerate(extraction.get("topics", [])):
            if topic == "hype" and extraction.get("hype_vs_actionable") != "hype" and not _has_claims(extraction):
                continue
            target = config["intelligence_channels"]["topics"].get(topic)
            if not target:
                continue
            card = render_topic_card(extraction_for_render, topic)
            if not card:
                continue
            bullets = _bullet_set(card)
            if bullets and bullets == intel_bullets:
                continue
            if bullets and bullets < intel_bullets and len(bullets) <= 1:
                continue
            unique_count = len(bullets - intel_bullets) or len(bullets)
            viable_topics.append((-unique_count, idx, {"type": "discord", "target": target, "mode": "topic", "topic": topic}))
        max_topics = int(config.get("discord", {}).get("max_topic_channels_per_post", 3))
        for _, _, sink in sorted(viable_topics)[:max_topics]:
            sinks.append(sink)
        if full_card:
            sinks.append({"type": "obsidian", "target": "vault", "mode": "full"})
    elif score >= short_t:
        sinks.append({"type": "discord", "target": creator.get("discord_channel", "ai-research"), "mode": "short"})
    return sinks


def _log_debug(logger: Any, message: str, payload: dict[str, Any]) -> None:
    if hasattr(logger, "debug"):
        logger.debug(message, extra=payload)
    elif callable(logger):
        logger(f"{message}: {payload}")


def route_extraction(extraction: dict[str, Any], config: dict[str, Any], *, dry_run: bool = False, logger=print) -> dict[str, Any]:
    render_extraction = {**extraction, "config": config}
    planned = route_plan(render_extraction, config)
    discord = make_discord_sender(config, dry_run=dry_run, logger=logger)
    obsidian = ObsidianWriter(config, dry_run=dry_run)
    messages: list[dict[str, Any]] = []
    note_path: str | None = None
    delivered: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    thresholds = config.get("scoring", {}).get("thresholds", {})
    if not planned and float(extraction.get("score") or 0) >= float(thresholds.get("obsidian_and_discord", 8)):
        skipped.append({"type": "discord", "target": None, "reason": "empty_card"})
    for sink in planned:
        if sink["type"] == "discord":
            card = render_discord_card(render_extraction, short=sink.get("mode") == "short", mode=sink.get("mode"), topic=sink.get("topic"))
            if card is None:
                entry = {"type": sink["type"], "target": sink.get("target"), "reason": "empty_card"}
                skipped.append(entry)
                _log_debug(logger, "sink_skipped_empty", entry)
                continue
            messages.append(discord.send(sink["target"], card))
            delivered.append(sink)
        elif sink["type"] == "obsidian":
            note_path = obsidian.write_video(extraction)
            delivered.append(sink)
    # Observability for topic cap/hype skips not present in planned route.
    max_topics = int(config.get("discord", {}).get("max_topic_channels_per_post", 3))
    delivered_topics = {s.get("topic") for s in delivered if s.get("mode") == "topic"}
    viable_count = 0
    for topic in extraction.get("topics", []):
        if topic == "hype" and extraction.get("hype_vs_actionable") != "hype" and not _has_claims(extraction):
            skipped.append({"type": "discord", "target": config.get("intelligence_channels", {}).get("topics", {}).get(topic), "reason": "hype_no_evidence"})
            continue
        if topic in delivered_topics:
            viable_count += 1
            continue
        if config.get("intelligence_channels", {}).get("topics", {}).get(topic) and render_topic_card(render_extraction, topic):
            reason = "topic_cap" if viable_count >= max_topics else "empty_or_duplicate_topic"
            skipped.append({"type": "discord", "target": config["intelligence_channels"]["topics"].get(topic), "reason": reason})
            viable_count += 1
    return {"sinks": delivered, "skipped_sinks": skipped, "discord_messages": messages, "obsidian_note_path": note_path}
