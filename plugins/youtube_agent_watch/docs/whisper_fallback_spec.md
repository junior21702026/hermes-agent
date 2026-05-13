# Whisper Audio-Transcription Fallback — Architect Spec

**Plugin:** `plugins/youtube_agent_watch`
**Status:** Design only (no implementation)
**Author:** architect subagent
**Date:** 2026-05-13
**Trigger:** User request "okay do it" — add Whisper fallback so YouTube subtitle 429s do not stop extraction. Hotspot internet proves transcripts work; home internet still 429s on subtitle endpoint.

---

## 1. Discovery findings

- **No existing Whisper fallback** found in: `plugins/youtube_agent_watch`, bundled `skills/`, `optional-skills/`, `~/.hermes/skills/`, hub-skills cache. Greps for `whisper`, `audio`, `transcribe`, `--extract-audio`, `ffmpeg` in those trees: zero hits. Building from scratch is required.
- **Tools available:**
  - `/opt/homebrew/bin/whisper` — OpenAI Whisper CLI (subprocess only).
  - `/opt/homebrew/bin/ffmpeg` — required by both yt-dlp audio extraction and whisper.
  - `.venv/bin/yt-dlp` — already used by `fetch_auto_subs_fallback`.
- **Python deps:** `yt_dlp` present in venv. `whisper` and `faster_whisper` Python modules **not** installed; we deliberately stay subprocess-based to avoid adding heavy deps.
- **Current flow** in `transcripts.py:fetch_transcript`:
  1. `youtube_transcript_api` (returns `yt-transcript-api`).
  2. Fallback `fetch_auto_subs_fallback` via yt-dlp `--write-auto-subs --sub-format json3` (returns `yt-dlp-auto`).
  3. Otherwise `("", "none")`.

We are inserting a **third** fallback between step 2's failure and the final `none` return.

---

## 2. Goals & non-goals

**Goals**
- Recover transcripts when both `youtube_transcript_api` and yt-dlp subtitle endpoint return 429 / blocked.
- Use the system `whisper` CLI via subprocess. No new Python imports beyond stdlib.
- Preserve cookie / yt-dlp flag behavior already in place for audio download.
- Keep secrets (cookie content, full cookie paths in error noise) out of logs.
- Expose tunables in config; ship safe defaults.
- Maintain TDD: unittest-only, no real network in unit tests.

**Non-goals**
- Bundling `whisper` or `faster-whisper` Python packages.
- GPU detection / model auto-selection beyond a configured model name.
- Streaming or chunked transcription for very long videos in v1 (timeout guard instead).
- Mutating the Obsidian write path or the "do not present transcript-blocked backfills as transcript-backed" rule (handled by caller; we just return a distinct source string and let downstream decide).

---

## 3. Files to modify / create

### Modify
| File | Change |
|---|---|
| `plugins/youtube_agent_watch/transcripts.py` | Add `fetch_whisper_fallback(video_id, config, cache_dir, *, logger)` and wire it into `fetch_transcript` after `fetch_auto_subs_fallback` returns `("","none")` and only when `config.ingest.transcript.whisper_fallback.enabled` is truthy. Extend `purge_transcript` glob if needed (current glob `{video_id}*` already covers audio side files, confirm). |
| `plugins/youtube_agent_watch/config.py` | Add `whisper_fallback` block under `ingest.transcript` in `DEFAULT_CONFIG` (see §4). |
| `plugins/youtube_agent_watch/tests/test_transcripts.py` | Add tests for (a) whisper invoked only when subtitle fallback returns none; (b) cookies wired into audio download; (c) whisper CLI args constructed correctly; (d) success path writes `.txt` and returns `whisper-fallback`; (e) failure paths return `("","none")`; (f) disabled-by-config short-circuit; (g) timeout / non-zero exit handling; (h) secret redaction in logger output. |

### Create
| File | Purpose |
|---|---|
| `plugins/youtube_agent_watch/docs/whisper_fallback_spec.md` | This spec. |
| (optional) `plugins/youtube_agent_watch/tests/fixtures/fake_whisper.txt` | Static text used by mocked whisper subprocess to validate `.txt` ingestion. Inline string is fine; fixture only needed if tests grow. |

No new modules — keep the surface area inside `transcripts.py` so `purge_transcript` and existing imports stay co-located.

---

## 4. Config schema additions

