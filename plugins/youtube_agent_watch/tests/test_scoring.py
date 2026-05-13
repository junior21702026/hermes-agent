from __future__ import annotations

import unittest

from plugins.youtube_agent_watch.config import DEFAULT_CONFIG
from plugins.youtube_agent_watch.extractor import extract_operational_signal
from plugins.youtube_agent_watch.scoring import score_band, score_extraction


class ScoringTests(unittest.TestCase):
    def rich_extraction(self):
        return {
            "duration_s": 1200,
            "topics": ["workflows", "automation_ideas", "skills_to_build", "tool_stack"],
            "workflows": [{"title": "demo", "steps": ["a", "b", "c"], "stack": ["n8n", "Claude Code"]}],
            "automations_for_small_business": [{"use_case": "lead routing", "trigger": "form submit", "tools": ["n8n"], "estimated_value": "faster response"}],
            "hermes_openclaw_codex_ideas": [{"kind": "skill", "name": "x", "rationale": "Create a reusable Hermes skill that monitors failures and patches the workflow automatically."}],
            "tools_models_stacks": [{"name": "n8n", "role": "orchestrator"}, {"name": "Claude Code", "role": "coding agent"}],
            "prompts_and_patterns": [{"name": "loop", "snippet": "Use a planner executor critic loop with explicit success criteria."}],
            "claims": [],
            "hype_vs_actionable": "actionable",
            "verification": {"confidence": "not_run"},
        }

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
        scored = score_extraction(self.rich_extraction(), DEFAULT_CONFIG, transcript_missing=True)

        self.assertLessEqual(scored["score"], 5)
        self.assertEqual(scored["score_band"], "seen")
        self.assertIn("transcript_missing", scored["score_caps_applied"])

    def test_score_band_boundaries(self):
        self.assertEqual(score_band(9.2, DEFAULT_CONFIG), "archive")
        self.assertEqual(score_band(6.5, DEFAULT_CONFIG), "short")
        self.assertEqual(score_band(4.0, DEFAULT_CONFIG), "seen")

    def test_empty_and_empty_dict_workflow_are_low_signal(self):
        extraction = {"duration_s": 1200, "topics": [], "workflows": [{}], "automations_for_small_business": [], "hermes_openclaw_codex_ideas": [], "tools_models_stacks": [], "prompts_and_patterns": [], "hype_vs_actionable": "actionable", "claims": []}
        scored = score_extraction(extraction, DEFAULT_CONFIG)
        self.assertLessEqual(scored["score"], 4.0)
        self.assertEqual(scored["score_band"], "seen")
        self.assertFalse(scored["score_inputs"]["substantial_workflow"])
        self.assertTrue(scored["score_reasons"])

    def test_unverified_stub_with_claims_caps_at_85_and_reason_included(self):
        extraction = self.rich_extraction()
        extraction["claims"] = [{"claim": "This beats all prior agents"}]
        extraction["verification"] = {"confidence": "unverified_stub"}
        scored = score_extraction(extraction, DEFAULT_CONFIG)
        self.assertLessEqual(scored["score"], 8.5)
        self.assertIn("unverified_stub_with_claims", scored["score_caps_applied"])
        self.assertIn("Researcher verification pending; capped at 8.5.", scored["score_reasons"])
        self.assertLessEqual(len(scored["score_reasons"]), 4)

    def test_unverified_stub_no_claims_and_not_run_claim_caps(self):
        extraction = self.rich_extraction()
        extraction["verification"] = {"confidence": "unverified_stub"}
        scored = score_extraction(extraction, DEFAULT_CONFIG)
        self.assertLessEqual(scored["score"], 9.0)
        self.assertIn("unverified_stub_no_claims", scored["score_caps_applied"])

        extraction = self.rich_extraction()
        extraction["claims"] = [{"claim": "Benchmarks doubled"}]
        extraction["verification"] = {"confidence": "not_run"}
        scored = score_extraction(extraction, DEFAULT_CONFIG)
        self.assertLessEqual(scored["score"], 9.0)
        self.assertIn("not_run_with_unverified_claims", scored["score_caps_applied"])

    def test_ten_requires_high_confidence_multi_signal(self):
        extraction = self.rich_extraction()
        extraction["verification"] = {"confidence": "verified"}
        scored = score_extraction(extraction, DEFAULT_CONFIG)
        self.assertGreaterEqual(scored["score"], 8)
        self.assertTrue(scored["score_inputs"]["substantial_workflow"])
        self.assertTrue(scored["score_inputs"]["substantial_automation"])
        self.assertTrue(scored["score_inputs"]["substantial_hermes_idea"])

        weak = self.rich_extraction()
        weak["workflows"] = []
        weak["automations_for_small_business"] = []
        weak["verification"] = {"confidence": "verified"}
        scored_weak = score_extraction(weak, DEFAULT_CONFIG)
        self.assertLessEqual(scored_weak["score"], 9.7)


if __name__ == "__main__":
    unittest.main()
