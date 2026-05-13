from __future__ import annotations

import unittest

from plugins.youtube_agent_watch.config import DEFAULT_CONFIG
from plugins.youtube_agent_watch.extractor import extract_operational_signal
from plugins.youtube_agent_watch.scoring import score_band, score_extraction


class ScoringTests(unittest.TestCase):
    def test_actionable_transcript_scores_archive_band(self):
        video = {
            "video_id": "abc123",
            "creator_id": "matthew-berman",
            "creator_name": "Matthew Berman",
            "title": "Build an n8n Claude Code agent workflow",
            "duration_s": 1200,
        }
        transcript = (
            "This workflow shows a step by step agent loop. "
            "Use n8n as the trigger, call the OpenAI API, then hand off to Claude Code. "
            "The automation updates GitHub and sends a prompt to the agent."
        )
        extraction = extract_operational_signal(video, transcript, DEFAULT_CONFIG)
        scored = score_extraction(extraction, DEFAULT_CONFIG)

        self.assertGreaterEqual(scored["score"], 8)
        self.assertEqual(scored["score_band"], "archive")
        self.assertTrue({"workflows", "automation_ideas", "skills_to_build", "tool_stack"} <= set(scored["topics"]))

    def test_transcript_missing_caps_score_at_five(self):
        extraction = {
            "duration_s": 1200,
            "topics": ["workflows", "automation_ideas", "skills_to_build", "tool_stack"],
            "workflows": [{"title": "demo", "steps": ["a"], "stack": ["n8n"]}],
            "automations_for_small_business": [{"use_case": "lead routing"}],
            "hermes_openclaw_codex_ideas": [{"kind": "skill", "name": "x"}],
            "tools_models_stacks": [{"name": "n8n"}],
            "hype_vs_actionable": "actionable",
        }
        scored = score_extraction(extraction, DEFAULT_CONFIG, transcript_missing=True)

        self.assertLessEqual(scored["score"], 5)
        self.assertEqual(scored["score_band"], "seen")

    def test_score_band_boundaries(self):
        self.assertEqual(score_band(9.2, DEFAULT_CONFIG), "archive")
        self.assertEqual(score_band(6.5, DEFAULT_CONFIG), "short")
        self.assertEqual(score_band(4.0, DEFAULT_CONFIG), "seen")


if __name__ == "__main__":
    unittest.main()
