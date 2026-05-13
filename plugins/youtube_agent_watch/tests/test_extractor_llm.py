from __future__ import annotations

import json
import unittest
from copy import deepcopy

from plugins.youtube_agent_watch.config import DEFAULT_CONFIG
from plugins.youtube_agent_watch.extractor import (
    extract_operational_signal,
    extract_operational_signal_llm,
    parse_json_object,
)


VIDEO = {
    "video_id": "abc123",
    "creator_id": "matthew-berman",
    "creator_name": "Matthew Berman",
    "title": "Build an n8n Claude Code agent workflow",
    "duration_s": 1200,
    "upload_date": "2026-05-01",
    "transcript_source": "fixture",
}
TRANSCRIPT = "Use n8n as a trigger, call OpenAI, then hand a repo task to Claude Code."


class LLMExtractorTests(unittest.TestCase):
    def llm_config(self):
        config = deepcopy(DEFAULT_CONFIG)
        config["extraction"]["mode"] = "llm"
        return config

    def test_default_mode_stays_heuristic_stub(self):
        extraction = extract_operational_signal(VIDEO, TRANSCRIPT, deepcopy(DEFAULT_CONFIG))

        self.assertEqual(extraction["model"], "heuristic-local-stub")
        self.assertNotEqual(extraction.get("extraction_mode"), "llm")

    def test_parse_json_object_strips_fences_and_ignores_surrounding_text(self):
        raw = "notes before\n```json\n" + json.dumps({"topics": ["workflows"]}) + "\n```\nnotes after"

        self.assertEqual(parse_json_object(raw), {"topics": ["workflows"]})

    def test_llm_mode_normalizes_metadata_and_removes_score_fields(self):
        def fake_llm(_prompt, _llm_cfg):
            return json.dumps(
                {
                    "video_id": "model-tried-to-change-it",
                    "creator_id": "wrong",
                    "title": "wrong",
                    "topics": ["workflows", "automation_ideas", "not_allowed"],
                    "hype_vs_actionable": "actionable",
                    "tldr": ["n8n trigger to OpenAI to Claude Code handoff."],
                    "workflows": [{"title": "Agent handoff", "steps": ["Trigger in n8n", "Call OpenAI", "Create Claude Code task"], "stack": ["n8n", "OpenAI", "Claude Code"], "copy_difficulty": "medium"}],
                    "automations_for_small_business": [],
                    "tools_models_stacks": [{"name": "n8n", "role": "trigger", "first_party": False}],
                    "prompts_and_patterns": [],
                    "hermes_openclaw_codex_ideas": [{"kind": "workflow", "name": "Hermes video-to-task router", "rationale": "Maps video ideas to agent tasks."}],
                    "claims": [],
                    "score": 10,
                    "score_band": "archive",
                    "score_reasons": ["model must not control scoring"],
                }
            )

        extraction = extract_operational_signal_llm(VIDEO, TRANSCRIPT, self.llm_config(), llm_call=fake_llm)

        self.assertEqual(extraction["video_id"], "abc123")
        self.assertEqual(extraction["creator_id"], "matthew-berman")
        self.assertEqual(extraction["title"], VIDEO["title"])
        self.assertEqual(extraction["model"], "openai-codex/gpt-5.4-mini")
        self.assertEqual(extraction["extraction_mode"], "llm")
        self.assertNotIn("score", extraction)
        self.assertNotIn("score_band", extraction)
        self.assertEqual(extraction["topics"], ["workflows", "automation_ideas"])
        self.assertIn("Extracted Learnings.md", extraction["obsidian_targets"])

    def test_llm_failure_falls_back_to_heuristic_with_error_note(self):
        def failing_llm(_prompt, _llm_cfg):
            raise RuntimeError("provider unavailable")

        extraction = extract_operational_signal_llm(VIDEO, TRANSCRIPT, self.llm_config(), llm_call=failing_llm)

        self.assertIn("llm_failed", extraction["model"])
        self.assertEqual(extraction["extraction_mode"], "llm_fallback_heuristic")
        self.assertIn("RuntimeError: provider unavailable", extraction["llm_error"])
        self.assertIn("workflows", extraction["topics"])


if __name__ == "__main__":
    unittest.main()
