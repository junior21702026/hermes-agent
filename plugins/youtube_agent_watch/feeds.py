from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

YOUTUBE_URL = "https://www.youtube.com/{handle}/videos"


def _parse_upload_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None


def fetch_creator_videos(creator: dict[str, Any], config: dict[str, Any], *, logger=print) -> list[dict[str, Any]]:
    ingest = config.get("ingest", {})
    handle = creator["handle"] if creator["handle"].startswith("@") else f"@{creator['handle']}"
    url = YOUTUBE_URL.format(handle=handle)
    cmd = [ingest.get("yt_dlp_path", "yt-dlp"), "--dump-json", "--flat-playlist", "--playlist-end", str(ingest.get("per_creator_lookback_videos", 5)), url]
    logger(f"fetch: {' '.join(cmd)}")
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "yt-dlp failed")
    videos = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        video_id = raw.get("id") or raw.get("url")
        if not video_id:
            continue
        videos.append({
            "video_id": video_id,
            "creator_id": creator["id"],
            "creator_name": creator.get("name", creator["id"]),
            "title": raw.get("title") or "Untitled",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "upload_date": raw.get("upload_date") or raw.get("release_date"),
            "duration_s": raw.get("duration") or 0,
        })
    return videos


def filter_candidates(videos: list[dict[str, Any]], config: dict[str, Any], state) -> list[dict[str, Any]]:
    ingest = config.get("ingest", {})
    today = datetime.now(timezone.utc).date()
    max_age = int(ingest.get("max_video_age_days", 14))
    min_d = int(ingest.get("min_duration_seconds", 180))
    max_d = int(ingest.get("max_duration_seconds", 7200))
    out = []
    for v in videos:
        if state.seen(v["video_id"]):
            continue
        duration = int(v.get("duration_s") or 0)
        if duration <= 0:
            continue
        if not (min_d <= duration <= max_d):
            continue
        uploaded = _parse_upload_date(v.get("upload_date"))
        if uploaded and (today - uploaded).days > max_age:
            continue
        out.append(v)
    return out


def fixture_videos(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("videos", [])
