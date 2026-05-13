from __future__ import annotations

import unittest

from plugins.youtube_agent_watch.config import DEFAULT_CONFIG
from plugins.youtube_agent_watch.feeds import filter_candidates


class DummyState:
    def __init__(self, seen_ids: set[str] | None = None):
        self.seen_ids = seen_ids or set()

    def seen(self, video_id: str) -> bool:
        return video_id in self.seen_ids


class FeedFixtureTests(unittest.TestCase):
    def test_filter_skips_no_duration_videos(self):
        videos = [
            {"video_id": "missing", "creator_id": "c", "title": "missing duration", "duration_s": 0},
            {"video_id": "valid", "creator_id": "c", "title": "valid", "duration_s": 600},
        ]

        out = filter_candidates(videos, DEFAULT_CONFIG, DummyState())

        self.assertEqual([v["video_id"] for v in out], ["valid"])

    def test_filter_skips_seen_videos(self):
        videos = [{"video_id": "seen", "creator_id": "c", "title": "seen", "duration_s": 600}]

        self.assertEqual(filter_candidates(videos, DEFAULT_CONFIG, DummyState({"seen"})), [])


if __name__ == "__main__":
    unittest.main()
