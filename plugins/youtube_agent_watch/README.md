# YouTube Agent Watch

Pragmatic watcher for AI-agent YouTube channels. It fetches recent uploads with `yt-dlp`, fetches transcripts with `youtube-transcript-api`/auto-sub fallback, extracts operational learning signals, scores them, and routes dry-run outputs to local logs/Obsidian stubs.

## Commands

```bash
python -m plugins.youtube_agent_watch.watcher healthcheck          # lenient/local review
python -m plugins.youtube_agent_watch.watcher healthcheck --strict # pre-cron gate
python -m plugins.youtube_agent_watch.watcher run --dry-run --max-videos 0
python -m plugins.youtube_agent_watch.watcher run --dry-run --creators matthew-berman --max-videos 1
```

## Runtime safety

- `extraction.mode` defaults to `heuristic_stub`. Dry-runs may route normally, but non-dry-run archive routing (`score >= 8`) is blocked unless `extraction.mode: llm` is configured or the operator explicitly passes `--allow-heuristic-live`.
- Discord is `log_only`: the watcher writes post plans to logs/reports; the parent Hermes cron/agent should deliver real Discord messages until a Discord gateway tool is integrated.
- Videos with missing/zero duration are skipped so unattended cron does not process unknown-length uploads.
- `--schedule evening` writes a weekly synthesis stub automatically on the configured weekly digest day (Sunday by default). `--weekly` forces the stub.

## Cron scheduling via Hermes

Cron is intentionally **not** created by plugin code and this repo should not hand-write `cron/jobs.json`. After strict healthcheck passes, ask the parent Hermes agent to use its cronjob tool. A ready prompt is in `prompts/cron_schedule.md`.

Suggested commands for jobs:

```bash
cd /Users/junior/junior-agent/hermes-agent && python -m plugins.youtube_agent_watch.watcher run --schedule morning --max-videos 10
cd /Users/junior/junior-agent/hermes-agent && python -m plugins.youtube_agent_watch.watcher run --schedule evening --max-videos 10
```

## Dependency notes

If healthcheck reports missing dependencies, install them into the Python environment that runs Hermes:

```bash
python -m pip install 'yt-dlp>=2024.10.0' 'youtube-transcript-api>=0.6.2' 'jinja2>=3.1' 'PyYAML>=6.0'
```

Healthcheck supports a system `yt-dlp` binary (`ingest.yt_dlp_path`) plus Python import checks and prints configured channel inventory for review.

## Notes

- Package path is `plugins/youtube_agent_watch` (underscore) rather than the spec's hyphenated display name so Python imports work.
- No Discord channels are auto-created. Missing/unknown channels fall back to `#ai-research` in dry-run/no-op logs.
- No media is downloaded. Raw transcripts are purged unless score is at or above the configured retain threshold.
- Cron jobs are intentionally not created by this implementation pass.
