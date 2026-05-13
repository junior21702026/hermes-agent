from __future__ import annotations

import json
from typing import Any

from .discord_out import make_discord_sender
from .obsidian import ObsidianWriter


def render_discord_card(extraction: dict[str, Any], short: bool = False, mode: str | None = None, topic: str | None = None) -> str:
    if short:
        return f"**{extraction.get('creator_name', extraction.get('creator_id'))}: {extraction.get('title')}**\nScore {extraction.get('score')} — {extraction.get('url')}\n{'; '.join(extraction.get('score_reasons', [])[:2])}"
    mode = mode or "full"
    if mode == "topic" and topic:
        return render_topic_card(extraction, topic)
    if mode == "intelligence":
        return render_intelligence_card(extraction)
    return render_full_learning_card(extraction)


def render_full_learning_card(extraction: dict[str, Any]) -> str:
    topics = ", ".join(extraction.get("topics", [])) or "none"
    lines = [
        f"**{extraction.get('title')}**",
        f"Creator: {extraction.get('creator_name', extraction.get('creator_id'))}",
        f"Score: {extraction.get('score')} | Topics: {topics}",
        str(extraction.get("url")),
        "",
        "**Core learnings**",
        *bullet_lines(extraction.get("tldr"), limit=3),
    ]
    lines += section_lines("Workflows to copy", format_workflow, extraction.get("workflows"), limit=2)
    lines += section_lines("Small-business automations", format_automation, extraction.get("automations_for_small_business"), limit=2)
    lines += section_lines("Tools / stack", format_tool, extraction.get("tools_models_stacks"), limit=4)
    lines += section_lines("Prompts / patterns", format_pattern, extraction.get("prompts_and_patterns"), limit=2)
    lines += section_lines("Hermes follow-ups", format_idea, extraction.get("hermes_openclaw_codex_ideas"), limit=2)
    return trim_card("\n".join(lines))


def render_intelligence_card(extraction: dict[str, Any]) -> str:
    lines = [
        f"**Learning extracted: {extraction.get('title')}**",
        f"{extraction.get('creator_name', extraction.get('creator_id'))} | Score {extraction.get('score')} | {extraction.get('url')}",
        "",
        "**Why it matters**",
        *bullet_lines(extraction.get("tldr"), limit=2),
    ]
    lines += section_lines("Copyable workflows", format_workflow_compact, extraction.get("workflows"), limit=2)
    lines += section_lines("Follow-up actions", format_idea, extraction.get("hermes_openclaw_codex_ideas"), limit=2)
    return trim_card("\n".join(lines))


def render_topic_card(extraction: dict[str, Any], topic: str) -> str:
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
        if not body:
            body = ["**Signal vs hype**", f"- {extraction.get('hype_vs_actionable', 'mixed')}: {extraction.get('low_signal_reason') or 'No claim details extracted.'}"]
    else:
        body = ["**Core learnings**", *bullet_lines(extraction.get("tldr"), limit=3)]
    return trim_card("\n".join(header + body))


def bullet_lines(items: Any, *, limit: int) -> list[str]:
    values = normalize_items(items)[:limit]
    return [f"- {format_scalar(v)}" for v in values] or ["- None extracted."]


def section_lines(title: str, formatter, items: Any, *, limit: int) -> list[str]:
    values = normalize_items(items)[:limit]
    if not values:
        return []
    return ["", f"**{title}**", *[f"- {formatter(v)}" for v in values]]


def normalize_items(items: Any) -> list[Any]:
    if not items:
        return []
    if isinstance(items, list):
        return items
    return [items]


def format_scalar(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items() if v)
    return str(value)


def format_workflow(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    title = item.get("title") or "Workflow"
    stack = item.get("stack") or []
    steps = item.get("steps") or []
    step_text = " → ".join(str(s) for s in steps[:4])
    stack_text = f" Stack: {', '.join(map(str, stack[:5]))}." if stack else ""
    return f"**{title}** — {step_text}.{stack_text}".replace("..", ".")


def format_workflow_compact(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    steps = item.get("steps") or []
    return f"**{item.get('title', 'Workflow')}** — {len(steps)} steps; difficulty: {item.get('copy_difficulty', 'unknown')}"


def format_automation(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    tools = item.get("tools") or []
    return f"**{item.get('use_case', 'Automation')}** — trigger: {item.get('trigger', 'unknown')}; tools: {', '.join(map(str, tools[:5]))}; value: {item.get('estimated_value', 'unknown')}"


def format_tool(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    return f"**{item.get('name', 'Tool')}** — {item.get('role', 'mentioned')}"


def format_pattern(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    name = item.get("name") or item.get("pattern") or "Pattern"
    snippet = item.get("snippet") or item.get("instruction") or item.get("description") or ""
    return f"**{name}** — {snippet}"


def format_idea(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    name = item.get("name") or item.get("title") or "Follow-up"
    kind = item.get("kind") or "idea"
    rationale = item.get("rationale") or item.get("why") or item.get("description") or ""
    return f"**{kind}: {name}** — {rationale}"


def format_claim(item: Any) -> str:
    if not isinstance(item, dict):
        return format_scalar(item)
    claim = item.get("claim") or item.get("text") or json.dumps(item, ensure_ascii=False)
    status = item.get("status") or item.get("confidence") or "unverified"
    return f"{claim} ({status})"


def trim_card(content: str, limit: int = 1900) -> str:
    if len(content) <= limit:
        return content
    return content[: limit - 14].rstrip() + "\n… truncated"


def route_plan(extraction: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    score = float(extraction.get("score") or 0)
    creator = next((c for c in config.get("creators", []) if c["id"] == extraction.get("creator_id")), {})
    thresholds = config.get("scoring", {}).get("thresholds", {})
    archive_t = float(thresholds.get("obsidian_and_discord", 8))
    short_t = float(thresholds.get("discord_short", 6))
    sinks: list[dict[str, Any]] = []
    if score >= archive_t:
        sinks.append({"type": "discord", "target": creator.get("discord_channel", "ai-research"), "mode": "full"})
        sinks.append({"type": "discord", "target": config["intelligence_channels"]["primary"], "mode": "intelligence"})
        for topic in extraction.get("topics", []):
            if topic == "hype" and extraction.get("hype_vs_actionable") == "hype":
                target = config["intelligence_channels"]["topics"].get("hype")
            else:
                target = config["intelligence_channels"]["topics"].get(topic)
            if target:
                sinks.append({"type": "discord", "target": target, "mode": "topic", "topic": topic})
        sinks.append({"type": "obsidian", "target": "vault", "mode": "full"})
    elif score >= short_t:
        sinks.append({"type": "discord", "target": creator.get("discord_channel", "ai-research"), "mode": "short"})
    return sinks


def route_extraction(extraction: dict[str, Any], config: dict[str, Any], *, dry_run: bool = False, logger=print) -> dict[str, Any]:
    sinks = route_plan(extraction, config)
    discord = make_discord_sender(config, dry_run=dry_run, logger=logger)
    obsidian = ObsidianWriter(config, dry_run=dry_run)
    messages: list[dict[str, Any]] = []
    note_path: str | None = None
    for sink in sinks:
        if sink["type"] == "discord":
            messages.append(discord.send(sink["target"], render_discord_card(extraction, short=sink.get("mode") == "short", mode=sink.get("mode"), topic=sink.get("topic"))))
        elif sink["type"] == "obsidian":
            note_path = obsidian.write_video(extraction)
    return {"sinks": sinks, "discord_messages": messages, "obsidian_note_path": note_path}
