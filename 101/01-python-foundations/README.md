# Module 01 — Python Foundations

This module pulls the Python idioms used across the whole pipeline into one
place. Every lesson cites real lines from the scripts under `scripts/`.

## Prerequisites

None. You only need a working Python 3.10+ install with the project's
`requirements.txt` available, and access to the source tree at the repository
root.

## What you'll be able to do after this module

- Read every other lesson in this course without stopping to look up Python
  syntax.
- Recognise why path handling, regex compilation, and exception chaining are
  written the way they are in `scripts/option2_pipeline.py` and
  `scripts/dashboard/lib.py`.
- Write defensive, readable Python in the same style — small functions, type
  hints, soft-fail imports, explicit fallbacks.
- Read the dashboard's Streamlit pages and tell which lines are caching, which
  are CLI plumbing, and which are real work.

## Lessons

| # | Lesson | What it covers |
|---|---|---|
| 01 | [Paths and files](01-paths-and-files.md) | `pathlib.Path`, project-root resolution, `.glob()`, `.exists()`, `.stat()`. Why every script uses `Path` instead of strings. |
| 02 | [Regex](02-regex.md) | `re.compile`, raw strings, character classes, alternation, lookaheads, and the CJK-prefix regex that cleans bilingual category labels. |
| 03 | [Strings and formatting](03-strings-and-formatting.md) | f-string format specifiers, `clean_text` / `normalize_space`, the truncation idiom, and why CLI logs use `repr()`. |
| 04 | [Collections and comprehensions](04-collections-and-comprehensions.md) | list / dict / set comprehensions, `Counter`, sets for fast `in` checks, and code-to-human dicts like `DESIRE_LABELS`. |
| 05 | [Error handling and soft-fail](05-error-handling-and-soft-fail.md) | `try/except`, `raise X from exc`, `optional_import`, lazy imports inside functions, defensive coercion, `st.stop()` on missing inputs. |
| 06 | [Type hints and modern Python](06-type-hints-and-modern-python.md) | `from __future__ import annotations`, PEP 604 `int | None`, `list[str]`, `dict[str, Any]`, and why type hints help even without mypy. |
| 07 | [Decorators, closures, CLI](07-decorators-closures-and-cli.md) | `@st.cache_data` vs `@st.cache_resource`, closures (`_first_existing`), and end-to-end `argparse` walked through `parse_args` in `option2_pipeline.py`. |

Each lesson ends with a "Try it" exercise you can run from the repo root.

What's next: [Module 02 — Data with pandas](../02-data-with-pandas/README.md).
