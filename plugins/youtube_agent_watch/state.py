from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
  id TEXT PRIMARY KEY,
  name TEXT,
  handle TEXT,
  weight REAL,
  last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  creator_id TEXT NOT NULL REFERENCES creators(id),
  title TEXT,
  url TEXT,
  upload_date TEXT,
  duration_s INTEGER,
  first_seen_at TEXT,
  status TEXT CHECK(status IN ('queued','extracted','routed','failed','skipped','seen_only')),
  score REAL,
  score_band TEXT CHECK(score_band IN ('archive','short','seen','below')),
  transcript_chars INTEGER,
  transcript_source TEXT,
  extract_attempts INTEGER DEFAULT 0,
  extract_path TEXT,
  routed_at TEXT,
  obsidian_note_path TEXT,
  discord_message_ids TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_creator ON videos(creator_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_score ON videos(score);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT, finished_at TEXT,
  candidates INTEGER, extracted INTEGER, routed INTEGER, errors INTEGER,
  report_path TEXT
);
CREATE TABLE IF NOT EXISTS topics (
  video_id TEXT REFERENCES videos(video_id),
  topic TEXT,
  PRIMARY KEY(video_id, topic)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_creators(self, creators: Iterable[dict[str, Any]]) -> None:
        with self.conn:
            for c in creators:
                self.conn.execute(
                    "INSERT INTO creators(id,name,handle,weight,last_checked_at) VALUES(?,?,?,?,COALESCE((SELECT last_checked_at FROM creators WHERE id=?), NULL)) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, handle=excluded.handle, weight=excluded.weight",
                    (c["id"], c.get("name"), c.get("handle"), c.get("weight", 1.0), c["id"]),
                )

    def mark_creator_checked(self, creator_id: str) -> None:
        self.conn.execute("UPDATE creators SET last_checked_at=? WHERE id=?", (utc_now(), creator_id))
        self.conn.commit()

    def seen(self, video_id: str) -> bool:
        row = self.conn.execute("SELECT status, transcript_chars, transcript_source FROM videos WHERE video_id=?", (video_id,)).fetchone()
        if row is None:
            return False
        if row["status"] in {"queued", "failed"}:
            return False
        if (row["transcript_source"] or "none") == "none" and int(row["transcript_chars"] or 0) == 0:
            return False
        return True

    def queue_video(self, video: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO videos(video_id,creator_id,title,url,upload_date,duration_s,first_seen_at,status) VALUES(?,?,?,?,?,?,?,?)",
                (video["video_id"], video["creator_id"], video.get("title"), video.get("url"), video.get("upload_date"), video.get("duration_s"), utc_now(), "queued"),
            )

    def record_result(self, video_id: str, *, status: str, score: float | None, score_band: str, transcript_chars: int, transcript_source: str, extract_path: str | None, topics: list[str], obsidian_note_path: str | None = None, discord_messages: list[dict[str, Any]] | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE videos SET status=?, score=?, score_band=?, transcript_chars=?, transcript_source=?, extract_attempts=COALESCE(extract_attempts, 0)+1, extract_path=?, routed_at=?, obsidian_note_path=?, discord_message_ids=? WHERE video_id=?",
                (status, score, score_band, transcript_chars, transcript_source, extract_path, utc_now() if status == "routed" else None, obsidian_note_path, json.dumps(discord_messages or []), video_id),
            )
            self.conn.execute("DELETE FROM topics WHERE video_id=?", (video_id,))
            for topic in topics:
                self.conn.execute("INSERT OR IGNORE INTO topics(video_id, topic) VALUES(?,?)", (video_id, topic))

    def start_run(self, run_id: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO runs(run_id,started_at,candidates,extracted,routed,errors) VALUES(?,?,?,?,?,?)", (run_id, utc_now(), 0, 0, 0, 0))
        self.conn.commit()

    def finish_run(self, run_id: str, *, candidates: int, extracted: int, routed: int, errors: int, report_path: str) -> None:
        self.conn.execute("UPDATE runs SET finished_at=?, candidates=?, extracted=?, routed=?, errors=?, report_path=? WHERE run_id=?", (utc_now(), candidates, extracted, routed, errors, report_path, run_id))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
