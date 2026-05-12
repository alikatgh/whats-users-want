# 04 — Marker-based idempotency

## What problem does this solve

`executive_findings.md` is the single human-readable narrative for a
run. Multiple stages (1, 3, 4, 5) each contribute their own section.
If you re-run stage 3 after stage 4, you don't want stage 3's section
duplicated in the file — you want it *replaced*. Same for stage 4 if
you re-run it, and stage 5 if you scale up the LLM extraction.

The pattern: **each stage writes its section between named markers**.
On re-run, the stage finds its own marker, removes everything from the
marker to the end (or to the next marker), and writes the new content.

## What's actually happening

Each stage's section starts with a unique heading like
`## Insight Layer` or `## Outlier Split`. The heading IS the marker.
On re-run:

1. Read the existing report file.
2. If the marker is present, split the file at the marker and keep
   only the prefix.
3. Append the new content (which itself starts with the marker).
4. Write the result.

If the marker isn't present (first run of this stage), step 2 is a no-op
and the new content is appended to whatever was there.

## The code in this codebase

[scripts/insight_layer.py](../../scripts/insight_layer.py) `append_report`:

```python
def append_report(run_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    ...
    lines = [
        "",
        "## Insight Layer",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "### Top Opportunity Backlog",
    ]
    ...
    report_path = run_dir / "executive_findings.md"
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    marker = "\n## Insight Layer\n"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    report_path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
```

Walk it line by line:

1. **Build the new section as `lines`** — a list of strings starting
   with `"## Insight Layer"`. Joining `"\n".join(lines)` produces the
   markdown.
2. **Read the existing file** (if it exists) into `existing`.
3. **Define the marker**: `"\n## Insight Layer\n"`. Note the surrounding
   newlines — that prevents false matches if the literal string
   `"Insight Layer"` appears mid-paragraph somewhere.
