from __future__ import annotations

import unittest

from plugins.youtube_agent_watch.router import render_discord_card


class RenderDiscordCardTests(unittest.TestCase):
    def sample(self):
        return {
            "creator_name": "Nate Herk",
            "creator_id": "nate-herk",
            "title": "Hermes Agent Course",
            "score": 10,
            "topics": ["automation_ideas", "workflows", "tool_stack"],
            "url": "https://youtube.com/watch?v=abc",
            "tldr": ["Use Hermes as an operational assistant.", "Turn repeated prompts into skills."],
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
        }

    def test_full_card_contains_operational_sections(self):
        card = render_discord_card(self.sample(), mode="full")
        self.assertIn("Core learnings", card)
        self.assertIn("Workflows to copy", card)
        self.assertIn("Small-business automations", card)
        self.assertIn("Hermes follow-ups", card)
        self.assertLessEqual(len(card), 1900)

    def test_topic_card_uses_topic_specific_content(self):
        card = render_discord_card(self.sample(), mode="topic", topic="automation_ideas")
        self.assertIn("Automation Ideas", card)
        self.assertIn("Daily AI briefing", card)
        self.assertLessEqual(len(card), 1900)


if __name__ == "__main__":
    unittest.main()
