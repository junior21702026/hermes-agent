# YouTube Agent Watcher — Discord Output Quality v2 Spec

Status: architect spec, not yet implemented.
Owner: youtube_agent_watch plugin.
Goal: lift average Discord post grade from B-/C+ to A-/B+ and stop spamming
near-identical content to 7+ topic channels. Drive change in the smallest
safe surface area (renderer + scoring + router uniqueness gate). Preserve
all existing watcher functionality and keep the unittest suite green.

References:
- skills/youtube-content/references/youtube-watcher-discord-quality-review.md
- plugins/youtube_agent_watch/docs/whisper_fallback_spec.md (unrelated, just
  mirrors the spec layout we want here)

---

## 1. Files to modify

In-scope (must change):
1. `plugins/youtube_agent_watch/router.py`
   - Add a renderer sanitizer + Hermes-term normalizer.
   - Drop "- None extracted." filler from `bullet_lines` and from
     `format_*` helpers when no real content exists.
   - Add a topic-uniqueness gate to `route_plan` so a topic channel only
     receives a post when the topic-specific body has substantive content.
   - Surface transcript_source / verification confidence as a labeled
     footer (one line, never a bullet).
2. `plugins/youtube_agent_watch/scoring.py`
   - Recalibrate base/weights so 10.0 is reserved for high-confidence
     items with multiple substantial signals.
   - Cap or downgrade scores when verification.confidence == "unverified_stub".
   - Always return non-empty, ordered, deduped `score_reasons` (max 4),
     including the dominant cap reason if a cap was applied.
3. `plugins/youtube_agent_watch/templates/obsidian_video_note.md.j2`
   - Replace `{% else %}- None extracted.` blocks with `{% else %}_(none extracted)_`
     so empty sections collapse into a single italic line instead of a fake bullet.
   - Apply the same Hermes-term normalization on render (via a Jinja filter
     registered in `obsidian.py`).
4. `plugins/youtube_agent_watch/obsidian.py`
   - Register a `hermes_terms` Jinja filter that calls the shared
     `normalize_hermes_terms` helper from `router.py` (or a new
     `text_quality.py` module — see §3).
5. `plugins/youtube_agent_watch/tests/test_router.py`
6. `plugins/youtube_agent_watch/tests/test_scoring.py`
   - Extend with cases covering every behavior contract below.
7. New: `plugins/youtube_agent_watch/text_quality.py`
   - Pure-function helpers shared by router + obsidian. No I/O, no config
     dependency beyond what is passed in. Easy to unit-test in isolation.

Out of scope (do not modify in this change):
- `extractor.py` — keep `unverified_stub` value as-is; consumers downgrade.
- `feeds.py`, `transcripts.py`, `watcher.py`, `state.py`.
- Discord delivery layer (`discord_out.py`).
- Config defaults except adding **new** keys under `scoring` and
  `discord` (additive, backwards compatible). See §5.

---

## 2. Behavior contracts

### 2.1 Renderer quality gate (router.py)

`bullet_lines(items, *, limit)`
- Input: any of `None`, `""`, `[]`, list of scalars/dicts.
- Output: list of `"- <text>"` strings.
- **Contract change:** if no normalized item produces a non-empty,
  non-whitespace, non-placeholder string, return `[]` (NOT
  `["- None extracted."]`). Caller suppresses the section.
- A "placeholder" string is any of: empty, "None", "none", "n/a",
  "unknown", "tbd", "—", "-".

`section_lines(title, formatter, items, *, limit)`
- Already returns `[]` when there are no values. Keep that.
- **New contract:** must call `formatter` then drop entries whose
  rendered string is placeholder OR matches `r"^\*\*[^*]+\*\* — \s*$"`
  (i.e. bolded label with empty body). If after filtering the list is
  empty, return `[]`.

`format_pattern(item)`
- If `snippet`/`instruction`/`description` are all empty, return `""`
  (signals "drop me" to `section_lines`). Never emit `"**Foo** — "`.

`format_idea(item)`
- Replace raw `kind` label rendering with a friendly map:
  - `parallel` → `Parallel pattern`
  - `skill` → `Skill`
  - `agent` → `Agent`
  - `workflow` → `Workflow`
  - `prompt` → `Prompt`
  - any unknown kind → Title-case the value with underscores → spaces.
- Output shape becomes: `**<friendly>: <name>** — <rationale>`.
- If `rationale` empty after normalization, output `**<friendly>: <name>**`
  (no trailing dash). If both `name` and `rationale` empty, return `""`.

`format_workflow(item)`
- If `steps` is empty AND `stack` is empty, return `""`.
- If only `stack` present, output `**<title>** — Stack: …` (no bare " — .").

`format_automation(item)`
- If `use_case` empty and `trigger` empty and `tools` empty, return `""`.
- Replace literal `"unknown"` with `"unspecified"` in user-visible text.