4. **Find and split**: `existing.split(marker, 1)[0]`. The `1` argument
   to `split` says "split at most once" — even if the marker appears
   multiple times (it shouldn't, but defensive code), only the first
   occurrence matters.
5. **Trim trailing whitespace** with `.rstrip()` and add a single
   newline. This avoids creating multiple blank lines at the join.
6. **Write**: prefix + new section.

The result: re-running stage 3 replaces only the "Insight Layer"
section, leaving stage 1's header and stage 4's outlier split intact
(if they're already in the file).

[scripts/split_outlier_bucket.py](../../scripts/split_outlier_bucket.py)
`append_report` follows the identical pattern with marker
`"\n## Outlier Split\n"`:

```python
def append_report(run_dir: Path, summary, metrics, refined) -> None:
    report = run_dir / "executive_findings.md"
    existing = report.read_text(encoding="utf-8") if report.exists() else ""
    marker = "\n## Outlier Split\n"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    lines = [
        "",
        "## Outlier Split",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        ...
    ]
    report.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")
```

[scripts/llm_extract_rich_tickets.py](../../scripts/llm_extract_rich_tickets.py)
`append_report` does the same with marker `"\n## LLM Extraction Layer\n"`.

The convention is now clear: every stage that writes to the report
has its own H2 heading, and that heading doubles as the marker for
idempotent rewrites.

## A subtle pitfall: the leading newline

The marker is `"\n## Insight Layer\n"` (with a leading newline), not
`"## Insight Layer\n"`. Why?

If the marker were `"## Insight Layer\n"`:

- It would also match `"### Insight Layer\n"` (a triple-`#` subheading),
  because `str.split` does substring matching, not boundary matching.
- It might match a literal mention in body text if the user wrote
  `"This is the ## Insight Layer subsystem"`. Unlikely, but possible.

With the leading newline, the marker only matches when the heading
starts at the beginning of a line. That's the behavior we want.

## A second pitfall: never start the new section with the marker missing

The new section's first line is `""` (empty), then `"## Insight Layer"`.
When joined, that becomes `"\n## Insight Layer\n..."` — exactly what
the marker matches. So when stage 3 runs again, the new content
itself starts with the marker, ensuring future re-runs work too.

If the new section started with `"## Insight Layer\n"` (no leading
empty), the joined string would be `"## Insight Layer\n..."`. Without
a leading newline that doesn't match the marker, and the next re-run
would fail to find the section to replace. The leading empty `""` in
the `lines` list is important.

## Try it

Open the executive findings:

```bash
RUN_DIR=$(ls -1d outputs/option2_* | sort | tail -1)
cat "$RUN_DIR/executive_findings.md" | head -80
```

You'll see the "Option 2 User-Needs Analysis" header from stage 1,
followed by sections for BERTopic Validation, Insight Layer, Outlier
Split, LLM Extraction Layer, and What Users Want — Taxonomy.

Now manually corrupt the Insight Layer section:

```bash
# Append a fake bad line to the file
echo "" >> "$RUN_DIR/executive_findings.md"
echo "## Insight Layer" >> "$RUN_DIR/executive_findings.md"
echo "WRONG DATA HERE" >> "$RUN_DIR/executive_findings.md"
echo "MORE WRONG STUFF" >> "$RUN_DIR/executive_findings.md"
```

The file now has *two* "## Insight Layer" sections. Re-run stage 3:

```bash
.venv/bin/python scripts/insight_layer.py "$RUN_DIR" 2>&1 | tail -5
```

Open the report again:

```bash
cat "$RUN_DIR/executive_findings.md" | head -80
```

The wrong data is gone. The stage's `marker = "\n## Insight Layer\n"`
matched the *first* occurrence of the marker; everything from that
point forward was discarded; the freshly-built section was appended.

The trick is double-edged though: if you put hand-written notes
*after* the marker but before another stage's marker, those notes will
also be wiped. The convention here is **stage outputs only**.
Hand-written notes belong in a separate file (or before the first
stage's marker).

## Why we chose this approach

Three alternatives we considered:

- **Write each stage's section to its own file.** No idempotency issue
  because each file is rewritten in full. But then the executive
  summary is fragmented across many files; harder to read.
- **Templating engines (Jinja2).** Define a master template with named
  placeholders; each stage fills in its placeholder. Works for
  predictable shapes; awkward when stages may or may not produce
  output (LLM extraction is optional).
- **Marker-based replace** — chosen. The marker is *also* the section
  heading, so it's self-documenting. The split logic is three lines.
  And the content is appendable, so a stage that didn't run before
  just appends its section first time.

The marker pattern works well for files that are *sections of stages*.
It would not be the right pattern for files that are *records* (where
every entry should accumulate). For records, append-only is the right
choice; for stage summaries, replace-on-re-run is.

## Generalizing the pattern

If you build a similar pipeline, copy this skeleton:

```python
def append_to_report(report_path: Path, marker: str, new_section: str) -> None:
    """Replace or append `new_section` in `report_path`, keyed on `marker`."""
    existing = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    report_path.write_text(existing + new_section + "\n", encoding="utf-8")
```

Three lines of logic. Every stage's `append_report` is a wrapper that
builds `new_section` and calls into this. The repository inlines the
pattern in each stage rather than centralising it (small enough not to
matter), but extracting it would be a one-paragraph refactor.

## A minimal experiment

Try the pattern in a tiny file:

```bash
.venv/bin/python <<'PY'
from pathlib import Path

REPORT = Path("/tmp/report.md")

def append_to_report(marker: str, new_section: str) -> None:
    existing = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    REPORT.write_text(existing + new_section + "\n", encoding="utf-8")

# First run
append_to_report("\n## Stage A\n", "\n## Stage A\n\nFirst version of A.")
print(REPORT.read_text())
print("---")

# Second run (replaces)
append_to_report("\n## Stage A\n", "\n## Stage A\n\nSecond version of A.")
print(REPORT.read_text())
print("---")

# Add a new stage (appends)
append_to_report("\n## Stage B\n", "\n## Stage B\n\nFirst version of B.")
print(REPORT.read_text())
PY
rm /tmp/report.md
```

The output shows:

1. After first run: just Stage A.
2. After second run: Stage A is *replaced*, not duplicated.
3. After adding Stage B: both sections coexist.

That's the entire pattern.
