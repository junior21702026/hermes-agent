from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

KEYWORDS = {
    "workflows": ["workflow", "step by step", "pipeline", "agent loop", "process"],
    "automation_ideas": ["automation", "automate", "zapier", "n8n", "make.com", "trigger"],
    "skills_to_build": ["claude code", "codex", "hermes", "skill", "tool call", "mcp"],
    "tool_stack": ["stack", "api", "model", "openai", "anthropic", "gemini", "cursor", "github"],
    "hype": ["insane", "shocking", "game changer", "you won't believe", "revolutionary"],
}

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "extract.md"
SCORE_FIELDS = {"score", "score_band", "score_reasons", "score_components"}
LIST_FIELDS = [
    "topics",
    "tldr",
    "workflows",
    "automations_for_small_business",
    "tools_models_stacks",
    "prompts_and_patterns",
    "hermes_openclaw_codex_ideas",
    "obsidian_targets",
    "claims",
]
ALLOWED_TOPICS = {"workflows", "automation_ideas", "skills_to_build", "tool_stack", "hype", "low_signal"}


def extract_operational_signal(video: dict[str, Any], transcript: str, config: dict[str, Any]) -> dict[str, Any]:
    """Extract operational learnings from a video.

    Safety/default behavior remains local heuristic extraction unless
    extraction.mode is explicitly set to "llm". LLM imports are lazy so normal
    healthchecks/tests do not require model/provider dependencies.
    """

    if config.get("extraction", {}).get("mode", "heuristic_stub") != "llm":
        return heuristic_extract_operational_signal(video, transcript, config)
    return extract_operational_signal_llm(video, transcript, config)


def heuristic_extract_operational_signal(video: dict[str, Any], transcript: str, config: dict[str, Any]) -> dict[str, Any]:
    text = transcript or ""
    lower = text.lower() + " " + str(video.get("title", "")).lower()
    topics = [topic for topic, words in KEYWORDS.items() if any(w in lower for w in words)]
    hype = "hype" if "hype" in topics and not ({"workflows", "automation_ideas"} & set(topics)) else "actionable"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    useful = [s for s in sentences if any(k in s.lower() for k in ["workflow", "autom", "agent", "tool", "prompt", "api", "n8n", "claude", "codex"])]
    summary = useful[:5] or sentences[:3]
    extraction = base_extraction(video, text, model="heuristic-local-stub")
    extraction.update(
        {
            "topics": topics,
            "hype_vs_actionable": hype,
            "tldr": summary[:2],
            "workflows": [],
            "automations_for_small_business": [],
            "tools_models_stacks": [],
            "prompts_and_patterns": [],
            "hermes_openclaw_codex_ideas": [],
            "obsidian_targets": [],
            "claims": [],
            "verification": {"claims_checked": 0, "researcher_model": None, "confidence": "not_run", "notes": "Researcher verification is stubbed; no LLM client available."},
            "raw_transcript_retained": False,
        }
    )
    if "workflows" in topics:
        extraction["workflows"].append({"title": "Candidate workflow from transcript", "steps": summary[:4], "stack": infer_tools(lower), "copy_difficulty": "medium"})
    if "automation_ideas" in topics:
        extraction["automations_for_small_business"].append({"use_case": "Operational automation candidate", "trigger": "See video transcript/notes", "tools": infer_tools(lower), "estimated_value": "Requires review"})
    if "skills_to_build" in topics:
        extraction["hermes_openclaw_codex_ideas"].append({"kind": "skill", "name": "youtube-agent-watch-followup", "rationale": "Video mentions agent/tooling patterns worth reviewing."})
    extraction["tools_models_stacks"] = [{"name": t, "role": "mentioned", "first_party": False} for t in infer_tools(lower)]
    extraction["obsidian_targets"] = obsidian_targets(extraction)
    return extraction


