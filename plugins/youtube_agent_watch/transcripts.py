from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


WHISPER_FALLBACK_DEFAULTS: dict[str, Any] = {
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
}


def fetch_transcript(video_id: str, config: dict[str, Any], cache_dir: Path, *, logger=print) -> tuple[str, str]:
    languages = config.get("ingest", {}).get("transcript", {}).get("languages", ["en"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # v1.x prefers instance API; older versions expose class/static methods.
        try:
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id, languages=languages)
            text = "\n".join(getattr(snippet, "text", str(snippet)) for snippet in fetched)
        except TypeError:
            rows = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
            text = "\n".join(row.get("text", "") for row in rows)
        if text.strip():
            (cache_dir / f"{video_id}.txt").write_text(text, encoding="utf-8")
            return text, "yt-transcript-api"
    except Exception as exc:  # dependency missing, disabled captions, network, etc.
        logger(f"transcript-api unavailable for {video_id}: {exc}")
    text, source = fetch_auto_subs_fallback(video_id, config, cache_dir, logger=logger)
    if text.strip():
        return text, source
    if _whisper_config(config).get("enabled"):
        return fetch_whisper_fallback(video_id, config, cache_dir, logger=logger)
    return "", "none"


def fetch_auto_subs_fallback(video_id: str, config: dict[str, Any], cache_dir: Path, *, logger=print) -> tuple[str, str]:
    yt_dlp = config.get("ingest", {}).get("yt_dlp_path", "yt-dlp")
    outtmpl = str(cache_dir / f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [yt_dlp, "--skip-download", "--write-auto-subs", "--sub-lang", "en.*", "--sub-format", "json3", "-o", outtmpl, url]
    _insert_yt_dlp_auth_and_args(cmd, config)
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        if proc.returncode != 0:
            logger(f"yt-dlp subtitle fallback failed for {video_id}: {_redact(proc.stderr.strip(), config)}")
            return "", "none"
        for sub in cache_dir.glob(f"{video_id}*.json3"):
            text = json3_to_text(sub)
            if text.strip():
                (cache_dir / f"{video_id}.txt").write_text(text, encoding="utf-8")
                try:
                    sub.unlink()
                except OSError:
                    pass
                return text, "yt-dlp-auto"
    except Exception as exc:
        logger(f"yt-dlp subtitle fallback error for {video_id}: {_redact(str(exc), config)}")
    return "", "none"


def fetch_whisper_fallback(video_id: str, config: dict[str, Any], cache_dir: Path, *, logger=print) -> tuple[str, str]:
    cfg = _whisper_config(config)
    if not cfg.get("enabled", True):
        return "", "none"

    whisper_bin = Path(str(cfg.get("binary", WHISPER_FALLBACK_DEFAULTS["binary"]))).expanduser()
    whisper_executable = str(whisper_bin)
    if not whisper_bin.is_file():
        found = shutil.which(str(cfg.get("binary", "")))
        if not found:
            logger(f"whisper binary not found at {whisper_bin}")
            return "", "none"
        whisper_executable = found

    audio_format = str(cfg.get("audio_format", "m4a"))
    audio_path = cache_dir / f"{video_id}.{audio_format}"
    output_path = cache_dir / f"{video_id}.{cfg.get('output_format', 'txt')}"

    try:
        yt_dlp = config.get("ingest", {}).get("yt_dlp_path", "yt-dlp")
        audio_tmpl = str(cache_dir / f"{video_id}.%(ext)s")
        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = [
            str(yt_dlp),
            "-x",
            "--audio-format",
            audio_format,
            "--audio-quality",
            str(cfg.get("audio_quality", "0")),
            "--ffmpeg-location",
            str(cfg.get("ffmpeg_location", "/opt/homebrew/bin")),
            "-o",
            audio_tmpl,
            url,
        ]
        _insert_yt_dlp_auth_and_args(cmd, config)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=int(cfg.get("audio_download_timeout_seconds", 300)),
        )
        if proc.returncode != 0:
            logger(f"yt-dlp audio download failed for {video_id}: {_redact(proc.stderr, config)}")
            _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=True)
            return "", "none"

        produced = next(cache_dir.glob(f"{video_id}.{audio_format}"), None)
        if produced is None or not produced.exists() or produced.stat().st_size == 0:
            logger(f"yt-dlp audio download failed for {video_id}: expected audio not found")
            _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=True)
            return "", "none"
        audio_path = produced

        start = time.monotonic()
        whisper_cmd = [
            whisper_executable,
            str(audio_path),
            "--model",
            str(cfg.get("model", "small.en")),
            "--language",
            str(cfg.get("language", "en")),
            "--output_format",
            str(cfg.get("output_format", "txt")),
            "--output_dir",
            str(cache_dir),
            "--fp16",
            "False",
        ]
        proc = subprocess.run(
            whisper_cmd,
            capture_output=True,
            text=True,
            timeout=int(cfg.get("whisper_timeout_seconds", 1800)),
        )
        if proc.returncode != 0:
            logger(f"whisper fallback failed for {video_id}: {_redact(proc.stderr, config)}")
            _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=bool(cfg.get("delete_audio_after", True)))
            return "", "none"

        if not output_path.exists():
            logger(f"whisper fallback failed for {video_id}: expected output not found")
            _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=bool(cfg.get("delete_audio_after", True)))
            return "", "none"
        text = output_path.read_text(encoding="utf-8")
        if len(text.strip()) < int(cfg.get("min_chars", 200)):
            logger(f"whisper output below min_chars for {video_id}")
            _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=bool(cfg.get("delete_audio_after", True)), remove_txt=True)
            return "", "none"

        canonical = cache_dir / f"{video_id}.txt"
        canonical.write_text(text, encoding="utf-8")
        _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=bool(cfg.get("delete_audio_after", True)))
        duration_ms = int((time.monotonic() - start) * 1000)
        logger(f"whisper-fallback used for {video_id} model={cfg.get('model', 'small.en')} duration_ms={duration_ms}")
        return text, "whisper-fallback"
    except subprocess.TimeoutExpired as exc:
        logger(f"whisper fallback timeout for {video_id}: {_redact(str(exc), config)}")
        _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=bool(cfg.get("delete_audio_after", True)))
    except Exception as exc:
        logger(f"whisper fallback error for {video_id}: {_redact(str(exc), config)}")
        _cleanup_whisper_outputs(video_id, cache_dir, audio_path, delete_audio=bool(cfg.get("delete_audio_after", True)))
    return "", "none"


