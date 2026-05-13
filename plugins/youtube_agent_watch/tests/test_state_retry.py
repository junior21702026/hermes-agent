from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.youtube_agent_watch.state import StateStore


VIDEO = {
    "video_id": "abc123",
    "creator_id": "creator",
    "title": "Test Video",
    "url": "https://youtube.com/watch?v=abc123",
    "upload_date": "20260512",
    "duration_s": 600,
}


class StateRetryTests(unittest.TestCase):
    def test_transcript_blocked_seen_only_video_is_not_considered_done(self):
        with tempfile.TemporaryDirectory() as td:
            state = StateStore(Path(td) / "state.db")
            state.upsert_creators([{"id": "creator", "name": "Creator", "handle": "@creator", "weight": 1.0}])
            state.queue_video(VIDEO)
            state.record_result(
                "abc123",
                status="seen_only",
                score=1.0,
                score_band="seen",
                transcript_chars=0,
                transcript_source="none",
                extract_path="abc123.json",
                topics=[],
            )

            self.assertFalse(state.seen("abc123"))
            state.close()

    def test_transcript_backed_seen_only_video_is_considered_done(self):
        with tempfile.TemporaryDirectory() as td:
            state = StateStore(Path(td) / "state.db")
            state.upsert_creators([{"id": "creator", "name": "Creator", "handle": "@creator", "weight": 1.0}])
            state.queue_video(VIDEO)
            state.record_result(
                "abc123",
                status="seen_only",
                score=1.0,
                score_band="seen",
                transcript_chars=1200,
                transcript_source="yt-dlp-auto",
                extract_path="abc123.json",
                topics=[],
            )

            self.assertTrue(state.seen("abc123"))
            state.close()


if __name__ == "__main__":
    unittest.main()
