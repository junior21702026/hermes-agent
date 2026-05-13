from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import creators_by_id, ensure_runtime_dirs, load_config, paths, write_default_config
from .extractor import extract_operational_signal, verify_if_needed
from .feeds import fetch_creator_videos, filter_candidates, fixture_videos
from .obsidian import ObsidianWriter
from .router import route_extraction
from .scoring import score_extraction
from .state import StateStore
from .transcripts import fetch_transcript, purge_transcript


def setup_logger(p, run_id: str) -> logging.Logger:
    p.logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"youtube-agent-watch.{run_id}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    logfile = p.logs_dir / f"run-{run_id}.log"
    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    latest = p.logs_dir / "run-latest.log"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(logfile.name)
    except OSError:
        shutil.copyfile(logfile, latest)
    return logger


def healthcheck(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config) if args.config else None)
    p = paths(config=config)
    ensure_runtime_dirs(p)
    issues: list[str] = []
    strict = bool(getattr(args, "strict", False))
    print(f"runtime_home: {p.runtime_home}")
    print(f"config: {p.config_path}")
    print(f"mode: {'strict' if strict else 'lenient'}")
    print("install_deps_command: python -m pip install 'yt-dlp>=2024.10.0' 'youtube-transcript-api>=0.6.2' 'jinja2>=3.1' 'PyYAML>=6.0'")
    try:
        proc = subprocess.run([config["ingest"].get("yt_dlp_path", "yt-dlp"), "--version"], text=True, capture_output=True, timeout=15)
        if proc.returncode == 0:
            print(f"yt-dlp: OK {proc.stdout.strip()}")
        else:
            issues.append(f"yt-dlp failed: {proc.stderr.strip()}")
    except Exception as exc:
        issues.append(f"yt-dlp unavailable: {exc}")
    try:
        import youtube_transcript_api  # noqa: F401
        print("youtube-transcript-api: OK")
    except Exception as exc:
        issues.append(f"youtube-transcript-api unavailable: {exc}")
    print(f"extraction_mode: {config.get('extraction', {}).get('mode', 'heuristic_stub')}")
    print(f"discord_delivery_mode: {config.get('discord', {}).get('delivery_mode', 'log_only')}")
    configured_channels = sorted({
        config.get("discord", {}).get("fallback_channel", "ai-research"),
        config.get("intelligence_channels", {}).get("primary", "ai-agent-watch"),
        *config.get("intelligence_channels", {}).get("topics", {}).values(),
        *(c.get("discord_channel", "") for c in config.get("creators", [])),
    } - {""})
    print("configured_discord_channels: " + ", ".join(configured_channels))
    usage = shutil.disk_usage(str(p.runtime_home))
    free_gb = usage.free / (1024 ** 3)
    print(f"disk_free_gb: {free_gb:.2f}")
    if free_gb < 4:
        issues.append("disk free below 4GB guard")
    obs_base = Path(config["obsidian"]["vault_path"]) / config["obsidian"]["base_folder"]
    try:
        obs_base.mkdir(parents=True, exist_ok=True)
        canary = obs_base / ".canary"
        canary.write_text("ok", encoding="utf-8")
        canary.unlink()
        print(f"obsidian_writable: OK {obs_base}")
    except Exception as exc:
        issues.append(f"obsidian not writable: {exc}")
    StateStore(p.state_db).close()
    ObsidianWriter(config).ensure_stubs()
    if issues:
        print("HEALTHCHECK WARN")
        for issue in issues:
            print(f"- {issue}")
        # Dependency/network warnings should not block local review in lenient mode; strict mode is for cron readiness.
        return 1 if strict else 0
    print("HEALTHCHECK OK")
    return 0