def _whisper_config(config: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(WHISPER_FALLBACK_DEFAULTS)
    cfg.update(config.get("ingest", {}).get("transcript", {}).get("whisper_fallback", {}) or {})
    return cfg


def _insert_yt_dlp_auth_and_args(cmd: list[str], config: dict[str, Any]) -> None:
    extra_args = config.get("ingest", {}).get("yt_dlp_args", [])
    if extra_args:
        cmd[1:1] = [str(arg) for arg in extra_args]
    cookie_file = config.get("ingest", {}).get("cookie_file")
    if cookie_file and Path(str(cookie_file)).expanduser().is_file():
        cmd[1:1] = ["--cookies", str(Path(str(cookie_file)).expanduser())]
    else:
        cookies_from_browser = config.get("ingest", {}).get("cookies_from_browser")
        if cookies_from_browser:
            cmd[1:1] = ["--cookies-from-browser", str(cookies_from_browser)]


def _redact(text: str | None, config: dict[str, Any]) -> str:
    if not text:
        return ""
    redacted_lines = []
    cookie_file = config.get("ingest", {}).get("cookie_file")
    cookie_path = str(Path(str(cookie_file)).expanduser()) if cookie_file else ""
    for line in str(text).splitlines():
        stripped = line.lstrip().lower()
        if stripped.startswith("cookie:") or stripped.startswith("set-cookie:"):
            continue
        if cookie_path:
            line = line.replace(cookie_path, "<cookie_file>")
        redacted_lines.append(line)
    return "\n".join(redacted_lines).strip()[:500]


def _cleanup_whisper_outputs(video_id: str, cache_dir: Path, audio_path: Path, *, delete_audio: bool, remove_txt: bool = False) -> None:
    if delete_audio:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass
    for suffix in [".vtt", ".json", ".srt"]:
        try:
            (cache_dir / f"{video_id}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
    if remove_txt:
        try:
            (cache_dir / f"{video_id}.txt").unlink(missing_ok=True)
        except OSError:
            pass


def json3_to_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    parts: list[str] = []
    for event in data.get("events", []):
        segs = event.get("segs") or []
        parts.extend(seg.get("utf8", "") for seg in segs)
    return "".join(parts).replace("\n", " ").strip()


def purge_transcript(video_id: str, cache_dir: Path, *, retain: bool) -> None:
    if retain:
        return
    for p in cache_dir.glob(f"{video_id}*"):
        try:
            p.unlink()
        except OSError:
            pass
