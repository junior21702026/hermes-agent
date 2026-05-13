# YouTube Agent Watch — Hermes cron prompt wrapper

Use this prompt with Hermes cron tooling after `python -m plugins.youtube_agent_watch.watcher healthcheck --strict` passes. Do not hand-edit `cron/jobs.json` for this plugin.

Suggested parent-agent prompt:

```text
Use the Hermes cronjob tool to schedule YouTube Agent Watch. Create two recurring jobs in timezone Australia/Brisbane:
1. Morning watcher: run `cd /Users/junior/junior-agent/hermes-agent && python -m plugins.youtube_agent_watch.watcher run --schedule morning --max-videos 10` at 08:00 daily.
2. Evening watcher: run `cd /Users/junior/junior-agent/hermes-agent && python -m plugins.youtube_agent_watch.watcher run --schedule evening --max-videos 10` at 20:00 daily. The watcher will write a weekly synthesis stub automatically on configured Sunday evening runs.

Before enabling either job, run strict healthcheck and a dry run smoke test:
- `python -m plugins.youtube_agent_watch.watcher healthcheck --strict`
- `python -m plugins.youtube_agent_watch.watcher run --dry-run --max-videos 0`

Keep Discord delivery in parent-agent/log-only mode until a Discord gateway tool is integrated.
```
