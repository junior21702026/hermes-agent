Input: extraction JSON.
Output: {score: float, reasons: [..3], topics: [...], hype_vs_actionable: "actionable|mixed|hype"}.

Rubric:
- 10: immediately copy/build; clear stack and steps.
- 8-9: strong practical automation pattern; reproducible and novel.
- 6-7: useful context or named tools, but incomplete.
- 4-5: hype/news/model reaction; little to copy.
- <4: unrelated or low-substance.

Respect hard caps: transcript_missing <= 5; duration <5min <= 7 unless explicit demo.