def extract_operational_signal_llm(
    video: dict[str, Any],
    transcript: str,
    config: dict[str, Any],
    *,
    llm_call: Callable[[str, dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    llm_cfg = extractor_model_config(config)
    model_label = f"{llm_cfg.get('provider', 'unknown')}/{llm_cfg.get('model', 'unknown')}"
    try:
        prompt = build_extraction_prompt(video, transcript, config)
        raw = (llm_call or call_hermes_agent)(prompt, llm_cfg)
        parsed = parse_json_object(raw)
        return normalize_llm_extraction(parsed, video, transcript, model_label)
    except Exception as exc:
        fallback = heuristic_extract_operational_signal(video, transcript, config)
        fallback["model"] = f"{model_label} (llm_failed; fallback=heuristic-local-stub)"
        fallback["llm_error"] = f"{type(exc).__name__}: {exc}"
        fallback["extraction_mode"] = "llm_fallback_heuristic"
        return fallback


def extractor_model_config(config: dict[str, Any]) -> dict[str, Any]:
    llm_cfg = dict(config.get("extraction", {}).get("llm", {}))
    specialist = config.get("models", {}).get("specialists", {}).get("extractor", {})
    llm_cfg.setdefault("provider", specialist.get("provider", "openai-codex"))
    llm_cfg.setdefault("model", specialist.get("model", "gpt-5.4-mini"))
    return llm_cfg


def build_extraction_prompt(video: dict[str, Any], transcript: str, config: dict[str, Any]) -> str:
    llm_cfg = extractor_model_config(config)
    limit = int(llm_cfg.get("transcript_truncate_chars", 90000) or 90000)
    text = (transcript or "")[:limit]
    template = PROMPT_PATH.read_text(encoding="utf-8")
    metadata = {
        "video_id": video.get("video_id"),
        "creator_id": video.get("creator_id"),
        "creator_name": video.get("creator_name", video.get("creator_id")),
        "title": video.get("title", "Untitled"),
        "url": video.get("url", f"https://www.youtube.com/watch?v={video.get('video_id')}"),
        "duration_s": video.get("duration_s"),
        "upload_date": video.get("upload_date"),
        "transcript_source": video.get("transcript_source", "none"),
    }
    schema = {field: [] for field in LIST_FIELDS}
    schema.update(
        {
            "hype_vs_actionable": "actionable|hype|mixed|low_signal",
            "low_signal_reason": "string when low_signal applies",
            "verification": {"claims_checked": 0, "researcher_model": None, "confidence": "not_run", "notes": "not run"},
        }
    )
    return (
        f"{template}\n\n"
        "Return one JSON object only. Do not wrap it in markdown. Do not include score, score_band, score_reasons, or score_components.\n\n"
        f"Video metadata JSON:\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        f"Expected extraction keys JSON:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "Transcript:\n<<<TRANSCRIPT\n"
        f"{text}\n"
        "TRANSCRIPT>>>"
    )


def call_hermes_agent(prompt: str, llm_cfg: dict[str, Any]) -> str:
    """Lazy Hermes AIAgent call used only when extraction.mode=llm."""

    try:
        from run_agent import AIAgent  # type: ignore
    except Exception:
        from hermes_agent.run_agent import AIAgent  # type: ignore

    agent = AIAgent(
        provider=llm_cfg.get("provider"),
        model=llm_cfg.get("model", "gpt-5.4-mini"),
        max_iterations=1,
        enabled_toolsets=[],
        disabled_toolsets=["all"],
        quiet_mode=True,
        skip_memory=True,
        skip_context_files=True,
        platform="youtube_agent_watch",
    )
    return str(agent.chat(prompt))


def parse_json_object(raw: str) -> dict[str, Any]:
    text = strip_markdown_fences(str(raw or "")).strip()
    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("No JSON object found in LLM response")


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def normalize_llm_extraction(parsed: dict[str, Any], video: dict[str, Any], transcript: str, model_label: str) -> dict[str, Any]:
    cleaned = {k: v for k, v in parsed.items() if k not in SCORE_FIELDS}
    extraction = base_extraction(video, transcript, model=model_label)
    extraction.update(cleaned)

    # Metadata always comes from trusted ingest metadata, not the model.
    extraction.update(base_extraction(video, transcript, model=model_label))
    for field in LIST_FIELDS:
        extraction[field] = normalize_list(extraction.get(field))
    extraction["topics"] = [str(t) for t in extraction["topics"] if str(t) in ALLOWED_TOPICS]
    if not extraction["topics"] and extraction.get("low_signal_reason"):
        extraction["topics"] = ["low_signal"]
    extraction["hype_vs_actionable"] = normalize_choice(extraction.get("hype_vs_actionable"), {"actionable", "hype", "mixed", "low_signal"}, "actionable")
    extraction["verification"] = normalize_verification(extraction.get("verification"))
    extraction["raw_transcript_retained"] = bool(extraction.get("raw_transcript_retained", False))
    extraction["obsidian_targets"] = normalize_list(extraction.get("obsidian_targets")) or obsidian_targets(extraction)
    extraction["extraction_mode"] = "llm"
    return extraction


def base_extraction(video: dict[str, Any], transcript: str, *, model: str) -> dict[str, Any]:
    video_id = video["video_id"]
    return {
        "video_id": video_id,
        "creator_id": video["creator_id"],
        "creator_name": video.get("creator_name", video.get("creator_id")),
        "title": video.get("title", "Untitled"),
        "url": video.get("url", f"https://www.youtube.com/watch?v={video_id}"),
        "duration_s": video.get("duration_s"),
        "upload_date": video.get("upload_date"),
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "transcript_source": video.get("transcript_source", "none"),
        "transcript_tokens": max(1, len((transcript or "").split())),
    }


def normalize_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def normalize_verification(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    return {
        "claims_checked": int(value.get("claims_checked") or 0),
        "researcher_model": value.get("researcher_model"),
        "confidence": value.get("confidence", "not_run"),
        "notes": value.get("notes", "Researcher verification not run during extraction."),
    }


def infer_tools(lower_text: str) -> list[str]:
    candidates = ["n8n", "Zapier", "Make.com", "Claude Code", "Codex", "OpenAI", "Anthropic", "Gemini", "MCP", "Cursor", "GitHub"]
    return [c for c in candidates if c.lower() in lower_text]


def obsidian_targets(extraction: dict[str, Any]) -> list[str]:
    targets = ["Extracted Learnings.md"]
    topics = set(extraction.get("topics", []))
    if "automation_ideas" in topics:
        targets.append("Automation Ideas.md")
    if "skills_to_build" in topics:
        targets.append("Hermes Skills To Build.md")
    return targets


def verify_if_needed(extraction: dict[str, Any], score: float, config: dict[str, Any]) -> dict[str, Any]:
    threshold = config.get("verification", {}).get("researcher_verification_threshold", 8)
    if score >= threshold and extraction.get("claims"):
        extraction["verification"] = {"claims_checked": len(extraction["claims"][:3]), "researcher_model": config["models"]["specialists"]["researcher"]["model"], "confidence": "unverified_stub", "notes": "Claims present; researcher verification threshold met but no LLM client configured in watcher."}
    return extraction