`format_tool(item)`
- If `name` empty, return `""`. If `role` empty, output just `**<name>**`.

`format_claim(item)`
- Unchanged shape, but route through `normalize_hermes_terms` (§2.2).

`render_full_learning_card`, `render_intelligence_card`, `render_topic_card`
- After computing `lines`, before `trim_card`:
  1. Apply `normalize_hermes_terms` to each line.
  2. Collapse runs of >1 blank line to a single blank line.
  3. Drop trailing blank lines.
  4. Append a single **footer** line when applicable (see §2.3).
- If the resulting body (excluding header + footer) is **empty of bullet
  content**, return `None` to signal the router that this card has no
  unique value and should NOT be sent. (Header-only posts are noise.)
  - "Header" = first 4 lines (title, creator/score line, url, blank).
  - `route_extraction` must skip sinks whose card is `None`.

`render_topic_card`
- For non-`hype` topics: if the topic-specific section returned `[]`,
  return `None` (router suppresses).
- For `hype` topic:
  - Only render when `extraction.get("hype_vs_actionable") == "hype"` OR
    `extraction.get("claims")` has ≥1 non-empty claim.
  - Remove the silent "**Signal vs hype** — mixed: No claim details
    extracted." fallback. If neither condition holds, return `None`.

### 2.2 Hermes-term normalization (text_quality.py)

`normalize_hermes_terms(text: str) -> str`
- Pure, idempotent, case-preserving on first letter where reasonable.
- Word-boundary regex replacements (apply in order):
  1. `\bKua\b` → `Cua`
  2. `\bkua-driver\b` → `cua-driver`
  3. `\bComputer Use\b` → `computer-use`
  4. `\bOpen Claw\b` → `OpenClaw`
  5. `\bopen[-_ ]?claw\b` → `OpenClaw` (case-insensitive variant)
  6. `\bClaude code\b` → `Claude Code`
  7. `\bn 8 n\b|\bn-8-n\b` → `n8n`
  8. `\bHermes Agent\b` (when not already followed by " plugin" or " repo") → `Hermes`
- Provide a config-overridable mapping for future additions:
  `config["discord"]["term_normalization"]` (dict[str, str]) — applied
  AFTER the built-ins. Missing/empty config = built-ins only.
- Helper must NOT touch URLs. Detect `https?://\S+` spans and skip them.
- Unit-tested in isolation.

`is_placeholder(text: str) -> bool`
- Returns True for the placeholder set in §2.1, after `.strip().lower()`.

`collapse_blank_lines(text: str) -> str`
- Replace `\n\s*\n(\s*\n)+` with `\n\n`. Strip trailing whitespace per line.

### 2.3 Confidence / source labeling (router.py)

A footer line is appended (single line, italics) summarizing caveats:
- Build from `extraction.get("transcript_source")` and
  `extraction.get("verification", {}).get("confidence")`.
- Format examples:
  - `_Source: whisper-fallback transcript • verification: not run_`
  - `_Source: youtube-transcript-api • verification: unverified (researcher pending)_`
- Map `"unverified_stub"` → `"unverified (researcher pending)"`.
- Map `"not_run"` → `"not run"`.
- Map `"verified"` → `"verified by researcher"`.
- Omit the footer entirely if both fields are missing/unknown.
- Footer is appended once per card, AFTER blank-line collapse, BEFORE
  `trim_card`. Never appears on `short` cards (those keep their compact
  one-line shape).

### 2.4 Scoring recalibration (scoring.py)

Goals:
- 10.0 must require multiple substantial signals AND high confidence.
- `unverified_stub` should not produce a 10.0.
- Inflation-by-counting (workflow + automation + ideas + tools = 9.3
  before weights) must end.

New formula (deterministic, preserves existing keys/return shape):

```
base = 3.0
# Substantial-signal credit (max one per category, with quality gates)
+ 1.5 if has_substantial_workflow(extraction)         # ≥3 steps OR (≥2 steps AND stack≥2)
+ 1.2 if has_substantial_automation(extraction)        # use_case AND (trigger OR tools≥1) AND estimated_value
+ 0.8 if has_substantial_hermes_idea(extraction)       # rationale len ≥ 40 chars
+ 0.5 if has_substantial_tool_stack(extraction)        # ≥2 distinct named tools with roles
+ 0.5 if has_substantial_pattern(extraction)           # snippet len ≥ 30 chars
- 1.5 if hype_vs_actionable == "hype"
- 0.5 if topics == {"hype"} only
+ small weighted adjustment (existing config["scoring"]["weights"], capped at +1.0)
```

Caps applied AFTER summing (each cap is a min, then take min of all):
- `transcript_missing` → cap 5.0 (existing).
- `duration < 300s` → cap 7.0 (existing).
- `verification.confidence == "unverified_stub"` AND any claims present
  → cap 8.5, append reason
  `"Researcher verification pending; capped at 8.5."`.