def run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config) if args.config else None)
    if args.dry_run:
        config["verification"]["dry_run"] = True
    p = paths(dry_run=args.dry_run, config=config)
    ensure_runtime_dirs(p)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger = setup_logger(p, run_id)
    log = logger.info
    state = StateStore(p.state_db)
    state.upsert_creators(config.get("creators", []))
    state.start_run(run_id)
    selected = set(args.creators.split(",")) if args.creators else None
    creator_map = creators_by_id(config)
    candidates: list[dict[str, Any]] = []
    errors = 0
    try:
        # `--max-videos 0` is the local smoke-test path: initialize config/state/reports
        # without touching YouTube or transcript services.
        if args.max_videos == 0:
            log("max_videos=0; skipping creator fetch and transcript fetch")
        elif args.fixture:
            videos = fixture_videos(Path(args.fixture))
            for v in videos:
                c = creator_map.get(v.get("creator_id"), {})
                v.setdefault("creator_name", c.get("name", v.get("creator_id", "Unknown")))
            candidates.extend(filter_candidates(videos, config, state))
        else:
            for creator in config.get("creators", []):
                if selected and creator["id"] not in selected:
                    continue
                try:
                    videos = fetch_creator_videos(creator, config, logger=log)
                    candidates.extend(filter_candidates(videos, config, state))
                    state.mark_creator_checked(creator["id"])
                except Exception as exc:
                    errors += 1
                    log(f"creator fetch failed {creator['id']}: {exc}")
        if args.max_videos is not None:
            candidates = candidates[: args.max_videos]
        log(f"candidates={len(candidates)} dry_run={args.dry_run}")
        routed = 0
        extracted = 0
        results = []
        for video in candidates:
            state.queue_video(video)
            text, source = ("", "none")
            if not args.metadata_only:
                text, source = fetch_transcript(video["video_id"], config, p.transcripts_cache_dir, logger=log)
            video["transcript_source"] = source
            min_chars = int(config["ingest"]["transcript"].get("min_chars", 800))
            transcript_missing = len(text) < min_chars
            extraction = extract_operational_signal(video, text, config)
            creator_weight = creator_map.get(video["creator_id"], {}).get("weight", 1.0)
            score = score_extraction(extraction, config, transcript_missing=transcript_missing, creator_weight=creator_weight)
            extraction.update(score)
            extraction = verify_if_needed(extraction, extraction["score"], config)
            retain = extraction["score"] >= float(config["ingest"].get("retain_raw_transcript_if_score_gte", 9))
            extraction["raw_transcript_retained"] = retain
            extract_path = p.extractions_dir / f"{video['video_id']}.json"
            extract_path.write_text(json.dumps(extraction, indent=2, ensure_ascii=False), encoding="utf-8")
            routing = {"sinks": [], "discord_messages": [], "obsidian_note_path": None}
            if live_safety_allows_routing(extraction, config, dry_run=args.dry_run, allow_heuristic_live=args.allow_heuristic_live):
                routing = route_extraction(extraction, config, dry_run=args.dry_run, logger=log)
            else:
                extraction["live_safety_gate"] = "blocked_heuristic_archive_route"
                extract_path.write_text(json.dumps(extraction, indent=2, ensure_ascii=False), encoding="utf-8")
                log("live safety gate blocked heuristic archive routing; use extraction.mode=llm or --allow-heuristic-live")
            if routing["sinks"]:
                routed += 1
            extracted += 1
            status = "routed" if routing["sinks"] else "seen_only"
            if source == "none" and transcript_missing:
                status = "failed"
            state.record_result(video["video_id"], status=status, score=extraction["score"], score_band=extraction["score_band"], transcript_chars=len(text), transcript_source=source, extract_path=extract_path.name, topics=extraction.get("topics", []), obsidian_note_path=routing.get("obsidian_note_path"), discord_messages=routing.get("discord_messages"))
            purge_transcript(video["video_id"], p.transcripts_cache_dir, retain=retain)
            results.append(extraction)
        report_path = write_daily_report(p.reports_dir, run_id, candidates, results, errors, config)
        if args.weekly or should_write_weekly(args.schedule, config):
            weekly_path = write_weekly_report(p.extractions_dir, p.reports_dir, run_id)
            log(f"weekly_report={weekly_path}")
        state.finish_run(run_id, candidates=len(candidates), extracted=extracted, routed=routed, errors=errors, report_path=str(report_path))
        log(f"report={report_path}")
        return 0
    finally:
        state.close()