Insert under `DEFAULT_CONFIG["ingest"]["transcript"]`:

```yaml
whisper_fallback:
  enabled: true                      # runtime default ON per user request
  binary: /opt/homebrew/bin/whisper  # absolute path to whisper CLI
  model: small.en                    # whisper model name (tiny.en/base.en/small.en/medium.en)
  language: en                       # passed as --language
  output_format: txt                 # whisper --output_format
  audio_format: m4a                  # yt-dlp --audio-format
  audio_quality: "0"                 # yt-dlp --audio-quality (best)
  ffmpeg_location: /opt/homebrew/bin # passed to yt-dlp --ffmpeg-location
  audio_download_timeout_seconds: 300
  whisper_timeout_seconds: 1800
  delete_audio_after: true           # remove .m4a once transcript is written
  min_chars: 200                     # below this, treat as failure
```

**Recommendation rationale**
- `enabled: true` because the user explicitly asked to add the fallback and the hotspot test confirmed transcripts are otherwise reachable; the home-internet 429 is the precise gap this closes.
- `model: small.en` balances quality vs. CPU runtime on Apple Silicon.
- `audio_format: m4a` is fastest from yt-dlp and acceptable input to whisper via ffmpeg.
- Timeouts guard against runaway whisper jobs on long videos.

Schema-level safety: `enabled` defaults to true in `DEFAULT_CONFIG`, but `fetch_whisper_fallback` must additionally hard-skip when `binary` is missing on disk — so an out-of-the-box machine without whisper installed degrades gracefully to `("","none")` instead of crashing.

---

## 5. Behavior contract

### `fetch_transcript` (modified)

```
1. yt-transcript-api → if text → cache .txt, return (text, "yt-transcript-api")
2. fetch_auto_subs_fallback → if text → return (text, "yt-dlp-auto")
3. if config.ingest.transcript.whisper_fallback.enabled:
       fetch_whisper_fallback → if text → return (text, "whisper-fallback")
4. return ("", "none")
```

### `fetch_whisper_fallback(video_id, config, cache_dir, *, logger=print) -> tuple[str, str]`

**Preconditions**
- `cache_dir` exists (caller guarantees via current `mkdir`).
- Config block read with defaults; missing keys fall back to schema defaults.

**Steps**
1. Resolve `cfg = config["ingest"]["transcript"]["whisper_fallback"]` (with `.get` and defaults).
2. Resolve `whisper_bin = Path(cfg["binary"]).expanduser()`. If not `is_file()` and not on PATH → `logger("whisper binary not found at %s", whisper_bin)`; return `("","none")`.
3. Build audio output template: `audio_tmpl = str(cache_dir / f"{video_id}.%(ext)s")`.
4. Construct yt-dlp audio command:
   ```
   [yt_dlp, "-x",
    "--audio-format", cfg.audio_format,
    "--audio-quality", cfg.audio_quality,
    "--ffmpeg-location", cfg.ffmpeg_location,
    "-o", audio_tmpl,
    f"https://www.youtube.com/watch?v={video_id}"]
   ```
   Then **prepend** `ingest.yt_dlp_args` and cookie flags using the **exact same precedence as `fetch_auto_subs_fallback`** (cookie_file if present file → else cookies_from_browser).
5. `subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.audio_download_timeout_seconds)`.
   - If returncode != 0 → log `f"yt-dlp audio download failed for {video_id}: {redact(proc.stderr)}"`; return `("","none")`.
6. Locate produced audio: `next(cache_dir.glob(f"{video_id}.{cfg.audio_format}"), None)`. If absent → log + return none.
7. Build whisper command:
   ```
   [str(whisper_bin), str(audio_path),
    "--model", cfg.model,
    "--language", cfg.language,
    "--output_format", cfg.output_format,
    "--output_dir", str(cache_dir),
    "--fp16", "False"]   # safer default on CPU
   ```
8. `subprocess.run(cmd, capture_output=True, text=True, timeout=cfg.whisper_timeout_seconds)`.
   - On non-zero or timeout → log redacted stderr, cleanup audio (respecting `delete_audio_after`), return none.