- `verification.confidence == "unverified_stub"` AND no claims → cap 9.0.
- `verification.confidence == "not_run"` AND extraction.get("claims")
  has ≥1 claim → cap 9.0 (claims should be checked before perfect score).
- 10.0 only achievable when:
  - At least 3 of {substantial_workflow, substantial_automation,
    substantial_hermes_idea, substantial_tool_stack} are True, AND
  - `verification.confidence` ∈ {"verified", "not_run"} with no
    unverified claims, AND
  - `transcript_missing` is False, AND
  - `duration >= 300`.
  Else final = `min(final, 9.7)`.

`creator_weight < 0.8` adjustment unchanged.

`score_reasons`:
- Always non-empty.
- Capped at 4 entries.
- Order: signal credits (in the order applied), then penalties, then caps.
- Deduplicated.
- If a cap fired, the cap reason is always included (even if it pushes
  another reason out — keep cap reasons last but never drop them).

Return shape additions (backwards compatible — existing keys preserved):
- `"score_caps_applied"`: list[str] (e.g. `["unverified_stub_with_claims"]`).
- `"score_inputs"`: dict mirroring the substantial_* booleans for debug.

### 2.5 Route uniqueness gate (router.py)

`route_plan(extraction, config)`
- Existing high-level structure preserved (archive vs short bands).
- **New:** before appending each topic sink:
  1. Render the topic card via `render_topic_card(extraction, topic)`.
  2. If it returns `None` (per §2.1), DO NOT append the sink.
  3. If it returns a card whose body equals the body of the
     `intelligence` card (after normalizing whitespace), DO NOT append
     (it adds no unique value).
  4. Equivalence check: hash the bullet bodies (lines starting with `- `)
     of each card; if the topic card's bullets are a strict subset of
     the intelligence card's bullets AND the topic card has ≤1 bullet,
     suppress.
- **New:** for the `hype` topic, only route when
  `extraction.get("hype_vs_actionable") == "hype"` OR there is ≥1
  non-empty claim. The existing `if topic == "hype" and ... == "hype"`
  branch is wrong — it uses topic channel only when hype, otherwise
  falls back to the topic key, which silently maps to the hype channel
  again. Replace with explicit: hype routing requires evidence, else skip.
- Cap topic fan-out to `config["discord"]["max_topic_channels_per_post"]`
  (default 3, configurable). Selection order when capped: keep topics
  whose card has the most unique bullets first, ties broken by topic
  declaration order in `extraction["topics"]`.

`route_extraction`
- For every sink, render once. If render is `None`, skip without
  attempting to send. Log `"sink_skipped_empty"` at debug level via
  `logger`. Continue with remaining sinks.
- Returned dict must still include `sinks` (only non-skipped) and a new
  `skipped_sinks` list with `{type, target, reason}` entries for
  observability.

---

## 3. Module layout

New file: `plugins/youtube_agent_watch/text_quality.py`
- `is_placeholder(text) -> bool`
- `normalize_hermes_terms(text, extra_map=None) -> str`
- `collapse_blank_lines(text) -> str`
- `friendly_kind(kind: str) -> str`
- `confidence_label(value: str) -> str`
- `transcript_source_label(value: str) -> str`
- `card_footer(extraction) -> str | None`

`router.py` imports from `text_quality`. Keeps its public API
(`render_discord_card`, `route_plan`, `route_extraction`) identical in
signature; only return values change as described.

`obsidian.py` registers the Jinja filter:
```
self.env.filters["hermes_terms"] = normalize_hermes_terms
```
Template uses `{{ idea.rationale | hermes_terms }}` etc. on free-text
fields. Frontmatter is left raw to keep YAML valid.

---

## 4. Edge cases (must each have a test or be covered)

E1. Extraction with **all** signal lists empty + topics empty.
    - score: ≤ 4.0, band: "seen", reasons non-empty.
    - render_full_learning_card: returns `None` (no sections, no value).
    - route_extraction: returns `{sinks: [], skipped_sinks: [...]}`.

E2. Extraction with workflows that are empty dicts `[{}]`.
    - format_workflow returns `""`, section suppressed.
    - score: workflow signal NOT credited (fails substantial test).

E3. Extraction with `hermes_openclaw_codex_ideas=[{"kind":"parallel","name":"slash-goal loop","rationale":""}]`.
    - format_idea returns `**Parallel pattern: slash-goal loop**` (no
      trailing dash, no raw "parallel").
    - Obsidian template renders matching line.

E4. Extraction with `prompts_and_patterns=[{"name":"Background computer-use pattern","snippet":""}]`.
    - format_pattern returns `""` → section suppressed.
    - No "**Background computer-use pattern** — " line anywhere.

