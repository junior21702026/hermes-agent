from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).with_name("templates")


def normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10] or "unknown-date"


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:80] or "untitled"


class ObsidianWriter:
    def __init__(self, config: dict[str, Any], *, dry_run: bool = False):
        obs = config["obsidian"]
        if dry_run:
            base = Path(config["verification"].get("dry_run_writes_to", "/tmp/yt-watch-dryrun")) / "obsidian"
        else:
            base = Path(obs["vault_path"]) / obs["base_folder"]
        self.base = base
        self.config = config
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(default=False))

    def ensure_stubs(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        files = self.config["obsidian"]["files"]
        defaults = {
            files["index"]: "# AI Agent YouTube Watch Index\n\n| Date | Creator | Title | Score | Topics | Note |\n|------|---------|-------|-------|--------|------|\n",
            files["extracted"]: "# Extracted Learnings\n\n",
            files["automations"]: "# Automation Ideas\n\n",
            files["skills"]: "# Hermes Skills To Build\n\n",
        }
        for rel, content in defaults.items():
            path = self.base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        (self.base / self.config["obsidian"].get("per_creator_folder", "Creators")).mkdir(exist_ok=True)

    def write_video(self, extraction: dict[str, Any]) -> str:
        self.ensure_stubs()
        creator = extraction.get("creator_name") or extraction.get("creator_id", "Unknown")
        date = normalize_date(extraction.get("upload_date") or extraction.get("extracted_at"))
        title_slug = slugify(extraction.get("title", "Untitled")).replace("-", " ").title()
        rel = Path(self.config["obsidian"].get("per_creator_folder", "Creators")) / creator / f"{date} — {title_slug}.md"
        path = self.base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        template = self.env.get_template("obsidian_video_note.md.j2")
        path.write_text(template.render(e=extraction), encoding="utf-8")
        self.append_indexes(extraction, rel.with_suffix(""))
        return str(path)

    def append_indexes(self, extraction: dict[str, Any], note_rel_no_suffix: Path) -> None:
        files = self.config["obsidian"]["files"]
        row = self.env.get_template("obsidian_index_row.md.j2").render(e=extraction, note=str(note_rel_no_suffix))
        self._append_once(self.base / files["index"], row, extraction["video_id"])
        bullet = f"- {extraction.get('extracted_at','')[:10]} — **{extraction.get('title')}** ({extraction.get('score')}) — {extraction.get('url')} <!-- {extraction['video_id']} -->\n"
        self._append_once(self.base / files["extracted"], bullet, extraction["video_id"])
        topics = set(extraction.get("topics", []))
        if "automation_ideas" in topics:
            self._append_once(self.base / files["automations"], bullet, extraction["video_id"])
        if "skills_to_build" in topics:
            self._append_once(self.base / files["skills"], bullet, extraction["video_id"])

    @staticmethod
    def _append_once(path: Path, text: str, marker: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if marker not in existing:
            with path.open("a", encoding="utf-8") as f:
                f.write(text if text.endswith("\n") else text + "\n")
