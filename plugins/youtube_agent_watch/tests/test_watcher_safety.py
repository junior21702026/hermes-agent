from __future__ import annotations

import unittest
from copy import deepcopy

from plugins.youtube_agent_watch.config import DEFAULT_CONFIG
from plugins.youtube_agent_watch.watcher import live_safety_allows_routing, should_write_weekly


class WatcherSafetyTests(unittest.TestCase):
    def test_heuristic_archive_blocked_in_live_mode(self):
        extraction = {"score": 9.0}
        config = deepcopy(DEFAULT_CONFIG)
        config["extraction"]["mode"] = "heuristic_stub"

        self.assertFalse(live_safety_allows_routing(extraction, config, dry_run=False, allow_heuristic_live=False))

    def test_heuristic_archive_allowed_in_dry_run_or_override(self):
        extraction = {"score": 9.0}
        config = deepcopy(DEFAULT_CONFIG)

        self.assertTrue(live_safety_allows_routing(extraction, config, dry_run=True, allow_heuristic_live=False))
        self.assertTrue(live_safety_allows_routing(extraction, config, dry_run=False, allow_heuristic_live=True))

    def test_llm_mode_allows_archive_live_routing(self):
        extraction = {"score": 9.0}
        config = deepcopy(DEFAULT_CONFIG)
        config["extraction"]["mode"] = "llm"

        self.assertTrue(live_safety_allows_routing(extraction, config, dry_run=False, allow_heuristic_live=False))

    def test_weekly_only_for_evening_schedule(self):
        self.assertFalse(should_write_weekly("morning", DEFAULT_CONFIG))
        self.assertFalse(should_write_weekly(None, DEFAULT_CONFIG))


if __name__ == "__main__":
    unittest.main()
