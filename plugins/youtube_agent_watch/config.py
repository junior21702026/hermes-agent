from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_HOME = Path("/Users/junior/junior-agent/.hermes/youtube-agent-watch")
DEFAULT_OBSIDIAN_VAULT = Path("/Users/junior/Documents/Obsidian Vault")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "schedule": {
        "timezone": "Australia/Brisbane",
        "runs": ["08:00", "20:00"],
        "weekly_digest": {"day": "Sunday", "time": "20:00"},
    },
    "models": {
        "orchestrator": {"provider": "openai-codex", "model": "gpt-5.4-mini"},
        "specialists": {
            "extractor": {"provider": "openai-codex", "model": "gpt-5.4-mini"},
            "scorer": {"provider": "openai-codex", "model": "gpt-5.4-mini"},
            "researcher": {"provider": "openrouter", "model": "perplexity/sonar-reasoning", "trigger": "score_gte_8_and_claims_present", "threshold_score": 8},
            "long_context": {"provider": "openrouter", "model": "google/gemini-2.5-pro", "trigger": "transcript_tokens_gt_60000 OR mode=weekly"},
            "writer": {"enabled": False, "provider": "openai-codex", "model": "gpt-5"},
        },
    },
    "extraction": {
        "mode": "heuristic_stub",
        "llm": {
            "provider": "openai-codex",
            "model": "gpt-5.4-mini",
            "max_input_tokens": 60000,
            "long_context_action": "flag_only",
            "transcript_truncate_chars": 90000,
            "retry_on_parse_error": 1,
            "timeout_seconds": 120,
        },
    },
    "ingest": {
        "yt_dlp_path": "yt-dlp",
        "per_creator_lookback_videos": 5,
        "max_video_age_days": 14,
        "min_duration_seconds": 180,
        "max_duration_seconds": 7200,
        "transcript": {
            "primary": "youtube_transcript_api",
            "fallback": "yt_dlp_auto_subs",
            "languages": ["en", "en-US", "en-GB", "en-AU"],
            "min_chars": 800,
            "whisper_fallback": {
                "enabled": True,
                "binary": "/opt/homebrew/bin/whisper",
                "model": "small.en",
                "language": "en",
                "output_format": "txt",
                "audio_format": "m4a",
                "audio_quality": "0",
                "ffmpeg_location": "/opt/homebrew/bin",
                "audio_download_timeout_seconds": 300,
                "whisper_timeout_seconds": 1800,
                "delete_audio_after": True,
                "min_chars": 200,
            },
        },
        "cookie_file": "/Users/junior/junior-agent/.hermes/youtube-cookies.txt",
        "cookies_from_browser": "chrome",
        "yt_dlp_args": ["--impersonate", "", "--extractor-retries", "5", "--sleep-subtitles", "5"],
        "retain_raw_transcript_if_score_gte": 9,
        "retain_raw_transcript_days": 30,
    },
    "creators": [
        {"id": "nate-herk", "name": "Nate Herk", "handle": "@NateHerk", "discord_channel": "yt-nate-herk", "weight": 1.0},
        {"id": "alex-finn", "name": "Alex Finn", "handle": "@AlexFinnOfficial", "discord_channel": "yt-alex-finn", "weight": 1.0},
        {"id": "worldofai", "name": "WorldofAI", "handle": "@intheworldofai", "discord_channel": "yt-worldofai", "weight": 1.0},
        {"id": "julian-goldie", "name": "Julian Goldie", "handle": "@JulianGoldieSEO", "discord_channel": "yt-julian-goldie", "weight": 0.9},
        {"id": "moe-lueker", "name": "Moe Lueker", "handle": "@moelueker", "discord_channel": "yt-moe-lueker", "weight": 1.0},
        {"id": "matthew-berman", "name": "Matthew Berman", "handle": "@matthew_berman", "discord_channel": "yt-matthew-berman", "weight": 1.0},
        {"id": "all-about-ai", "name": "All About AI", "handle": "@AllAboutAI", "discord_channel": "yt-all-about-ai", "weight": 1.0},
    ],
    "intelligence_channels": {
        "primary": "ai-agent-watch",
        "topics": {
            "automation_ideas": "automation-ideas",
            "workflows": "agent-workflows",
            "skills_to_build": "hermes-skills-to-build",
            "tool_stack": "tool-stack-radar",
            "hype": "hype-filter",
        },
    },
    "discord": {
        "guild_hint": "Junior Agent",
        "delivery_mode": "log_only",
        "bot_token_env": "DISCORD_BOT_TOKEN",
        "guild_id_env": "DISCORD_GUILD_ID",
        "channel_cache_ttl_minutes": 60,
        "max_warnings_per_run": 5,
        "fallback_channel": "ai-research",
        "hype_fallback_channel": "ai-research",
        "on_missing_channel": "post_to_fallback_and_warn",
        "auto_create_channels": False,
    },
    "safety": {"require_explicit_live_flag": True, "live_promotion_checklist_passed": False},
    "obsidian": {
        "vault_path": str(DEFAULT_OBSIDIAN_VAULT),
        "base_folder": "02 Research/AI Agent YouTube Watch",
        "files": {"index": "Index.md", "extracted": "Extracted Learnings.md", "automations": "Automation Ideas.md", "skills": "Hermes Skills To Build.md"},
        "per_creator_folder": "Creators",
        "write_threshold_score": 8,
    },
    "scoring": {
        "thresholds": {"obsidian_and_discord": 8, "discord_short": 6, "seen_only_max": 5},
        "weights": {"workflow_explicit": 0.30, "automation_actionable": 0.25, "hermes_or_claude_code_pattern": 0.20, "tool_stack_clarity": 0.10, "novelty_vs_known": 0.10, "hype_penalty": -0.20},
    },
    "verification": {"dry_run": False, "dry_run_writes_to": "/tmp/yt-watch-dryrun", "require_human_approval_above_score": None, "researcher_verification_threshold": 8},
}


@dataclass(frozen=True)
class Paths:
    runtime_home: Path
    config_path: Path
    state_db: Path
    pending_jsonl: Path
    logs_dir: Path
    extractions_dir: Path
    transcripts_cache_dir: Path
    reports_dir: Path


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def runtime_home() -> Path:
    return Path(os.environ.get("YOUTUBE_AGENT_WATCH_HOME", str(DEFAULT_RUNTIME_HOME))).expanduser()


def paths(home: Path | None = None, dry_run: bool = False, config: dict[str, Any] | None = None) -> Paths:
    base = home or runtime_home()
    if dry_run and config:
        base = Path(config["verification"].get("dry_run_writes_to", "/tmp/yt-watch-dryrun")).expanduser()
    return Paths(
        runtime_home=base,
        config_path=(home or runtime_home()) / "config.yaml",
        state_db=base / ("state.db.dryrun" if dry_run else "state.db"),
        pending_jsonl=base / "pending.jsonl",
        logs_dir=base / "logs",
        extractions_dir=base / "extractions",
        transcripts_cache_dir=base / "transcripts_cache",
        reports_dir=base / "reports",
    )


def ensure_runtime_dirs(p: Paths) -> None:
    for d in [p.runtime_home, p.logs_dir, p.extractions_dir, p.transcripts_cache_dir, p.reports_dir]:
        d.mkdir(parents=True, exist_ok=True)
    p.pending_jsonl.touch(exist_ok=True)


def write_default_config(path: Path | None = None) -> Path:
    target = path or runtime_home() / "config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
    return target


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = write_default_config(path)
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return deep_merge(DEFAULT_CONFIG, loaded)


def creators_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in config.get("creators", [])}