9. Whisper writes `<audio-stem>.txt` in `cache_dir`. Stem equals `f"{video_id}"` (since audio is `{video_id}.m4a`). Read it.
10. If `len(text.strip()) < cfg.min_chars` → log `"whisper output below min_chars"`, cleanup, return none.
11. Write canonical `cache_dir / f"{video_id}.txt"` (overwriting whisper's file is fine — same path with our format normalization: collapse newlines? **Decision:** keep newlines; downstream extractor handles both forms).
12. If `cfg.delete_audio_after` → `audio_path.unlink(missing_ok=True)`. Also unlink `.vtt`/`.json`/`.srt` siblings whisper may emit.
13. Return `(text, "whisper-fallback")`.

**Logging rules**
- Never log the resolved cookie file contents.
- When logging stderr from yt-dlp/whisper, pass through a `_redact(s)` helper that:
  - Replaces any substring matching the configured `cookie_file` absolute path with `<cookie_file>`.
  - Strips any `Set-Cookie:` / `Cookie:` headers (line-level filter).
  - Truncates to ~500 chars.

**Source string**
- Return `"whisper-fallback"`. Caller (extractor / Obsidian writer) MUST treat this as transcript-backed for extraction, but per the youtube-content skill rule, the Obsidian/Discord rendering layer must NOT label the output "transcript-backed" without distinguishing this provenance. (Out of scope for this spec — flagged for the next ticket.)

---

## 6. Edge cases

| Case | Behavior |
|---|---|
| `whisper` binary missing | log + return `("","none")`. Do not raise. |
| `enabled: false` in config | `fetch_whisper_fallback` not called at all. |
| yt-dlp returns non-zero (429, geo block, member-only) | log redacted stderr, return none, do not invoke whisper. |
| Audio file produced but empty (0 bytes) | treat as failure, cleanup, return none. |
| Whisper subprocess timeout | catch `TimeoutExpired`, kill, cleanup audio, return none. |
| Whisper output too short (`< min_chars`) | treat as failure to avoid garbage transcripts on music/silence. |
| Whisper output file missing despite rc==0 | log "expected output not found", return none. |
| Concurrent runs on same `video_id` | not protected here; existing pipeline already serializes per-video. |
| Cache dir ENOENT | impossible — `fetch_transcript` calls `mkdir(parents=True, exist_ok=True)`. |
| Disk full | subprocess raises; outer `try/except Exception` logs and returns none. |
| `ingest.yt_dlp_args` contains stale empty string (`["--impersonate",""]`) | preserved as-is — same behavior as subtitle path; do not filter (would change current behavior). |
| `purge_transcript(retain=False)` | existing `cache_dir.glob(f"{video_id}*")` already removes `.m4a`/`.txt`/`.vtt`; verify in test. |

---

## 7. TDD test plan (`tests/test_transcripts.py`, unittest)

Add a new `WhisperFallbackTests(unittest.TestCase)` class. All tests use `tempfile.TemporaryDirectory` and `unittest.mock.patch`. **No network, no real subprocess.**

### T1 — `fetch_transcript` skips whisper when disabled
- Patch `youtube_transcript_api` import to raise.
- Patch `fetch_auto_subs_fallback` to return `("","none")`.
- Patch `fetch_whisper_fallback` and assert it is **not** called when `enabled=false`.
- Assert return is `("","none")`.

### T2 — `fetch_transcript` invokes whisper when subtitle fallback returns none
- Same setup, `enabled=true`.
- Patch `fetch_whisper_fallback` to return `("hello world", "whisper-fallback")`.
- Assert `fetch_transcript` returns `("hello world", "whisper-fallback")`.

### T3 — Whisper binary missing → graceful none
- Point `binary` at a path under tempdir that does not exist.
- Patch `subprocess.run` to fail loudly if called (it shouldn't be).
- Assert `fetch_whisper_fallback` returns `("","none")` and logger received "whisper binary not found".

### T4 — yt-dlp audio command construction with cookie file
- Create a fake cookie file in tempdir.
- Patch `subprocess.run` to record calls, return rc=1 for first call (audio).
- Assert first call cmd contains: `-x`, `--audio-format m4a`, `--ffmpeg-location`, `--cookies <path>`, video URL.
- Assert whisper call NOT made (audio download failed).
- Assert return is `("","none")`.

### T5 — yt-dlp uses cookies-from-browser when cookie file absent
- `cookie_file` set to non-existent path, `cookies_from_browser="chrome"`.
- Assert audio cmd contains `--cookies-from-browser chrome`, NOT `--cookies`.

### T6 — Successful end-to-end
- Fake `subprocess.run`:
  - Call 1 (yt-dlp): create `cache_dir/{vid}.m4a` as side effect, return rc=0.
  - Call 2 (whisper): create `cache_dir/{vid}.txt` with 1500 chars of "lorem...", return rc=0.
- Create the whisper binary as an actual touched file in tempdir so `is_file()` passes; point config at it.
- Assert returned tuple is `(text, "whisper-fallback")`.
- Assert final `cache_dir / "{vid}.txt"` exists with that text.
- Assert `.m4a` was deleted (delete_audio_after=true).

### T7 — Whisper rc != 0 → none + cleanup
- Fake yt-dlp succeeds, fake whisper returns rc=1 with stderr.
- Assert return `("","none")`, audio file removed.

### T8 — Whisper output below min_chars → none
- Fake whisper writes a 50-char file, `min_chars=200`.
- Assert return `("","none")`, no `.txt` in canonical location with that short content (or assert it was removed/overwritten — pick one: **remove**).

### T9 — Timeout handling
- Fake `subprocess.run` raises `subprocess.TimeoutExpired` on whisper call.
- Assert returns `("","none")` without exception escaping.

### T10 — Logger redaction
- Configure `cookie_file` path containing a unique sentinel string; have fake whisper stderr include the path and a `Cookie:` header line.
- Capture all logger calls; assert sentinel and `Cookie:` are NOT in any logged message.

### T11 — `purge_transcript` removes audio + transcript
- Touch `{vid}.m4a`, `{vid}.txt`, `{vid}.vtt` in cache dir, call `purge_transcript(retain=False)`, assert all removed.

### Existing tests
- `test_yt_dlp_uses_cookie_file_when_present` and `test_yt_dlp_uses_browser_cookies_when_cookie_file_missing` must continue passing unchanged (only subtitle-fallback path).

---

## 8. Verification commands

Run from repo root with the project venv:

```bash
# 1. Unit tests (whisper-fallback class + plugin discovery)
.venv/bin/python -m unittest discover -s plugins/youtube_agent_watch/tests -t . -v

# 2. Targeted file
.venv/bin/python -m unittest plugins.youtube_agent_watch.tests.test_transcripts -v

# 3. Strict watcher healthcheck (must already exist; if entry point is python -m)
.venv/bin/python -m plugins.youtube_agent_watch.watcher --healthcheck --strict

# 4. Optional offline smoke: drop a small .m4a fixture, point binary at /bin/echo wrapper that
#    writes a stub .txt, and confirm fetch_whisper_fallback returns ("...","whisper-fallback").
#    This is a manual one-off, not part of CI.
.venv/bin/python - <<'PY'
from pathlib import Path
from plugins.youtube_agent_watch.transcripts import fetch_whisper_fallback
# ... craft config pointing at a script that simulates whisper ...
PY

# 5. Live network smoke (manual, off CI, after merge)
.venv/bin/yt-dlp --version
/opt/homebrew/bin/whisper --help | head -5
.venv/bin/python -m plugins.youtube_agent_watch.watcher --once --video <known-blocked-id>
```

CI requirement: only **#1 and #2** must pass for merge. #3 if healthcheck CLI exists.

---

## 9. Rollout & guardrails

- Land config block first (defaults enabled), but new `fetch_whisper_fallback` is invoked only when `enabled` is truthy AND binary is present — so machines without whisper degrade silently.
- Add a one-line entry to plugin README noting the new fallback and how to disable (`ingest.transcript.whisper_fallback.enabled: false`).
- Telemetry/log line per invocation: `whisper-fallback used for {video_id} model={model} duration_ms={x}` so we can audit how often we're falling all the way through.
- Follow-up ticket: extractor / Obsidian writer should annotate `whisper-fallback` provenance distinctly (per youtube-content skill rule); explicitly out of scope here.

---

## 10. Open questions for the parent agent

1. Should `fetch_transcript` accept an explicit `transcript_source_pref` param so callers can force-skip whisper for cheap dry-runs? **Recommend: no in v1**, use config flag.
2. Should we add a per-creator override? **Recommend: no in v1.** Add later if cost/runtime becomes an issue.
3. Is `small.en` acceptable as default, or prefer `base.en` for faster first-run on new machines? **Recommend: small.en**, tuneable.