E5. WorldofAI v2 case: high signal counts but
    `verification.confidence == "unverified_stub"` AND claims present.
    - score capped at 8.5 (was 10.0).
    - score_reasons includes researcher-pending cap message.
    - Footer line includes "verification: unverified (researcher pending)".

E6. Transcript with `transcript_source == "whisper-fallback"`.
    - Footer reads "Source: whisper-fallback transcript".
    - Score not penalized for source (keep existing behavior).

E7. Term normalization:
    - `"Kua agent in cua-driver"` → `"Cua agent in cua-driver"`.
    - `"Open Claw and open-claw and OPEN_CLAW"` → all `OpenClaw`.
    - Idempotent: applying twice yields same result.
    - URLs untouched: `"see https://Kua.example/Open Claw"` stays as-is.

E8. Topic fan-out cap:
    - Extraction with 5 viable topic cards → only 3 routed; selection
      stable; the other 2 in `skipped_sinks` with reason "topic_cap".

E9. Topic card duplication of intelligence card:
    - `skills_to_build` topic body is identical to the
      "Follow-up actions" section in the intelligence card → suppressed.

E10. `hype` topic with `hype_vs_actionable="actionable"` and no claims.
    - Topic skipped (current code would emit a fallback line). reason
      "hype_no_evidence".

E11. Backwards compat: existing `test_actionable_transcript_scores_archive_band`
    must still pass. The new formula must keep an actionable, multi-signal
    extraction with verification == "not_run" and no claims at score ≥ 8.

E12. Scoring `transcript_missing=True` still caps at 5 regardless of
     other signals (existing behavior).

E13. `render_discord_card(short=True)` is unchanged in shape (one line +
     score_reasons), but term-normalized.

---

## 5. Config additions (additive, optional)

In `DEFAULT_CONFIG`:
```
"discord": {
    ...,
    "max_topic_channels_per_post": 3,
    "term_normalization": {},  # user overrides
    "suppress_empty_cards": True,
},
"scoring": {
    ...,
    "caps": {
        "unverified_stub_with_claims": 8.5,
        "unverified_stub_no_claims": 9.0,
        "not_run_with_unverified_claims": 9.0,
        "non_perfect_unless_multi_signal": 9.7,
    },
    "substantial": {
        "workflow_min_steps": 3,
        "workflow_alt_steps_with_stack": 2,
        "workflow_alt_min_stack": 2,
        "automation_requires_value": True,
        "hermes_idea_min_rationale_chars": 40,
        "tool_stack_min_named": 2,
        "pattern_min_snippet_chars": 30,
    },
},
```
All values must be readable with safe defaults so existing user
`config.yaml` files continue to work without edits.

---

## 6. Verification steps

Before merge:

1. Unit tests:
   - `cd /Users/junior/junior-agent/hermes-agent && source .venv/bin/activate`
   - `python -m unittest plugins.youtube_agent_watch.tests.test_router plugins.youtube_agent_watch.tests.test_scoring -v`
   - All previously-passing tests still pass (30/30 → ≥30/30 with new
     additions). Net new tests target each E# above.
2. Full plugin suite:
   - `python -m unittest discover -s plugins/youtube_agent_watch/tests -v`
3. Repo-wide smoke (no regression in adjacent plugins):
   - `bash scripts/run_tests.sh -k youtube_agent_watch`
4. Dry-run against last bad output (WorldofAI Hermes v2):
   - Replay the cached extraction JSON through `route_extraction(...,
     dry_run=True)` and assert:
     - score ≤ 8.5
     - `skipped_sinks` is non-empty
     - No card contains `"None extracted."`
     - No card contains `"**` followed immediately by `** — \n"` or
       `"** — $"` (empty body bullet)
     - At least one card carries the footer with
       "verification: unverified (researcher pending)"
     - Total Discord sinks ≤ 1 (creator) + 1 (intelligence) +
       `max_topic_channels_per_post` (3) = 5, down from 7.
5. Manual eyeball: render the same extraction with the new code, paste
   into Discord staging channel, confirm it reads as A-/B+ vs the
   previous B-/C+.
6. Obsidian: open the generated note, confirm "(none extracted)" italic
   appears where empty, and that "Kua/Open Claw" terms are normalized in
   free text but not in frontmatter or URLs.

Ship criteria:
- All tests green.
- Replay verification (#4) passes all assertions.
- No changes outside the files listed in §1.

---

## 7. Non-goals (explicit)

- Not retraining the extractor or changing prompts.
- Not implementing actual researcher LLM verification (still stubbed).
- Not changing thresholds for `archive`/`short`/`seen` bands.
- Not redesigning the Obsidian template structure beyond the empty-line
  collapse + filter.
- Not touching the Discord sender / channel cache.