def live_safety_allows_routing(extraction: dict[str, Any], config: dict[str, Any], *, dry_run: bool, allow_heuristic_live: bool) -> bool:
    if dry_run or allow_heuristic_live:
        return True
    mode = config.get("extraction", {}).get("mode", "heuristic_stub")
    archive_t = float(config.get("scoring", {}).get("thresholds", {}).get("obsidian_and_discord", 8))
    return not (mode != "llm" and float(extraction.get("score") or 0) >= archive_t)


def should_write_weekly(schedule: str | None, config: dict[str, Any]) -> bool:
    if schedule != "evening":
        return False
    tz_name = config.get("schedule", {}).get("timezone", "UTC")
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now()
    return now.strftime("%A") == str(config.get("schedule", {}).get("weekly_digest", {}).get("day", "Sunday"))


def write_daily_report(reports_dir: Path, run_id: str, candidates: list[dict[str, Any]], results: list[dict[str, Any]], errors: int, config: dict[str, Any]) -> Path:
    path = reports_dir / f"daily-{run_id}.md"
    source_counts: dict[str, int] = {}
    for video in candidates:
        source = str(video.get("transcript_source") or "none")
        source_counts[source] = source_counts.get(source, 0) + 1
    source_summary = ", ".join(f"{k}={v}" for k, v in sorted(source_counts.items())) or "none=0"
    lines = [f"# YouTube Agent Watch Report {run_id}", "", f"Candidates: {len(candidates)}", f"Extracted: {len(results)}", f"Errors: {errors}", f"Transcript sources: {source_summary}", f"Discord delivery mode: {config.get('discord', {}).get('delivery_mode', 'log_only')}", f"Extraction mode: {config.get('extraction', {}).get('mode', 'heuristic_stub')}", ""]
    for r in results:
        lines.append(f"- {r.get('score')} — {r.get('creator_name')} — [{r.get('title')}]({r.get('url')}) — {', '.join(r.get('topics', []))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_weekly_report(extractions_dir: Path, reports_dir: Path, run_id: str) -> Path:
    cutoff = datetime.now() - timedelta(days=7)
    items: list[dict[str, Any]] = []
    for path in sorted(extractions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            continue
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    out = reports_dir / f"weekly-{run_id}.md"
    lines = [f"# YouTube Agent Watch Weekly Stub {run_id}", "", "Scope: last 7 days of local extraction JSON files.", f"Items: {len(items)}", "", "## Top items"]
    for item in sorted(items, key=lambda x: float(x.get("score") or 0), reverse=True)[:20]:
        lines.append(f"- {item.get('score')} — {item.get('creator_name')} — [{item.get('title')}]({item.get('url')})")
    if not items:
        lines.append("- No extraction JSON files found for the last 7 days.")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="youtube-agent-watch")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("healthcheck")
    h.add_argument("--lenient", action="store_true", help="Return 0 for dependency warnings during local review (default).")
    h.add_argument("--strict", action="store_true", help="Return non-zero for dependency/config warnings before cron scheduling.")
    h.set_defaults(func=healthcheck)
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--creators", help="Comma-separated creator ids")
    r.add_argument("--max-videos", type=int, default=None)
    r.add_argument("--fixture")
    r.add_argument("--metadata-only", action="store_true", help="Skip transcript fetch; useful for dependency-limited local smoke tests")
    r.add_argument("--schedule", choices=["morning", "evening"], default=None)
    r.add_argument("--weekly", action="store_true", help="Also write a last-7-days weekly synthesis stub.")
    r.add_argument("--allow-heuristic-live", action="store_true", help="Permit live routing of heuristic_stub archive scores; normally blocked until extraction.mode=llm.")
    r.set_defaults(func=run)
    return parser


def main(argv: list[str] | None = None) -> int:
    write_default_config()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
