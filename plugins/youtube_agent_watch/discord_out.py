from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DiscordMessage:
    channel: str
    content: str
    dry_run: bool = True
    warning: str | None = None


class DiscordNoopSender:
    """Log-only Discord sender used for dry runs and fallback planning."""

    def __init__(self, config: dict[str, Any], *, dry_run: bool = True, logger=print, known_channels: set[str] | None = None):
        self.config = config
        self.dry_run = dry_run
        self.logger = logger
        self.known_channels = known_channels or {config.get("discord", {}).get("fallback_channel", "ai-research")}

    def resolve_channel(self, target: str) -> tuple[str, str | None]:
        if target in self.known_channels:
            return target, None
        fallback = self.config.get("discord", {}).get("fallback_channel", "ai-research")
        warning = f"⚠️ target #{target} missing — falling back. Create channel to enable proper routing."
        return fallback, warning

    def send(self, target: str, content: str) -> dict[str, Any]:
        channel, warning = self.resolve_channel(target)
        prefix = "🧪 DRY RUN " if self.dry_run else "📋 POST PLAN LOG_ONLY "
        final = f"{prefix}{warning}\n{content}" if warning else f"{prefix}{content}"
        self.logger(f"DISCORD[{channel}]: {final[:1800]}")
        return {"channel": channel, "id": "log-only", "warning": warning, "dry_run": self.dry_run, "delivery_mode": "log_only"}


class DiscordRestSender:
    """Minimal Discord REST sender for scheduled watcher posts.

    Uses the bot token already configured for Hermes Gateway. It resolves channel
    names directly from Discord instead of relying on the gateway target cache, so
    newly created watcher channels can receive cron output immediately.
    """

    api_base = "https://discord.com/api/v10"

    def __init__(self, config: dict[str, Any], *, dry_run: bool = False, logger=print):
        self.config = config
        self.dry_run = dry_run
        self.logger = logger
        self.discord_cfg = config.get("discord", {})
        load_local_env()
        token_env = self.discord_cfg.get("bot_token_env", "DISCORD_BOT_TOKEN")
        self.token = os.environ.get(token_env)
        if not self.token:
            raise RuntimeError(f"Discord bot token env var {token_env} is not set")
        self.guild_id = self._resolve_guild_id()
        self._channels_by_name: dict[str, dict[str, Any]] | None = None

    def send(self, target: str, content: str) -> dict[str, Any]:
        channel, warning = self.resolve_channel(target)
        final = f"{warning}\n{content}" if warning else content
        if self.dry_run:
            self.logger(f"DISCORD_DRY_RUN[{channel['name']}]: {final[:1800]}")
            return {"channel": channel["name"], "id": "dry-run", "warning": warning, "dry_run": True, "delivery_mode": "discord"}
        message = self._request("POST", f"/channels/{channel['id']}/messages", {"content": trim_discord_message(final)})
        self.logger(f"DISCORD_SENT[{channel['name']}]: {message.get('id')}")
        return {"channel": channel["name"], "id": message.get("id"), "warning": warning, "dry_run": False, "delivery_mode": "discord"}

    def resolve_channel(self, target: str) -> tuple[dict[str, Any], str | None]:
        channels = self.channels_by_name()
        if target in channels:
            return channels[target], None
        if self.discord_cfg.get("auto_create_channels"):
            created = self.create_channel(target)
            self._channels_by_name = None
            return created, None
        fallback = self.discord_cfg.get("fallback_channel", "ai-research")
        if fallback not in channels:
            raise RuntimeError(f"Discord channel #{target} missing and fallback #{fallback} missing")
        warning = f"⚠️ target #{target} missing — falling back. Create channel to enable proper routing."
        return channels[fallback], warning

    def channels_by_name(self) -> dict[str, dict[str, Any]]:
        if self._channels_by_name is None:
            channels = self._request("GET", f"/guilds/{self.guild_id}/channels")
            self._channels_by_name = {c["name"]: c for c in channels if c.get("type") == 0}
        return self._channels_by_name

    def create_channel(self, name: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "type": 0}
        category_name = self.discord_cfg.get("category_name") or "AI Agent Research"
        category = self.find_or_create_category(category_name)
        if category:
            payload["parent_id"] = category["id"]
        return self._request("POST", f"/guilds/{self.guild_id}/channels", payload)

    def find_or_create_category(self, name: str) -> dict[str, Any] | None:
        channels = self._request("GET", f"/guilds/{self.guild_id}/channels")
        existing = next((c for c in channels if c.get("type") == 4 and c.get("name") == name), None)
        if existing:
            return existing
        if not self.discord_cfg.get("auto_create_channels"):
            return None
        return self._request("POST", f"/guilds/{self.guild_id}/channels", {"name": name, "type": 4})

    def _resolve_guild_id(self) -> str:
        guild_id_env = self.discord_cfg.get("guild_id_env", "DISCORD_GUILD_ID")
        guild_id = os.environ.get(guild_id_env) or self.discord_cfg.get("guild_id")
        if guild_id:
            return str(guild_id)
        guild_hint = self.discord_cfg.get("guild_hint")
        guilds = self._request("GET", "/users/@me/guilds")
        if guild_hint:
            match = next((g for g in guilds if g.get("name") == guild_hint), None)
            if match:
                return str(match["id"])
        if len(guilds) == 1:
            return str(guilds[0]["id"])
        raise RuntimeError("DISCORD_GUILD_ID is not set and guild_hint did not uniquely resolve")

    def _request(self, method: str, path: str, payload: Any | None = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json", "User-Agent": "HermesYoutubeWatch/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")[:500]
            raise RuntimeError(f"Discord API {method} {path} failed with HTTP {exc.code}: {body}") from exc


def make_discord_sender(config: dict[str, Any], *, dry_run: bool = False, logger=print):
    if dry_run or config.get("discord", {}).get("delivery_mode", "log_only") != "discord":
        return DiscordNoopSender(config, dry_run=dry_run, logger=logger)
    return DiscordRestSender(config, dry_run=dry_run, logger=logger)


def load_local_env() -> None:
    candidates = [
        Path("/Users/junior/junior-agent/.hermes/.env"),
        Path.home() / "junior-agent" / ".hermes" / ".env",
        Path.home() / ".hermes" / ".env",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def trim_discord_message(content: str) -> str:
    if len(content) <= 2000:
        return content
    return content[:1950].rstrip() + "\n\n… truncated"
