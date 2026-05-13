from __future__ import annotations

import copy
import unittest

from plugins.youtube_agent_watch.config import DEFAULT_CONFIG
from plugins.youtube_agent_watch.router import (
    bullet_lines,
    format_idea,
    format_pattern,
    format_workflow,
    render_discord_card,
    route_extraction,
    route_plan,
)
from plugins.youtube_agent_watch.text_quality import normalize_hermes_terms


class RenderDiscordCardTests(unittest.TestCase):
    def sample(self):
        return {
            "video_id": "abc",
            "creator_name": "Nate Herk",
            "creator_id": "nate-herk",
            "title": "Hermes Agent Course",
            "score": 10,
            "topics": ["automation_ideas", "workflows", "tool_stack"],
            "url": "https://youtube.com/watch?v=abc",
            "tldr": ["Use Hermes Agent as an operational assistant.", "Turn repeated prompts into skills."],
            "workflows": [
                {
                    "title": "Deploy Hermes",
                    "steps": ["Provision VPS", "Install Docker", "Connect Telegram", "Verify reply"],
                    "stack": ["Hermes", "Docker", "Telegram"],
                    "copy_difficulty": "medium",
                }
            ],
            "automations_for_small_business": [
                {"use_case": "Daily AI briefing", "trigger": "morning cron", "tools": ["Hermes", "Discord"], "estimated_value": "saves review time"}
            ],
            "tools_models_stacks": [{"name": "Hermes", "role": "agent runtime"}],
            "prompts_and_patterns": [{"name": "Skill loop", "snippet": "Patch skills after repeated failures."}],
            "hermes_openclaw_codex_ideas": [{"kind": "skill", "name": "backup-loop", "rationale": "protect state"}],
            "claims": [],
            "hype_vs_actionable": "actionable",
            "verification": {"confidence": "not_run"},
            "transcript_source": "whisper-fallback",
        }

    def test_full_card_contains_operational_sections(self):
        card = render_discord_card(self.sample(), mode="full")
        self.assertIsNotNone(card)
        assert card is not None
        self.assertIn("Core learnings", card)
        self.assertIn("Workflows to copy", card)
        self.assertIn("Small-business automations", card)
        self.assertIn("Hermes follow-ups", card)
        self.assertIn("_Source: whisper-fallback transcript • verification: not run_", card)
        self.assertNotIn("None extracted", card)
        self.assertLessEqual(len(card), 1900)

    def test_topic_card_uses_topic_specific_content(self):
        card = render_discord_card(self.sample(), mode="topic", topic="automation_ideas")
        self.assertIsNotNone(card)
        assert card is not None
        self.assertIn("Automation Ideas", card)
        self.assertIn("Daily AI briefing", card)
        self.assertLessEqual(len(card), 1900)

    def test_empty_sections_are_suppressed_and_empty_full_card_returns_none(self):
        extraction = {**self.sample(), "tldr": [], "workflows": [{}], "automations_for_small_business": [], "tools_models_stacks": [], "prompts_and_patterns": [{"name": "Background computer-use pattern", "snippet": ""}], "hermes_openclaw_codex_ideas": []}
        self.assertEqual(bullet_lines(["", "None", "n/a", "—"], limit=3), [])
        self.assertEqual(format_workflow({}), "")
        self.assertEqual(format_pattern({"name": "Background computer-use pattern", "snippet": ""}), "")
        self.assertIsNone(render_discord_card(extraction, mode="full"))

    def test_internal_kind_label_friendly_mapping_and_no_trailing_dash(self):
        self.assertEqual(format_idea({"kind": "parallel", "name": "slash-goal loop", "rationale": ""}), "**Parallel pattern: slash-goal loop**")
        self.assertEqual(format_idea({"kind": "custom_kind", "name": "x", "rationale": "why"}), "**Custom Kind: x** — why")

    def test_term_normalization_and_short_card(self):
        text = "Kua agent in cua-driver; Open Claw and open-claw and OPEN_CLAW; Claude code; n 8 n; see https://Kua.example/Open Claw"
        normalized = normalize_hermes_terms(text)
        self.assertIn("Cua agent in cua-driver", normalized)
        self.assertIn("OpenClaw and OpenClaw and OpenClaw", normalized)
        self.assertIn("Claude Code", normalized)
        self.assertIn("n8n", normalized)
        self.assertIn("https://Kua.example/Open Claw", normalized)
        self.assertEqual(normalize_hermes_terms(normalized), normalized)
        sample = self.sample()
        sample["title"] = "Kua Open Claw update"
        card = render_discord_card(sample, short=True)
        self.assertIsNotNone(card)
        assert card is not None
        self.assertIn("Cua OpenClaw update", card)
        self.assertGreaterEqual(len(card.splitlines()), 2)

    def test_unverified_footer_and_hype_skip(self):
        sample = self.sample()
        sample["verification"] = {"confidence": "unverified_stub"}
        sample["transcript_source"] = "youtube-transcript-api"
        card = render_discord_card(sample, mode="full")
        self.assertIsNotNone(card)
        assert card is not None
        self.assertIn("verification: unverified (researcher pending)", card)
        self.assertIsNone(render_discord_card(sample, mode="topic", topic="hype"))

    def test_topic_fanout_cap_and_actionable_archive_routes_obsidian(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        sample = self.sample()
        sample.update(
            {
                "score": 9,
                "extracted_at": "2026-05-13T00:00:00+00:00",
                "topics": ["automation_ideas", "workflows", "skills_to_build", "tool_stack", "hype"],
                "claims": [{"claim": "Model beats benchmarks", "status": "unverified"}],
            }
        )
        sinks = route_plan(sample, config)
        topic_sinks = [s for s in sinks if s.get("mode") == "topic"]
        self.assertEqual(len(topic_sinks), 3)
        self.assertTrue(any(s["type"] == "obsidian" for s in sinks))
        result = route_extraction(sample, config, dry_run=True, logger=lambda *_: None)
        self.assertTrue([s for s in result["skipped_sinks"] if s["reason"] == "topic_cap"])

    def test_route_extraction_empty_has_no_sinks(self):
        config = copy.deepcopy(DEFAULT_CONFIG)
        extraction = {"video_id": "empty", "creator_id": "nate-herk", "creator_name": "Nate", "title": "Empty", "score": 8.1, "topics": [], "url": "https://example", "tldr": [], "workflows": [], "automations_for_small_business": [], "tools_models_stacks": [], "prompts_and_patterns": [], "hermes_openclaw_codex_ideas": [], "claims": [], "hype_vs_actionable": "actionable"}
        self.assertIsNone(render_discord_card(extraction, mode="full"))
        result = route_extraction(extraction, config, dry_run=True, logger=lambda *_: None)
        self.assertEqual(result["sinks"], [])
        self.assertTrue(result["skipped_sinks"])


if __name__ == "__main__":
    unittest.main()
