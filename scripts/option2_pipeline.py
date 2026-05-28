#!/usr/bin/env python3
"""Stage 1 — clean, featurize, embed, cluster, score managers.

This is the entry point of the pipeline. It reads ``data_2may.csv``, produces a
fully enriched per-ticket dataset, embeds tickets into a multilingual semantic
space, clusters them, and scores managers on context-richness. Every output is
written to a timestamped ``outputs/option2_<timestamp>/`` directory and is
self-contained.

Pipeline order:

1. ``read_raw_csv`` reads the messy CSV with ``dtype=str`` to preserve UID strings.
2. ``canonicalize`` resolves Chinese/English column variants and parses dates.
3. ``featurize_tickets`` extracts the 10 evidence flags, the 10 desire flags,
   the urgency signal, and computes ``context_depth_score`` and the band.
4. ``build_manager_summary`` and ``adjusted_manager_context`` compute manager
   evidence statistics and the OLS-adjusted context-depth model.
5. ``cluster_texts`` embeds (TF-IDF / local sentence-transformers / OpenAI),
   reduces with UMAP, clusters with HDBSCAN (KMeans fallback), and writes the
   interactive Plotly map.
6. ``build_network`` builds a desire/category co-occurrence graph (NetworkX).
7. ``create_charts`` writes static PNG visuals.
8. ``write_markdown_report`` composes ``executive_findings.md``.
9. ``export_excel`` and ``export_analytical_store`` write the Excel workbook,
   Parquet copies, and a DuckDB database with all output tables.

Backends for embeddings:

* ``tfidf``  — fully local; ``TfidfVectorizer`` + ``TruncatedSVD`` if needed.
* ``local``  — local sentence-transformers MiniLM; cached as ``embeddings_local.npy``.
* ``openai`` — OpenAI embeddings API; requires ``OPENAI_API_KEY``.

Soft-fail dependencies: ``umap-learn``, ``hdbscan``, ``statsmodels``,
``networkx``, ``plotly``, ``matplotlib``, ``seaborn``, ``duckdb`` are all
optional. Missing libraries skip their stage with a warning.

Example:
    .. code-block:: bash

        .venv/bin/python scripts/option2_pipeline.py \\
          --input data_2may.csv \\
          --embedding-backend local

See :doc:`docs/engineering/01-stage1-pipeline` for a function-by-function
explanation and :doc:`docs/engineering/09-formulas-cheatsheet` for the exact
``context_depth_score`` formula.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / ".matplotlib-cache"))

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Module-level regex constants.
#
# Every regex below is compiled ONCE at import time with re.compile(...). That
# matters: re.compile pre-parses the pattern into a state machine; we then
# .search() / .findall() it across all 6,728 tickets without re-parsing. The
# trailing re.I flag makes matches case-insensitive (so "BAN" and "ban" both
# count). \b is a word boundary — it pins the match between a word char and a
# non-word char, so "ban" in "Albania" will NOT match.
# ---------------------------------------------------------------------------

# Any http(s) URL up to the first whitespace character. \S+ is "one or more
# non-whitespace chars" — greedy by default, which is what we want for URLs.
URL_RE = re.compile(r"https?://\S+", re.I)

# Image-hosting URLs. The lazy quantifier \S+? plus the lookahead-style group
# `(?:jpg|jpeg|png|webp|gif)` makes this stop at the FIRST image extension,
# even if there is a query string `(?:\?\S*)?` afterwards. (?:...) is a
# non-capturing group — slightly faster than (...) when we don't need the
# captured text.
IMAGE_RE = re.compile(r"https?://\S+?\.(?:jpg|jpeg|png|webp|gif)(?:\?\S*)?", re.I)

# ISO-ish timestamp: "2026-04-12 14:30" or "2026/04/12T14:30:01". The character
# class [-/.] allows any of three separators users actually write.
TIMESTAMP_RE = re.compile(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?\b")

# Bare dates without a time. Two alternations cover both ISO ("2026-04-12") and
# DMY/MDY ("12.04.2026") orderings — common in this multilingual dataset.
DATE_RE = re.compile(r"\b(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]20\d{2})\b")

# Bigo room/group/channel identifiers like "bg_12345abc" or "voice-room.42xy".
# The leading prefix list is the platform's namespace (bg/sg/cg/voice/...).
ROOM_ID_RE = re.compile(r"\b(?:bg|sg|cg|voice|room|channel|group)[._:-]?[a-z0-9][a-z0-9._:-]{5,}\b", re.I)

# Long opaque numeric IDs (UIDs, case IDs). 12–18 digits is the empirical
# range we saw — short enough to exclude phone numbers, long enough to exclude
# years/quantities.
LONG_ID_RE = re.compile(r"\b\d{12,18}\b")

# Vocabulary that signals a ban/moderation discussion. ? after `s` ("insults?")
# makes the s optional, matching both singular and plural forms.
BAN_REASON_RE = re.compile(
    r"\b(?:ban|banned|block|blocked|blacklist|unban|quick unban|insults?|personal attacks?|severe|violation|abuse|scam|fraud|punishment|kick|source|reason)\b",
    re.I,
)

# Self-defense phrases — users protesting innocence ("I did nothing", "without
# reason"). Multi-word phrases are written literally; `dont` covers the common
# typo for "don't".
USER_CLAIM_RE = re.compile(
    r"\b(?:i did nothing|did absolutely nothing|without reason|no reason|by mistake|mistake|unfair|wrongly|false|i don't know|dont know|do not understand|why was i|why i was|i was banned|i got blocked|not guilty|didn't do|did not do)\b",
    re.I,
)

# Money / monetization vocabulary. `top.?up` allows "topup", "top-up", "top up"
# via the `.?` (any single char, optional).
MONEY_RE = re.compile(r"\b(?:money|withdraw|withdrawal|salary|cash|payment|pay|payout|diamonds?|beans?|recharge|top.?up|seller|dealer|reseller|host salary|income|earn)\b", re.I)

# Account-recovery vocabulary — login, password, phone number, restore.
ACCOUNT_RE = re.compile(r"\b(?:account|recover|recovery|login|log in|password|phone number|uid|restore|lost|cannot access|can't access|add friends?)\b", re.I)

# Status / privilege vocabulary (SVIP is Bigo's super-VIP tier).
STATUS_RE = re.compile(r"\b(?:svip|vip|level|points?|badge|status|privilege)\b", re.I)

# Audience-growth vocabulary: opening channels/groups/rooms, raising follower
# limits, creating families, host-agency relationships.
GROWTH_RE = re.compile(r"\b(?:channel|group|room|family|host|agency|limit|followers?|friends?|create|open channel|open group|increase limit)\b", re.I)

# Reporting / complaint vocabulary — used for the "protect from abuse" desire.
REPORT_RE = re.compile(r"\b(?:report|complaint|scam|fraud|abuse|insult|attack|harass|blackmail|evidence)\b", re.I)

# Bug / technical-issue vocabulary.
TECH_RE = re.compile(r"\b(?:bug|error|issue|problem|not working|cannot|can't|failed|crash|version|function|screen|loading)\b", re.I)

# "Help me understand the rules" vocabulary — meta-questions about policy.
RULES_RE = re.compile(r"\b(?:how|why|policy|rule|reason|explain|understand|what happened|new policy|allowed|forbidden)\b", re.I)

# Urgency cues. We COUNT these (not boolean), so "please please plz urgent now"
# scores higher than a single "please". See URGENCY_RE.findall(s) usage.
URGENCY_RE = re.compile(r"\b(?:urgent|asap|please|plz|help|immediately|now|very|again|many times|still|cannot|can't|failed)\b", re.I)

# ---------------------------------------------------------------------------
# DESIRE_PATTERNS: the 10-class taxonomy of "what does the user actually want?"
#
# Each value is a compiled regex; each key is a stable English slug used as a
# column name (`desire__recover_access`, `desire__earn_or_transact_money`,
# ...). We re-use existing regex objects when a class is already covered (e.g.
# ACCOUNT_RE -> recover_access) and inline a fresh re.compile only for the
# unique ones (clearance/fairness, identity/assets, play/entertainment).
#
# Type annotation: `dict[str, re.Pattern[str]]` says "string keys, values are
# compiled patterns over str (not bytes)". The `[str]` parameter on Pattern is
# Python 3.9+ generics syntax.
# ---------------------------------------------------------------------------
DESIRE_PATTERNS: dict[str, re.Pattern[str]] = {
    "recover_access": ACCOUNT_RE,
    "clear_name_or_get_fairness": re.compile(r"\b(?:unban|ban|banned|block|blocked|blacklist|without reason|unfair|wrongly|appeal|reason)\b", re.I),
    "earn_or_transact_money": MONEY_RE,
    "grow_audience_or_community": GROWTH_RE,
    "gain_status_or_privileges": STATUS_RE,
    "protect_from_abuse_or_scam": REPORT_RE,
    "fix_product_or_technical_flow": TECH_RE,
    "understand_rules_or_system_logic": RULES_RE,
    "customize_identity_or_assets": re.compile(r"\b(?:gift|prop|frame|avatar|profile|custom|name|photo|badge|skin)\b", re.I),
    "play_or_entertainment": re.compile(r"\b(?:game|games|win|durak|play|guess|casino|bet)\b", re.I),
}

# EVIDENCE_LABELS: the 10 boolean columns that count toward
# `evidence_element_count`. Order matters only for display; summing booleans
# (True=1, False=0) gives an integer "how many kinds of evidence did this
# ticket include" — the foundation of the context_depth_score.
EVIDENCE_LABELS = [
    "has_url",
    "has_image_url",
    "has_timestamp",
    "has_room_or_group_id",
    "has_long_uid_or_case_id",
    "has_ban_reason_language",
    "has_user_claim",
    "has_money_terms",
    "has_status_or_svip_terms",
    "has_multiline_note",
]


def optional_import(module_name: str) -> Any | None:
    """Soft-import a module; return None if it is missing or raises on import.

    The pipeline depends on UMAP, HDBSCAN, statsmodels, NetworkX, plotly,
    matplotlib, seaborn, and DuckDB — but a useful subset still works without
    any of them. Rather than crash at startup, every optional library is
    fetched through this wrapper (or via local ``try/except`` blocks at the
    call site) and the corresponding stage is skipped with a warning when the
    library is absent.

    Args:
        module_name: Top-level module name to import (e.g. ``"umap"``).

    Returns:
        The imported module object, or ``None`` if the import failed.

    Teaching:
        ``__import__`` is the low-level builtin behind the ``import`` statement.
        It takes a string (so the module name can be computed at runtime) and
        returns the module object. We catch ``Exception`` rather than
        ``ImportError`` because some libraries (looking at you, hdbscan +
        numpy ABI mismatches) raise ``RuntimeError`` or ``OSError`` during
        import. The ``Any | None`` return type is PEP 604 union syntax,
        equivalent to ``Optional[Any]``.
    """
    try:
        return __import__(module_name)
    except Exception:
        return None


def ensure_dir(path: Path) -> None:
    """Create ``path`` (and any missing parents) idempotently.

    Used everywhere the pipeline writes files so that ``outputs/option2_<ts>/``
    and its subdirectories spring into existence on first call.

    Args:
        path: Directory to create. Existing directories are left untouched.

    Teaching:
        ``Path.mkdir(parents=True, exist_ok=True)`` is the Pythonic ``mkdir
        -p``: ``parents=True`` makes intermediate directories as needed and
        ``exist_ok=True`` suppresses the ``FileExistsError`` that would
        otherwise fire on the second call. Returning ``None`` (no return
        statement) is conventional for procedural side-effect functions.
    """
    path.mkdir(parents=True, exist_ok=True)


def clean_text(value: Any) -> str:
    """Coerce ``value`` to a stripped string with normalized newlines.

    The first text-cleaning step. Handles three real-world hazards in this
    dataset: (1) pandas hands us ``NaN`` floats for missing cells, (2)
    Windows-style ``\\r\\n`` line endings get mixed with ``\\n`` and break
    later regexes, and (3) tabs and runs of internal spaces inflate
    character counts.

    Args:
        value: Anything pandas might hand us — string, NaN, int, None.

    Returns:
        A clean string. ``None`` and ``NaN`` collapse to ``""``.

    Teaching:
        - ``isinstance(value, float) and math.isnan(value)`` is the canonical
          way to detect NaN. ``NaN != NaN`` by IEEE-754 rule, so a plain
          ``value == nan`` check would silently fail.
        - ``str(value).replace(...)`` chains two passes to normalize CRLF and
          stray CR into LF. Order matters: replace ``\\r\\n`` first so we don't
          double-replace its trailing CR.
        - ``re.sub(r"[ \\t]+", " ", text)`` collapses spaces and tabs but
          PRESERVES newlines (because ``\\n`` is not in the character class).
          That's important — :func:`featurize_tickets` later counts non-empty
          lines as a forensic signal.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_space(value: Any) -> str:
    """Aggressively flatten all whitespace runs (including newlines) to a single space.

    Used for fields where line structure is meaningless — UIDs, manager names,
    category labels, the ``question_flat`` column used for word counting.

    Args:
        value: Anything pandas might hand us.

    Returns:
        A single-line string with internal whitespace runs collapsed.

    Teaching:
        ``\\s+`` matches one or more whitespace chars (spaces, tabs, newlines,
        CR, form-feed). Compare with :func:`clean_text` which preserves
        ``\\n``: the difference between a "tidied multi-line note" and a
        "single-line key for matching/joining". Calling ``clean_text`` first
        gives us NaN/None safety before the whitespace pass.
    """
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def first_existing(df: pd.DataFrame, names: Iterable[str]) -> str | None:
    """Return the first column from ``names`` that exists in ``df``, or None.

    Defensive column resolution. Different CSV exports of the same dataset
    have different column orderings, capitalizations, and language variants
    (``Manager`` vs ``manager``, ``category`` vs ``分类``,
    ``Deligate to`` [sic] vs ``Delegate to``). Rather than littering the
    pipeline with try/except blocks, every column lookup goes through this
    helper.

    Args:
        df: The DataFrame to probe.
        names: An iterable of candidate column names, in priority order.

    Returns:
        The first matching real column name from ``df.columns``, or ``None``
        if nothing matched. The original column casing is preserved so the
        caller can index ``df[returned_name]`` directly.

    Teaching:
        - ``Iterable[str]`` is from ``typing``: any object you can ``for``
          over. We don't need a list — a tuple, generator, or set works too.
        - The two-pass design (exact match first, then case/whitespace
          insensitive) preserves performance on the happy path while still
          rescuing typos from upstream sheet exports.
        - The dict comprehension ``{c.lower().strip(): c for c in
          df.columns}`` builds a lookup table once, so the second loop is
          O(n) total rather than O(n*m).
        - The ``str | None`` return type tells callers they MUST check the
          result before subscripting ``df[...]``.
    """
    for name in names:
        if name in df.columns:
            return name
    lowered = {c.lower().strip(): c for c in df.columns}
    for name in names:
        hit = lowered.get(name.lower().strip())
        if hit:
            return hit
    return None


def read_raw_csv(path: Path) -> pd.DataFrame:
    """Read the raw ticket CSV with string-preserving settings.

    The first stage of the pipeline. Reads ``data_2may.csv`` (6,728 rows in
    the current corpus) into a pandas DataFrame, normalizes the column names,
    and drops the entirely-empty trailing ``Unnamed: N`` columns Google Sheets
    emits when a region of the spreadsheet was selected but never filled.

    Args:
        path: Filesystem path to the source CSV.

    Returns:
        A DataFrame where every cell is a Python ``str`` (never ``NaN``),
        column names are stripped of whitespace, and empty trailing columns
        are removed.

    Teaching:
        - ``dtype=str`` forces every column to be read as a string. CRITICAL
          for this dataset: Bigo UIDs are 12–18 digit numbers (e.g.
          ``900912345678``). Pandas's default would convert them to ``int64``
          or ``float64``, dropping leading zeros and crucially losing
          precision past 2^53. UIDs become ``9.00912e+11`` and break joins.
        - ``keep_default_na=False`` stops pandas from interpreting strings
          like ``"NA"``, ``"N/A"``, ``""``, ``"null"`` as NaN. We want literal
          empty strings, because (a) we'll do our own NaN handling, and (b)
          some legitimate values (e.g. user complaints containing the word
          "null") would otherwise vanish.
        - ``df.columns = [clean_text(c) for c in df.columns]`` is a list
          comprehension that rebuilds the column index. pandas allows
          assigning a list of the same length as the existing columns.
        - The ``empty_unnamed`` list-comprehension uses ``.all()`` on a
          boolean Series — True if every cell in the column was empty after
          stripping. ``.astype(str)`` defends against the rare case the
          ``dtype=str`` directive missed something.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [clean_text(c) for c in df.columns]
    empty_unnamed = [c for c in df.columns if c.lower().startswith("unnamed") and (df[c].astype(str).str.strip() == "").all()]
    if empty_unnamed:
        df = df.drop(columns=empty_unnamed)
    return df


# Match a leading run of CJK chars + CJK punctuation + ampersands/whitespace
# that immediately precedes an English Latin letter. The lookahead `(?=[A-Za-z])`
# is a zero-width assertion: the Latin letter must FOLLOW but is NOT consumed
# by the match, so it survives the .sub() that strips the CJK prefix away.
# Range `一-鿿` covers CJK Unified Ideographs; `　-〿` covers CJK punctuation
# (including the ideographic space `　` and other fullwidth marks).
CJK_DUP_PREFIX_RE = re.compile(r"^[一-鿿　-〿&\s]+(?=[A-Za-z])")


def strip_cjk_dup_prefix(value: Any) -> str:
    """Strip a leading CJK label that precedes the same value in English.

    Colleagues prefix many category strings with the Chinese version of the
    label, sometimes with separators (``&``, spaces). Examples:

        '咨询信息Consulting info'              -> 'Consulting info'
        '解封&封禁 Unblocking & Banning'        -> 'Unblocking & Banning'
        '货币相关 Currency related'             -> 'Currency related'

    Pure-Chinese values (``已解决``) and pure-English values are left alone
    because the lookahead requires a Latin letter to anchor the strip.

    Args:
        value: Anything pandas might pass — typically a ``str``, but could be
            ``None`` or ``NaN`` from a missing cell.

    Returns:
        The value with the duplicated CJK prefix removed and surrounding
        whitespace stripped, or the original/empty string if the input was
        not a string.

    Teaching:
        - The ``isinstance`` guard is a defensive idiom: regex methods only
          accept ``str`` inputs, and pandas ``apply`` will sometimes hand us
          ``None`` for null cells even after :func:`clean_text`.
        - ``CJK_DUP_PREFIX_RE.sub("", value)`` says "replace every match with
          the empty string". Because the regex is anchored with ``^`` it can
          only match at the start, so this acts as a "strip prefix" rather
          than a global substitution.
        - The lookahead ``(?=[A-Za-z])`` is what keeps this safe for purely
          Chinese values: with no Latin letter anywhere, the lookahead can
          never be satisfied, the regex doesn't match, and ``.sub()`` returns
          the original string unchanged.
    """
    if not isinstance(value, str):
        return value if value is not None else ""
    return CJK_DUP_PREFIX_RE.sub("", value).strip()


# Detects ad-hoc "cohort" columns colleagues add in Google Sheets pivots.
# Their headers literally contain a newline followed by an emoji-and-date tag
# (e.g. "Role\n📆: 2026-04-06"). The re.VERBOSE flag lets us write the regex
# across multiple lines with `#` comments — pure readability win for patterns
# that humans will revisit. The `|` alternation matches either prefix.
JUNK_COLUMN_RE = re.compile(
    r"""
    ^Role\n               # 'Role\n📆: 2026-04-06' style cohort columns
    | ^SVIP\n             # 'SVIP\n📆: ...' style cohort columns
    """,
    re.VERBOSE,
)


def drop_noise_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Drop columns colleagues add for ad-hoc Google Sheets pivots.

    Real CSV exports are messy: support managers add temporary tally columns
    to count things during weekly meetings, then export the sheet without
    cleaning up. This function recognises and discards those without
    affecting the genuine ticket columns.

    Removes:
      * Cohort-tag columns whose name starts with ``Role\\n`` or ``SVIP\\n``
        (carrying inline dates and emoji).
      * The Russian ``Статус`` column when it is being used as a pivot count
        (mostly numeric / mostly empty values, not a real status).

    Args:
        df: Raw DataFrame straight from :func:`read_raw_csv`.

    Returns:
        ``(cleaned_df, list_of_dropped_column_names)``. The list is for the
        run-metadata audit log so we can prove which columns were sacrificed.

    Teaching:
        - ``list(df.columns)`` snapshots the column index BEFORE we start
          mutating ``df``. Iterating directly over ``df.columns`` while
          dropping columns inside the loop would change the iterator
          mid-flight — a classic mutate-while-iterating bug.
        - ``str.fullmatch(...)`` returns True only if the ENTIRE string
          matches the pattern (unlike ``search``/``match``). Combined with
          ``.mean()`` on a boolean Series, it gives the fraction of nonempty
          rows that look like numbers — our heuristic for "this is a tally
          column".
        - The 0.30 / 0.85 thresholds are deliberately conservative: a
          legitimate ``Статус`` column with a few stray digits in it stays;
          one with mostly numbers or mostly blanks goes.
    """
    dropped: list[str] = []

    for col in list(df.columns):
        if JUNK_COLUMN_RE.search(col):
            df = df.drop(columns=[col])
            dropped.append(col)

    if "Статус" in df.columns:
        values = df["Статус"].fillna("").astype(str).str.strip()
        nonempty = values[values.ne("")]
        if len(nonempty):
            numeric_share = nonempty.str.fullmatch(r"-?\d+(?:\.\d+)?").mean()
            empty_share = (values == "").mean()
            if numeric_share >= 0.30 or empty_share >= 0.85:
                df = df.drop(columns=["Статус"])
                dropped.append("Статус")
    return df, dropped


def drop_summary_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop colleague-added pivot / summary / aggregation rows.

    These rows have no real ticket content — usually just a category label and a
    count, like ``,咨询信息Consulting info,0,,,``. Heuristic: any row missing
    both ``Question`` text and ``UID`` is treated as a summary row and dropped.
    Returns ``(cleaned_df, dropped_count)``.

    Args:
        df: DataFrame after :func:`drop_noise_columns`.

    Returns:
        ``(cleaned_df, dropped_count)``. The count goes into ``run_metadata.json``.

    Teaching:
        - ``has_question | has_uid`` is element-wise boolean OR on pandas
          Series — a row is "real" if it has either Question text or a UID.
          Use ``|`` and ``&`` between Series, not the Python keywords ``or``
          and ``and`` (those would coerce the whole Series to a single bool
          and raise).
        - The leading ``~`` in ``(~keep).sum()`` is element-wise NOT (boolean
          inversion), giving us the count of rows that fail BOTH checks.
        - ``df.loc[mask].reset_index(drop=True)`` filters by boolean mask and
          then renumbers the index from 0 again. ``drop=True`` discards the
          old (now gappy) index instead of preserving it as a new column.
        - The early return for "no Question/UID columns at all" is a defense
          against radically different schemas — if neither column exists, we
          have no basis to judge anything as a summary row, so we leave the
          frame untouched.
    """
    question_col = first_existing(df, ["Question"])
    uid_col = first_existing(df, ["UID"])
    if question_col is None and uid_col is None:
        return df.reset_index(drop=True), 0

    has_question = pd.Series([False] * len(df), index=df.index)
    has_uid = pd.Series([False] * len(df), index=df.index)
    if question_col is not None:
        has_question = df[question_col].fillna("").astype(str).str.strip().ne("")
    if uid_col is not None:
        has_uid = df[uid_col].fillna("").astype(str).str.strip().ne("")

    keep = has_question | has_uid
    dropped = int((~keep).sum())
    return df.loc[keep].reset_index(drop=True), dropped


def canonicalize(df: pd.DataFrame) -> pd.DataFrame:
    """Resolve column variants and produce a stable canonical schema.

    The CSV's column names drift between exports \u2014 sometimes English,
    sometimes Chinese (``\u5206\u7c7b``), sometimes Russian (``\u0421\u0442\u0430\u0442\u0443\u0441``), sometimes
    misspelled (``Deligate to``). This function normalises everything into
    a known set of snake_case columns the rest of the pipeline can depend on,
    and parses dates into proper ``datetime64`` values.

    Args:
        df: Cleaned raw DataFrame from :func:`drop_summary_rows`.

    Returns:
        A fresh DataFrame with these canonical columns: ``source_row``,
        ``date_raw``, ``date``, ``month``, ``manager``, ``role``,
        ``role_secondary``, ``uid``, ``question_kind``, ``question``,
        ``question_flat``, ``delegate_to``, ``status_en``, ``category``,
        ``status_cn``, ``svip_level``, ``is_resolved``, ``is_unresolved``.

    Teaching:
        - Each ``out["..."] = df[first_existing(...)]...`` chain wraps a
          column lookup in :func:`first_existing` so the pipeline survives
          either ``Manager``, ``manager``, or anything in between.
        - ``pd.to_datetime(..., errors="coerce", dayfirst=True)`` parses
          strings into datetimes; ``coerce`` turns unparseable values into
          ``NaT`` (Not a Time, pandas's null) instead of raising;
          ``dayfirst=True`` handles the European ``DD.MM.YYYY`` ordering many
          users in this dataset write.
        - ``out["date"].dt.to_period("M").astype(str)`` collapses each date
          to its month bucket as a string like ``"2026-04"``. ``.dt`` is the
          datetime accessor, the same way ``.str`` is the string accessor.
        - ``out["is_resolved"] = out["status_en"].isin([...]) | ...`` builds
          a boolean column from two language variants of "resolved": English
          ``Closed``/``Done`` and Chinese ``\u5df2\u89e3\u51b3``. ``\\u5df2\\u89e3\\u51b3``
          is a Unicode-escaped form of ``\u5df2\u89e3\u51b3`` \u2014 equivalent but ASCII-safe
          for editors that struggle with CJK.
        - The ``next((c for c in df.columns if "SVIP" in c.upper()), None)``
          generator-expression-with-default is the idiomatic way to get the
          first matching item or ``None``.
    """
    category_col = first_existing(df, ["category", "\u5206\u7c7b"])
    status_cn_col = first_existing(df, ["status_cn", "\u0421\u0442\u0430\u0442\u0443\u0441"])
    role_1_col = first_existing(df, ["Role.1", "role_1", "role_secondary"])
    svip_col = next((c for c in df.columns if "SVIP" in c.upper()), None)

    out = pd.DataFrame(index=df.index)
    out["source_row"] = df[first_existing(df, ["#"])].map(normalize_space) if first_existing(df, ["#"]) else np.arange(1, len(df) + 1).astype(str)
    out["date_raw"] = df[first_existing(df, ["Date"])].map(normalize_space) if first_existing(df, ["Date"]) else ""
    out["date"] = pd.to_datetime(out["date_raw"], errors="coerce", dayfirst=True)
    out["month"] = out["date"].dt.to_period("M").astype(str).replace("NaT", "")
    out["manager"] = df[first_existing(df, ["Manager"])].map(normalize_space) if first_existing(df, ["Manager"]) else "Unknown"
    out["role"] = df[first_existing(df, ["Role"])].map(normalize_space) if first_existing(df, ["Role"]) else ""
    out["role_secondary"] = df[role_1_col].map(normalize_space) if role_1_col else ""
    out["uid"] = df[first_existing(df, ["UID"])].map(normalize_space) if first_existing(df, ["UID"]) else ""
    out["question_kind"] = df[first_existing(df, ["Question Kind"])].map(normalize_space) if first_existing(df, ["Question Kind"]) else ""
    question_col = first_existing(df, ["Question"])
    out["question"] = df[question_col].map(clean_text) if question_col else ""
    out["question_flat"] = out["question"].map(normalize_space)
    out["delegate_to"] = df[first_existing(df, ["Deligate to", "Delegate to"])].map(normalize_space) if first_existing(df, ["Deligate to", "Delegate to"]) else ""
    out["status_en"] = df[first_existing(df, ["Status"])].map(normalize_space) if first_existing(df, ["Status"]) else ""
    if category_col:
        out["category"] = df[category_col].map(lambda v: strip_cjk_dup_prefix(normalize_space(v)))
    else:
        out["category"] = ""
    out["status_cn"] = df[status_cn_col].map(normalize_space) if status_cn_col else ""
    out["svip_level"] = df[svip_col].map(normalize_space) if svip_col else ""
    out["is_resolved"] = out["status_en"].isin(["Closed", "Done"]) | out["status_cn"].eq("\u5df2\u89e3\u51b3")
    out["is_unresolved"] = ~out["is_resolved"]
    return out


def featurize_tickets(df: pd.DataFrame) -> pd.DataFrame:
    """Add evidence, desire, and context-depth features to the canonicalized frame.

    The heart of the pipeline. Every downstream stage (manager scoring,
    clustering, OLS adjustment, charts, report) reads from the columns this
    function produces. The philosophy: a ticket is "rich" when it carries
    artefacts that let a downstream investigator reconstruct what happened
    without bothering the user — URLs, screenshots, timestamps, room IDs,
    long UIDs, ban-reason language, the user's own claim of innocence,
    money/SVIP/status terms, and a non-trivial line count.

    Computes ~25 derived columns per ticket: length features (``char_count``,
    ``word_count``, ``line_count``), evidence counts and boolean flags
    (``has_url``, ``has_image_url``, ``has_timestamp``, ...), the 10
    ``desire__*`` boolean flags, ``primary_desire``, ``urgency_signal``,
    ``evidence_element_count``, ``context_depth_score`` (capped at the 95th
    percentile so a single long ticket cannot dominate), ``context_depth_band``,
    and ``model_text`` (the question with URLs replaced by ``[URL]`` for
    embedding).

    Args:
        df: Canonicalized DataFrame from :func:`canonicalize`.

    Returns:
        A new DataFrame with derived columns added. Original columns preserved.

    Teaching:
        WALKTHROUGH OF EVERY FEATURE.

        Length features:
          * ``char_count``: ``q.str.len()`` — raw Python ``len`` on each cell.
          * ``word_count``: ``flat.str.findall(r"\\b\\w+\\b").str.len()``
            counts word tokens. ``\\w+`` includes Unicode word chars by
            default in Python 3, so Cyrillic and Chinese-as-romanized count.
          * ``line_count``: a Python lambda splits on ``\\n`` and counts
            non-empty lines. Multi-line tickets correlate strongly with
            "user provided structured forensic detail".

        Regex counts (counts, not booleans, so the score can scale):
          ``url_count``, ``image_url_count``, ``timestamp_count``,
          ``date_mention_count``, ``room_or_group_id_count``,
          ``long_uid_or_case_id_count``. Each is ``q.map(lambda s:
          len(REGEX.findall(s)))`` — number of matches in that ticket.

        Evidence booleans (used by ``evidence_element_count`` and the score):
          ``has_url``, ``has_image_url``, ``has_timestamp``,
          ``has_room_or_group_id``, ``has_long_uid_or_case_id``: derived from
          the count columns via ``.gt(0)`` (greater-than-zero).
          ``has_ban_reason_language``, ``has_user_claim``, ``has_money_terms``,
          ``has_status_or_svip_terms``: ``bool(REGEX.search(s))`` per row.
          ``has_multiline_note``: ``line_count.ge(3)`` — three or more lines.
          ``has_screenshot_evidence``: image OR the literal word
          "screenshot/screens" appears.

        Desire flags:
          The for-loop unrolls :data:`DESIRE_PATTERNS` into 10 columns named
          ``desire__<slug>``. Note the ``lambda s, p=pattern:`` trick — it
          binds ``pattern`` at function-definition time as a default arg,
          which prevents Python's late-binding closure bug (otherwise every
          lambda would capture the same final ``pattern`` from the loop).
          ``desire_count`` sums the 10 flags. ``primary_desire`` uses
          ``idxmax`` to pick the FIRST column where the row is True (so
          declared-order in DESIRE_PATTERNS = priority). When no desire
          fired, the row is labelled ``unclear_or_needs_llm`` so a future
          LLM-based pass can re-classify it.

        Urgency:
          ``urgency_signal`` is a count of urgency cue words (please, urgent,
          asap, ...). Counts, not booleans, so panicked users score higher.

        ``evidence_element_count``: sum across the 10 EVIDENCE_LABELS — an
          integer 0-10 expressing "how many forensic evidence types".

        ``context_depth_score`` — THE FORMULA.
          Three continuous features (chars, lines, urls) are normalised by
          their 95th-percentile value (``char_cap``, ``line_cap``,
          ``url_cap``). ``np.minimum(x/cap, 1)`` clips to [0, 1] — the cap is
          a "percentile capping" technique that prevents one outlier ticket
          (someone pasted 50,000 characters) from saturating the formula and
          stealing all the signal from average-rich tickets.
          The score is then a WEIGHTED SUM. Weights were chosen by hand to
          encode the team's investigative priors:
            18 = chars (bulkiest signal of "user wrote a lot")
            10 = lines      (structured complaint)
            10 = urls       (artefacts to inspect)
            10 = image      (a screenshot is gold)
             8 = timestamp  (when it happened)
             8 = room id    (where it happened)
             8 = long uid   (whom it concerns)
            10 = ban-reason (a moderation case)
             8 = user claim (counter-narrative)
             5 = money      (escalation but not forensic)
             5 = status     (escalation but not forensic)
          Maximum theoretically achievable: 18+10+10+10+8+8+8+10+8+5+5 = 100.
          ``.round(2)`` makes the column readable in CSV/Excel exports.

        Bands via ``pd.cut``:
          ``pd.cut`` slices a numeric Series into labelled bins. ``bins=[-1,
          15, 35, 60, 101]`` produces four buckets — note the ``-1`` lower
          edge (so a literal 0 score is included in ``thin``) and ``101``
          upper edge (so the rare 100-score ticket lands in ``forensic``).
          ``.astype(str)`` converts the resulting categorical to a plain
          string column for clean CSV output.

        ``model_text``:
          The question, with every URL replaced by the literal token
          ``[URL]``. This is the input to the embedding stage. We strip URLs
          because they're high-cardinality noise that confuses TF-IDF and
          embedding models alike — the FACT that a URL was present is
          captured separately in ``has_url``.
    """
    out = df.copy()
    q = out["question"].fillna("").astype(str)
    flat = out["question_flat"].fillna("").astype(str)

    out["char_count"] = q.str.len()
    out["word_count"] = flat.str.findall(r"\b\w+\b").str.len()
    out["line_count"] = q.map(lambda s: len([line for line in s.split("\n") if line.strip()]))
    out["url_count"] = q.map(lambda s: len(URL_RE.findall(s)))
    out["image_url_count"] = q.map(lambda s: len(IMAGE_RE.findall(s)))
    out["timestamp_count"] = q.map(lambda s: len(TIMESTAMP_RE.findall(s)))
    out["date_mention_count"] = q.map(lambda s: len(DATE_RE.findall(s)))
    out["room_or_group_id_count"] = q.map(lambda s: len(ROOM_ID_RE.findall(s)))
    out["long_uid_or_case_id_count"] = q.map(lambda s: len(LONG_ID_RE.findall(s)))

    out["has_url"] = out["url_count"].gt(0)
    out["has_image_url"] = out["image_url_count"].gt(0)
    out["has_timestamp"] = out["timestamp_count"].gt(0)
    out["has_room_or_group_id"] = out["room_or_group_id_count"].gt(0)
    out["has_long_uid_or_case_id"] = out["long_uid_or_case_id_count"].gt(0)
    out["has_ban_reason_language"] = q.map(lambda s: bool(BAN_REASON_RE.search(s)))
    out["has_user_claim"] = q.map(lambda s: bool(USER_CLAIM_RE.search(s)))
    out["has_money_terms"] = q.map(lambda s: bool(MONEY_RE.search(s)))
    out["has_status_or_svip_terms"] = q.map(lambda s: bool(STATUS_RE.search(s)))
    out["has_multiline_note"] = out["line_count"].ge(3)
    out["has_screenshot_evidence"] = out["has_image_url"] | q.str.contains(r"\bscreens?\b|screenshot", flags=re.I, regex=True, na=False)

    for desire, pattern in DESIRE_PATTERNS.items():
        out[f"desire__{desire}"] = q.map(lambda s, p=pattern: bool(p.search(s)))

    desire_cols = [f"desire__{name}" for name in DESIRE_PATTERNS]
    out["desire_count"] = out[desire_cols].sum(axis=1)
    out["primary_desire"] = out[desire_cols].idxmax(axis=1).str.replace("desire__", "", regex=False)
    out.loc[out[desire_cols].sum(axis=1).eq(0), "primary_desire"] = "unclear_or_needs_llm"

    out["urgency_signal"] = q.map(lambda s: len(URGENCY_RE.findall(s)))
    out["evidence_element_count"] = out[EVIDENCE_LABELS].sum(axis=1)

    char_cap = max(float(out["char_count"].quantile(0.95)), 1.0)
    line_cap = max(float(out["line_count"].quantile(0.95)), 1.0)
    url_cap = max(float(out["url_count"].quantile(0.95)), 1.0)
    out["context_depth_score"] = (
        18 * np.minimum(out["char_count"] / char_cap, 1)
        + 10 * np.minimum(out["line_count"] / line_cap, 1)
        + 10 * np.minimum(out["url_count"] / url_cap, 1)
        + 10 * out["has_image_url"].astype(int)
        + 8 * out["has_timestamp"].astype(int)
        + 8 * out["has_room_or_group_id"].astype(int)
        + 8 * out["has_long_uid_or_case_id"].astype(int)
        + 10 * out["has_ban_reason_language"].astype(int)
        + 8 * out["has_user_claim"].astype(int)
        + 5 * out["has_money_terms"].astype(int)
        + 5 * out["has_status_or_svip_terms"].astype(int)
    ).round(2)
    out["context_depth_band"] = pd.cut(
        out["context_depth_score"],
        bins=[-1, 15, 35, 60, 101],
        labels=["thin", "basic", "rich", "forensic"],
    ).astype(str)
    out["model_text"] = q.map(lambda s: URL_RE.sub(" [URL] ", normalize_space(s)).strip())
    return out


def build_manager_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-manager evidence and context-depth metrics.

    Produces the ``manager_context_quality`` table. For every manager (the
    person who handled the ticket), this computes ticket volume, unique
    users, mean/median context-depth score, the share of tickets in each
    band, and the share of tickets carrying each evidence type. Sorted by
    average context score so the "best documenters" surface first.

    Args:
        df: Enriched ticket DataFrame from :func:`featurize_tickets`.

    Returns:
        DataFrame with one row per manager, sorted by ``avg_context_score``
        descending then ``tickets`` descending.

    Teaching:
        - ``df.groupby("manager", dropna=False)`` groups rows by manager;
          ``dropna=False`` keeps a group for ``NaN`` managers (so we don't
          silently lose tickets from missing-manager rows).
        - ``.agg(name=(column, fn), ...)`` is the named-aggregation form: each
          keyword becomes a column in the result, and the tuple ``(source,
          func)`` says "apply ``func`` to ``source`` within each group".
          Using string names (``"count"``, ``"mean"``, ``"median"``) is
          faster than custom lambdas because pandas dispatches to optimized
          C paths.
        - Lambdas are used for the harder cases: counting unique non-empty
          UIDs (``s.replace("", np.nan).nunique()`` — replace blanks with
          NaN so they're skipped) and computing share-of-band
          (``(s == "forensic").mean()`` — boolean-to-fraction trick).
        - The trailing for-loop rounds anything that's a share, average, or
          median to 4 decimals — readability for CSV and Excel exports.
        - ``sort_values(..., ascending=[False, False])`` accepts a list of
          booleans matching the list of columns: both descending here.
    """
    grouped = df.groupby("manager", dropna=False)
    summary = grouped.agg(
        tickets=("source_row", "count"),
        unique_users=("uid", lambda s: s.replace("", np.nan).nunique()),
        avg_context_score=("context_depth_score", "mean"),
        median_context_score=("context_depth_score", "median"),
        forensic_share=("context_depth_band", lambda s: (s == "forensic").mean()),
        rich_or_forensic_share=("context_depth_band", lambda s: s.isin(["rich", "forensic"]).mean()),
        avg_char_count=("char_count", "mean"),
        avg_line_count=("line_count", "mean"),
        url_share=("has_url", "mean"),
        image_evidence_share=("has_image_url", "mean"),
        timestamp_share=("has_timestamp", "mean"),
        room_id_share=("has_room_or_group_id", "mean"),
        user_claim_share=("has_user_claim", "mean"),
        ban_reason_share=("has_ban_reason_language", "mean"),
        unresolved_share=("is_unresolved", "mean"),
    ).reset_index()
    for col in summary.columns:
        if col.endswith("share") or col.startswith("avg") or col.startswith("median"):
            summary[col] = summary[col].astype(float).round(4)
    return summary.sort_values(["avg_context_score", "tickets"], ascending=[False, False])


def adjusted_manager_context(df: pd.DataFrame) -> pd.DataFrame:
    """Fit OLS of context_depth_score on manager + controls; return per-manager deltas.

    Model:

        context_depth_score ~ C(manager) + C(category) + C(question_kind)
                            + C(role) + C(status_en) + C(month)

    Uses ``cov_type="HC3"`` for heteroskedasticity-robust standard errors. The
    baseline manager is the first one alphabetically (Albert in this dataset).
    Each non-baseline manager's coefficient is interpreted as the
    context-depth delta after controlling for ticket mix.

    Args:
        df: An enriched ticket DataFrame from :func:`featurize_tickets`.

    Returns:
        DataFrame with columns ``manager``, ``adjusted_context_delta_vs_baseline``,
        ``baseline_manager``, ``p_value``, ``model_r2``, ``interpretation``.
        Sorted by delta descending. Returns a one-row error frame if statsmodels
        is unavailable.

    Teaching:
        WHY ADJUST AT ALL?
        The raw ``manager_context_quality`` table can mislead: a manager who
        only handles forensic ban appeals will look "deep" simply because
        ban appeals are inherently long. Conversely, a manager assigned to
        quick technical resets will look "shallow". The adjusted model
        controls for the MIX of work each manager handles and asks: "given
        the same category, role, status, and month, who writes more
        context?" That's the question we actually care about.

        OLS IN ONE PARAGRAPH.
        Ordinary Least Squares fits ``y = beta_0 + beta_1*x_1 + ... + e``
        by minimising the sum of squared residuals. statsmodels's
        ``smf.ols`` accepts a Patsy-style FORMULA: ``"y ~ x1 + x2"``. The
        wrapper ``C(...)`` turns a categorical variable into a set of
        one-hot dummy columns automatically — one level becomes the baseline
        (reference) and the rest are encoded as 0/1 contrasts. So
        ``C(manager)`` produces 1 dummy per manager (minus the baseline).

        FIXED EFFECTS.
        ``C(category) + C(question_kind) + C(role) + C(status_en) +
        C(month)`` are fixed effects: we don't care about their individual
        coefficients, but we want them in the model so the residual variance
        in ``context_depth_score`` AFTER they're accounted for is what's
        attributable to the manager. ``C(month)`` controls for time trends
        (rules tightened or templates changed); ``C(role)`` controls for
        user type; ``C(status_en)`` for resolution state.

        WHY HC3-ROBUST STANDARD ERRORS.
        The OLS standard p-value formula assumes residuals are
        homoskedastic — same variance everywhere. In support-ticket data
        that's almost never true: variance scales with category, ticket
        length, and so on. ``cov_type="HC3"`` switches to MacKinnon &
        White's HC3 sandwich estimator, which produces standard errors
        that are valid under arbitrary heteroskedasticity. HC3 is the
        most conservative of the HC variants and the modern default for
        small/medium samples. The point estimates (the deltas) don't change
        — only the standard errors and therefore the p-values.

        BASELINE CHOICE.
        ``sorted(unique)[0]`` makes Albert (alphabetically first) the
        reference manager. All deltas are interpreted as "vs Albert". This
        is arbitrary but consistent — flipping the baseline shifts every
        coefficient by a constant but preserves rank-order.

        ``fit.params`` is a Series of coefficients keyed by the Patsy term
        name (``"C(manager)[T.<name>]"``). ``fit.pvalues`` is the matching
        p-values. ``fit.rsquared`` is the model's R² — fraction of variance
        explained — useful as a sanity check (low R² means the controls
        don't explain much, so deltas should be read carefully).
    """
    try:
        import statsmodels.formula.api as smf
    except Exception:
        return pd.DataFrame({"note": ["statsmodels unavailable; adjusted model skipped"]})

    model_df = df[["context_depth_score", "manager", "category", "question_kind", "role", "status_en", "month"]].copy()
    for col in ["manager", "category", "question_kind", "role", "status_en", "month"]:
        model_df[col] = model_df[col].fillna("").replace("", "Unknown")
    try:
        fit = smf.ols("context_depth_score ~ C(manager) + C(category) + C(question_kind) + C(role) + C(status_en) + C(month)", data=model_df).fit(cov_type="HC3")
    except Exception as exc:
        return pd.DataFrame({"note": [f"adjusted model failed: {exc}"]})

    rows = []
    base_manager = sorted(model_df["manager"].unique())[0]
    intercept = fit.params.get("Intercept", 0.0)
    for manager in sorted(model_df["manager"].unique()):
        term = f"C(manager)[T.{manager}]"
        coef = 0.0 if manager == base_manager else float(fit.params.get(term, 0.0))
        pval = np.nan if manager == base_manager else float(fit.pvalues.get(term, np.nan))
        rows.append(
            {
                "manager": manager,
                "adjusted_context_delta_vs_baseline": round(coef, 3),
                "baseline_manager": base_manager,
                "p_value": None if np.isnan(pval) else round(pval, 5),
                "model_r2": round(float(fit.rsquared), 4),
                "interpretation": "positive means richer context after controlling for category/kind/role/status/month",
            }
        )
    return pd.DataFrame(rows).sort_values("adjusted_context_delta_vs_baseline", ascending=False)


def top_examples(df: pd.DataFrame, n: int = 80) -> pd.DataFrame:
    """Return the ``n`` highest-context tickets with their full text and provenance.

    Used to populate ``high_context_examples.csv`` — a curated list of
    "model-quality" tickets that future managers can study as exemplars.
    Sorted by ``context_depth_score`` descending.

    Args:
        df: Enriched ticket DataFrame.
        n: How many top examples to return (default 80).

    Returns:
        A DataFrame with the most informative columns for human inspection:
        identification (``source_row``, ``date_raw``, ``manager``, ``uid``),
        classification (``category``, ``question_kind``, ``status_en``,
        ``primary_desire``), the score itself, evidence counts, and the
        flattened question text.

    Teaching:
        - The default ``n: int = 80`` lets the function be called with no
          argument; an integer literal as a default is fine because ints are
          immutable. (Mutable defaults like ``[]`` would be a classic Python
          gotcha — never do that.)
        - ``df.sort_values(...)[cols].head(n)`` chains three operations:
          sort, project columns, slice top n. Each returns a new DataFrame,
          so the original frame is untouched.
        - Column projection (``df[cols]``) is cheap — it just creates a new
          frame referencing the same underlying arrays.
    """
    cols = [
        "source_row",
        "date_raw",
        "manager",
        "uid",
        "category",
        "question_kind",
        "status_en",
        "context_depth_score",
        "context_depth_band",
        "primary_desire",
        "url_count",
        "image_url_count",
        "timestamp_count",
        "room_or_group_id_count",
        "question_flat",
    ]
    return df.sort_values("context_depth_score", ascending=False)[cols].head(n)


def desire_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Volume and outcome stats per user-desire class.

    For each of the 10 desire classes in :data:`DESIRE_PATTERNS`, count
    matching tickets, compute their share of the corpus, the unresolved
    share, the average context score, and the top-3 managers handling
    that desire. Used to identify which desires are large, badly-resolved,
    or lightly-documented — the main "where to invest" question.

    Args:
        df: Enriched ticket DataFrame.

    Returns:
        DataFrame with one row per desire, sorted by ``tickets`` descending.

    Teaching:
        - The classic accumulator pattern: build a list of dicts, then
          ``pd.DataFrame(rows)`` at the end. Cleaner than appending to a
          DataFrame in a loop (which would copy on every step).
        - ``df[col]`` where ``col`` holds booleans is the same as
          ``df[df[col] == True]``: it selects rows where the boolean is True.
        - Each ticket can match MULTIPLE desires (the regexes overlap), so
          the per-desire ticket counts can sum to MORE than ``len(df)``. The
          ``share`` column normalises by the corpus size, so shares can sum
          to >1 — that's expected, not a bug.
        - ``max(len(df), 1)`` is a divide-by-zero guard. If df is empty we
          divide by 1, returning 0.0 instead of crashing.
        - ``sub["manager"].value_counts().head(3).index.astype(str)`` gets
          the top-3 manager names (``value_counts`` returns counts indexed
          by value, ``.index`` is the Index of those values, ``.astype(str)``
          ensures the join below works even on numeric-looking names).
    """
    rows = []
    for desire in DESIRE_PATTERNS:
        col = f"desire__{desire}"
        sub = df[df[col]]
        rows.append(
            {
                "desire": desire,
                "tickets": int(len(sub)),
                "share": round(len(sub) / max(len(df), 1), 4),
                "unresolved_share": round(float(sub["is_unresolved"].mean()) if len(sub) else 0, 4),
                "avg_context_score": round(float(sub["context_depth_score"].mean()) if len(sub) else 0, 2),
                "top_managers": ", ".join(sub["manager"].value_counts().head(3).index.astype(str)) if len(sub) else "",
            }
        )
    return pd.DataFrame(rows).sort_values("tickets", ascending=False)


def make_text_matrix(texts: list[str], max_features: int = 6000) -> tuple[Any, Any, str]:
    """Fit a TF-IDF vectorizer and return the sparse term matrix.

    Used both as the primary text representation when ``--embedding-backend
    tfidf`` is selected, AND as a labelling tool inside :func:`cluster_texts`
    to extract human-readable top terms per cluster (a precursor to BERTopic's
    "c-TF-IDF" idea).

    Args:
        texts: One document per element. In this pipeline each element is the
            ``model_text`` of one ticket.
        max_features: Cap on vocabulary size. 6000 is a good balance: large
            enough to capture meaningful vocabulary across 6,728 tickets,
            small enough to keep the matrix tractable.

    Returns:
        ``(matrix, vectorizer, "tfidf")``. The matrix is a
        ``scipy.sparse.csr_matrix`` of shape ``(n_docs, n_terms)``; the
        vectorizer can be re-used to transform new texts; the string label
        flows through to ``nlp_backend`` columns for provenance.

    Teaching:
        WHAT TF-IDF IS, MATHEMATICALLY.
        For a term ``t`` in document ``d``:
            tf(t, d)   = count of t in d (or a sublinear log variant)
            idf(t)     = log( N / df(t) ) + 1, where N = total docs and
                         df(t) = number of docs containing t
            tfidf(t,d) = tf(t,d) * idf(t)
        Then sklearn L2-normalizes each document vector. Intuition:
        common words (``the``, ``please``) get tiny IDF and are downweighted;
        rare-but-distinctive words (``unban``, ``svip``) dominate the vector.
        It's a bag-of-words representation — order is lost — but it captures
        topical signal cheaply and is the foundation of every text-mining
        toolkit.

        EVERY PARAMETER, EXPLAINED.
        - ``max_features=6000``: keep only the 6000 most frequent terms
          across the corpus after the other filters. Bounds memory usage.
        - ``min_df=3``: a term must appear in AT LEAST 3 documents to be
          kept. Throws away one-off typos and unique IDs that masqueraded as
          words. With 6,728 tickets, 3 is a soft floor.
        - ``max_df=0.82``: a term that appears in MORE than 82% of documents
          is dropped as a stopword-like nuisance. Catches domain-specific
          junk that ``stop_words="english"`` doesn't know about.
        - ``ngram_range=(1, 2)``: extract both unigrams ("ban") and bigrams
          ("without reason"). Bigrams catch idioms and named entities that
          unigrams miss.
        - ``strip_accents="unicode"``: normalise accented characters
          (``ñ`` → ``n``, ``é`` → ``e``). Critical for a multilingual support
          corpus where users type accents inconsistently.
        - ``lowercase=True``: case-fold before tokenizing.
        - ``token_pattern=r"(?u)\\b[\\w][\\w'-]{2,}\\b"``: only keep tokens
          that are 3+ chars, start with a word char, and may contain
          internal apostrophes/hyphens. ``(?u)`` is the legacy Unicode flag —
          today ``\\w`` is already Unicode, but the explicit flag documents
          intent. This excludes 2-letter words and pure-digit tokens.
        - ``stop_words="english"``: drop the standard English stop list (a,
          the, of, and, ...). Doesn't help non-English content directly, but
          improves the dominant English subset.

        ``fit_transform`` in one call: learn the vocabulary AND produce the
        matrix. If you need to vectorize new texts later, call
        ``vectorizer.transform(new_texts)`` — it reuses the learned IDFs.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(
        max_features=max_features,
        min_df=3,
        max_df=0.82,
        ngram_range=(1, 2),
        strip_accents="unicode",
        lowercase=True,
        token_pattern=r"(?u)\b[\w][\w'-]{2,}\b",
        stop_words="english",
    )
    matrix = vectorizer.fit_transform(texts)
    return matrix, vectorizer, "tfidf"


def embed_texts(texts: list[str], backend: str, out_dir: Path, model_name: str) -> tuple[np.ndarray | Any, Any, str]:
    """Convert texts to vectors using one of three backends, with caching.

    The pluggable embedding stage. Three backends, ordered from cheapest to
    most expensive:

    1. ``tfidf`` — sklearn :class:`TfidfVectorizer` (no model download). Returns
       a sparse high-dimensional matrix. Falls through to :func:`make_text_matrix`.
    2. ``local`` — sentence-transformers (HuggingFace), default
       ``paraphrase-multilingual-MiniLM-L12-v2``. ~120 MB download on first
       run. Returns dense 384-d vectors and is the recommended default for a
       corpus this multilingual.
    3. ``openai`` — calls the OpenAI Embeddings API. Highest semantic
       fidelity, requires ``OPENAI_API_KEY`` and incurs per-token cost.

    Args:
        texts: One string per ticket (typically ``model_text``).
        backend: ``"tfidf" | "local" | "openai"``.
        out_dir: Run output directory; embeddings are cached here as
            ``embeddings_<backend>.npy``.
        model_name: Sentence-transformers model id or OpenAI embedding model
            name. Ignored when ``backend == "tfidf"``.

    Returns:
        ``(features, vectorizer_or_None, label)``. ``features`` is either a
        sparse TF-IDF matrix or a dense numpy ``(n, d)`` array. ``vectorizer``
        is the fitted TfidfVectorizer for the tfidf path, ``None`` otherwise.
        ``label`` is a provenance string like ``"local:..."`` /
        ``"openai:..."`` / ``"tfidf"`` / ``"local-cache:..."`` that flows
        into the ``nlp_backend`` column.

    Raises:
        RuntimeError: ``backend == "openai"`` but no ``OPENAI_API_KEY``.

    Teaching:
        WHY CACHING MATTERS.
        Embeddings are expensive — local MiniLM takes ~30s for 6,728 tickets
        on a laptop GPU; OpenAI costs real money. We cache the result as a
        single ``.npy`` file via ``np.save`` and check for it on entry. Re-runs
        of the pipeline (e.g. you tweaked the chart code) reuse the cached
        embeddings without re-encoding. ``np.save``/``np.load`` is preferred
        over pickle because it's portable, version-stable, and only stores
        the array (not arbitrary Python objects).

        WHY ``normalize_embeddings=True`` ON sentence-transformers.
        It L2-normalizes each output vector to unit length. With unit
        vectors, cosine similarity is just a dot product — fast and the
        scaling is consistent across documents. UMAP and HDBSCAN both behave
        more predictably on normalized inputs because the metric becomes
        purely angular.

        BATCHED API CALLS.
        OpenAI's API accepts multiple inputs per request. We batch in groups
        of 256 to amortize round-trip latency. ``range(0, len(texts), 256)``
        produces start indices; ``texts[start:start+256]`` is a slice that
        gracefully handles the last (possibly shorter) batch.

        DTYPE MATTERS FOR CACHE SIZE.
        ``dtype=np.float32`` halves the file size vs the default float64
        with no measurable accuracy loss for clustering — embedding models
        already operate in float32 internally.
    """
    cache = out_dir / f"embeddings_{backend}.npy"
    if backend == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        from openai import OpenAI

        client = OpenAI()
        vectors: list[list[float]] = []
        batch_size = 256
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = client.embeddings.create(model=model_name, input=batch)
            vectors.extend([item.embedding for item in response.data])
        arr = np.array(vectors, dtype=np.float32)
        np.save(cache, arr)
        return arr, None, f"openai:{model_name}"

    if backend == "local":
        if cache.exists():
            return np.load(cache), None, f"local-cache:{model_name}"
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        arr = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)
        arr = np.asarray(arr, dtype=np.float32)
        np.save(cache, arr)
        return arr, None, f"local:{model_name}"

    matrix, vectorizer, label = make_text_matrix(texts)
    return matrix, vectorizer, label


def cluster_texts(df: pd.DataFrame, out_dir: Path, backend: str, model_name: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Embed ticket text, reduce with UMAP, cluster with HDBSCAN, label with TF-IDF.

    Embedding backend is chosen by ``backend``:

    * ``tfidf``  — sklearn TfidfVectorizer + TruncatedSVD; no model download.
    * ``local``  — sentence-transformers MiniLM; cached as ``embeddings_local.npy``.
    * ``openai`` — OpenAI embeddings API; requires ``OPENAI_API_KEY``.

    UMAP runs twice — once for 2D visualization (``x``, ``y``) and once for a
    10-component clustering space. HDBSCAN is the primary clusterer with adaptive
    ``min_cluster_size = max(12, min(80, len // 90))``. Falls back to
    MiniBatchKMeans with ``k = max(8, min(35, sqrt(n/2)))`` if HDBSCAN is missing
    or fails. Cluster labels come from per-cluster mean TF-IDF top terms.

    Side effects:
        * Writes ``semantic_ticket_map.html`` (interactive Plotly).
        * Writes ``embeddings_<backend>.npy`` cache.

    Args:
        df: Enriched ticket DataFrame.
        out_dir: Run output directory.
        backend: Embedding backend.
        model_name: Sentence-transformers or OpenAI embedding model name.

    Returns:
        Tuple of three DataFrames: per-ticket assignments (with cluster_id, x,
        y, cluster_probability, nlp_backend), per-cluster summary (size, share,
        terms, top desires/categories/managers, examples), and a one-row backend
        info frame.

    Teaching:
        WHY UMAP TWICE — VISUALIZATION VS CLUSTERING.
        UMAP (Uniform Manifold Approximation and Projection) is a non-linear
        dimensionality reduction algorithm. Intuition: it builds a fuzzy
        neighbourhood graph in the high-dim embedding space, then optimises
        a low-dim layout that preserves those neighbourhoods. We run it
        TWICE with different ``n_components``:
          * ``n_components=2`` for the on-screen scatter (x, y coords) —
            humans need 2D, ``min_dist=0.08`` lets points spread out a bit.
          * ``n_components=10`` for clustering — more dimensions retain
            more discriminative signal. ``min_dist=0.0`` packs neighbours
            tightly (which is what HDBSCAN's density estimator wants).
        ``metric="cosine"`` matters: text embeddings live on a sphere, so
        angular distance (cosine) reflects semantic similarity better than
        Euclidean. ``random_state=42`` makes the reduction reproducible.
        ``n_neighbors`` is auto-scaled with the corpus size — too small and
        the manifold gets fragmented, too large and local structure is
        smeared.

        WHY HDBSCAN — DENSITY-BASED CLUSTERING.
        Unlike k-means, HDBSCAN does NOT require ``k`` up front. It builds
        a hierarchy of density-connected components and selects the most
        stable clusters across multiple density thresholds. ``min_cluster_size``
        is the only hard-knob: clusters smaller than this become noise
        (``cluster_id = -1``). We adapt it to corpus size:
        ``max(12, min(80, n // 90))`` — ~75 for 6,728 tickets. This means
        HDBSCAN can declare some tickets as "outliers" (cluster -1), which
        is gold for finding emerging issues that don't fit any pattern yet.
        ``min_samples`` controls the density floor; ``metric="euclidean"``
        is correct AFTER UMAP (UMAP outputs are not on a unit sphere).

        FALLBACK TO MINIBATCHKMEANS.
        If hdbscan isn't installed (it has C extensions that occasionally
        break), we fall back to k-means with ``k = max(8, min(35,
        sqrt(n/2)))``. K-means assigns every point to a cluster (no -1
        noise), assumes spherical equal-variance clusters, and is faster
        and simpler. ``MiniBatchKMeans`` uses random subsamples for each
        update — a big speed win on larger corpora at the cost of a small
        quality hit. ``n_init=20`` runs 20 random initialisations and
        keeps the best, mitigating local-minima issues.

        PER-CLUSTER TF-IDF FOR LABELLING.
        Once we have cluster IDs, we want a human-readable label per
        cluster. The trick: for each cluster, take the MEAN of the TF-IDF
        rows of its members and pick the top terms. This is the same idea
        BERTopic later formalised as "c-TF-IDF" (class-based TF-IDF). When
        the TF-IDF backend was used we reuse its matrix; otherwise (local
        or openai backend) we build a one-shot TF-IDF JUST for labelling
        — embeddings cluster, TF-IDF labels.

        ``np.where(labels == cluster_id)[0]`` returns row indices belonging
        to that cluster. ``features[idx].mean(axis=0)`` averages the sparse
        rows; ``.argsort()[-12:][::-1]`` picks the indices of the 12 largest
        values in descending order — Python's slicing trick where ``[::-1]``
        reverses.

        PLOTLY OUTPUT.
        ``include_plotlyjs="cdn"`` keeps the HTML small by linking the
        plotly.js library from a CDN rather than embedding it (~3 MB saved
        per export).
    """
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import normalize

    valid = df["model_text"].fillna("").map(lambda s: len(s) >= 8)
    work = df.loc[valid, ["source_row", "model_text", "manager", "category", "question_kind", "primary_desire", "context_depth_score", "is_unresolved"]].copy()
    texts = work["model_text"].tolist()

    used_backend = backend
    try:
        features, vectorizer, used_backend = embed_texts(texts, backend=backend, out_dir=out_dir, model_name=model_name)
    except Exception as exc:
        print(f"[warn] embedding backend {backend!r} failed: {exc}. Falling back to TF-IDF/SVD.", file=sys.stderr)
        features, vectorizer, used_backend = embed_texts(texts, backend="tfidf", out_dir=out_dir, model_name=model_name)

    if used_backend == "tfidf":
        n_components = min(80, max(2, features.shape[1] - 1), max(2, features.shape[0] - 1))
        svd = TruncatedSVD(n_components=n_components, random_state=42)
        dense = normalize(svd.fit_transform(features))
        feature_terms = np.asarray(vectorizer.get_feature_names_out())
    else:
        dense = np.asarray(features)
        feature_terms = None

    reduced = dense
    x = np.zeros(len(work))
    y = np.zeros(len(work))
    try:
        import umap

        n_neighbors = min(30, max(5, len(work) // 200))
        reducer_2d = umap.UMAP(
            n_components=2,
            n_neighbors=n_neighbors,
            min_dist=0.08,
            metric="cosine",
            random_state=42,
            n_jobs=1,
        )
        coords = reducer_2d.fit_transform(dense)
        x, y = coords[:, 0], coords[:, 1]
        reducer_cluster = umap.UMAP(
            n_components=10,
            n_neighbors=n_neighbors,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
            n_jobs=1,
        )
        reduced = reducer_cluster.fit_transform(dense)
    except Exception as exc:
        print(f"[warn] UMAP unavailable/failed: {exc}. Clustering on SVD/embedding space.", file=sys.stderr)

    try:
        import hdbscan

        min_cluster_size = max(12, min(80, len(work) // 90))
        clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=max(5, min_cluster_size // 3), metric="euclidean")
        labels = clusterer.fit_predict(reduced)
        probabilities = getattr(clusterer, "probabilities_", np.ones(len(work)))
    except Exception as exc:
        print(f"[warn] HDBSCAN unavailable/failed: {exc}. Falling back to MiniBatchKMeans.", file=sys.stderr)
        from sklearn.cluster import MiniBatchKMeans

        k = max(8, min(35, int(math.sqrt(len(work) / 2))))
        clusterer = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=20, batch_size=1024)
        labels = clusterer.fit_predict(reduced)
        probabilities = np.ones(len(work))

    assignments = work.copy()
    assignments["cluster_id"] = labels.astype(int)
    assignments["cluster_probability"] = np.asarray(probabilities).round(4)
    assignments["x"] = np.asarray(x).round(6)
    assignments["y"] = np.asarray(y).round(6)
    assignments["nlp_backend"] = used_backend

    if used_backend == "tfidf":
        # Use the original sparse TF-IDF matrix for interpretable labels.
        topic_terms = []
        labels_series = pd.Series(labels, index=work.index)
        for cluster_id in sorted(pd.Series(labels).unique()):
            idx = np.where(labels == cluster_id)[0]
            if len(idx) == 0:
                continue
            mean_tfidf = np.asarray(features[idx].mean(axis=0)).ravel()
            top_idx = mean_tfidf.argsort()[-12:][::-1]
            terms = [str(feature_terms[i]) for i in top_idx if mean_tfidf[i] > 0]
            topic_terms.append((int(cluster_id), terms))
        terms_by_cluster = dict(topic_terms)
    else:
        # Still create labels using TF-IDF over texts inside each embedding cluster.
        tfidf, vec, _ = make_text_matrix(texts, max_features=5000)
        terms = np.asarray(vec.get_feature_names_out())
        terms_by_cluster = {}
        for cluster_id in sorted(pd.Series(labels).unique()):
            idx = np.where(labels == cluster_id)[0]
            if len(idx) == 0:
                continue
            mean_tfidf = np.asarray(tfidf[idx].mean(axis=0)).ravel()
            top_idx = mean_tfidf.argsort()[-12:][::-1]
            terms_by_cluster[int(cluster_id)] = [str(terms[i]) for i in top_idx if mean_tfidf[i] > 0]

    summaries = []
    for cluster_id, sub in assignments.groupby("cluster_id"):
        examples = sub.sort_values(["context_depth_score", "cluster_probability"], ascending=False).head(3)["model_text"].tolist()
        summaries.append(
            {
                "cluster_id": int(cluster_id),
                "tickets": int(len(sub)),
                "share": round(len(sub) / max(len(assignments), 1), 4),
                "avg_context_score": round(float(sub["context_depth_score"].mean()), 2),
                "unresolved_share": round(float(sub["is_unresolved"].mean()), 4),
                "top_terms": ", ".join(terms_by_cluster.get(int(cluster_id), [])[:10]),
                "top_desires": ", ".join(sub["primary_desire"].value_counts().head(4).index.astype(str)),
                "top_categories": ", ".join(sub["category"].value_counts().head(4).index.astype(str)),
                "top_managers": ", ".join(sub["manager"].value_counts().head(4).index.astype(str)),
                "example_1": examples[0] if len(examples) > 0 else "",
                "example_2": examples[1] if len(examples) > 1 else "",
                "example_3": examples[2] if len(examples) > 2 else "",
                "nlp_backend": used_backend,
            }
        )
    cluster_summary = pd.DataFrame(summaries).sort_values(["cluster_id"])

    try:
        import plotly.express as px

        plot_df = assignments.merge(cluster_summary[["cluster_id", "top_terms"]], on="cluster_id", how="left")
        fig = px.scatter(
            plot_df,
            x="x",
            y="y",
            color="cluster_id" if plot_df["cluster_id"].nunique() <= 40 else "primary_desire",
            hover_data=["source_row", "manager", "category", "primary_desire", "context_depth_score", "top_terms"],
            title="Ticket semantic map: clusters of user needs",
            height=850,
        )
        fig.write_html(out_dir / "semantic_ticket_map.html", include_plotlyjs="cdn")
    except Exception as exc:
        print(f"[warn] Plotly map failed: {exc}", file=sys.stderr)

    return assignments, cluster_summary, pd.DataFrame({"nlp_backend": [used_backend], "tickets_clustered": [len(assignments)]})


def build_network(df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Build a co-occurrence graph of desires and categories; return node centrality.

    For each ticket, we treat its set of "active" desires and its category as
    nodes; we add an edge between every pair of nodes that co-occur in a
    ticket, weighted by how often that pair appears across the corpus. The
    result is a "what user-intents tend to bundle together with which
    categories" graph — useful for discovering hidden product seams (e.g. if
    ``recover_access`` and ``earn_or_transact_money`` co-occur heavily, it
    suggests scammed-account tickets are routed wrong).

    Side effect:
        Writes ``desire_category_network_edges.csv`` (edges with weight >= 8).

    Args:
        df: Enriched ticket DataFrame.
        out_dir: Run output directory.

    Returns:
        Per-node DataFrame with ``degree_centrality`` (normalised number of
        neighbours, in [0, 1]) and ``weighted_degree`` (total edge weight
        incident to the node). Sorted by ``weighted_degree`` descending.
        Falls back to a one-row note if NetworkX isn't installed.

    Teaching:
        - ``nx.Graph()`` is an undirected graph. Adding the same edge twice
          would just overwrite — that's why we explicitly check
          ``g.has_edge(a, b)`` and ``+= 1`` the weight.
        - ``df.iterrows()`` yields ``(index, Series)`` per row. It's slow on
          big frames but fine for graph-construction patterns where we need
          a row at a time.
        - The double for-loop ``for i in range(len(nodes)): for j in
          range(i+1, len(nodes))`` enumerates unordered pairs without
          repetition — the standard "upper triangle" trick.
        - ``degree_centrality`` divides each node's degree by ``n - 1``
          (max possible degree), giving a value in [0, 1] that's comparable
          across graphs of different sizes.
        - ``weighted_degree`` = sum of edge weights touching the node, so a
          node with three high-weight edges scores higher than one with
          three light edges. Captures importance better than raw degree on
          weighted graphs.
        - The 8-weight threshold for edge export is denoising: pairs that
          appear fewer than 8 times in 6,728 tickets are too sparse to
          generalise.
    """
    try:
        import networkx as nx
    except Exception:
        return pd.DataFrame({"note": ["networkx unavailable; desire/category network skipped"]})

    g = nx.Graph()
    desire_cols = [f"desire__{name}" for name in DESIRE_PATTERNS]
    for _, row in df.iterrows():
        active = [c.replace("desire__", "") for c in desire_cols if bool(row.get(c, False))]
        cat = row.get("category", "") or "Unknown"
        nodes = active + [f"category::{cat}"]
        for node in nodes:
            g.add_node(node)
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                if g.has_edge(a, b):
                    g[a][b]["weight"] += 1
                else:
                    g.add_edge(a, b, weight=1)
    rows = []
    if g.number_of_nodes() == 0:
        return pd.DataFrame()
    centrality = nx.degree_centrality(g)
    weighted_degree = dict(g.degree(weight="weight"))
    for node in g.nodes:
        rows.append({"node": node, "degree_centrality": round(centrality[node], 4), "weighted_degree": round(weighted_degree[node], 2)})
    edges = [
        {"source": a, "target": b, "weight": data["weight"]}
        for a, b, data in g.edges(data=True)
        if data["weight"] >= 8
    ]
    pd.DataFrame(edges).sort_values("weight", ascending=False).to_csv(out_dir / "desire_category_network_edges.csv", index=False)
    return pd.DataFrame(rows).sort_values("weighted_degree", ascending=False)


def create_charts(df: pd.DataFrame, manager_summary: pd.DataFrame, out_dir: Path) -> None:
    """Write three static PNG visualisations of the run's findings.

    Three plots, each saved at 180 DPI for readable embedding in the
    Markdown report:
      1. ``manager_context_depth.png`` — horizontal bar chart of average
         context depth per manager.
      2. ``desire_trends.png`` — monthly tickets per top-8 primary desires.
      3. ``context_depth_vs_outcome.png`` — boxplot of score by band, split
         by resolved/unresolved.

    Args:
        df: Enriched + clustered ticket DataFrame.
        manager_summary: Output of :func:`build_manager_summary`.
        out_dir: Run output directory.

    Teaching:
        - The ``try/except`` around imports follows the same soft-fail
          pattern as :func:`optional_import` — if matplotlib or seaborn is
          missing the run continues without charts.
        - ``sns.set_theme(style="whitegrid", font_scale=0.95)`` configures a
          uniform look-and-feel for ALL subsequent plots in this process.
        - Each plot uses ``plt.figure(figsize=(...))`` to start a fresh
          canvas, then ``plt.tight_layout()`` to prevent label clipping,
          then ``plt.savefig(..., dpi=180)`` and ``plt.close()``. Closing
          frees memory — without it, long-running processes leak figure
          handles.
        - ``df.groupby(["month", "primary_desire"]).size().reset_index(name="tickets")``
          is the idiomatic "pivot to long format" — group, count, and
          rename the count column. The result is what seaborn's
          ``lineplot(hue=...)`` expects.
        - ``df["primary_desire"].value_counts().head(8).index`` finds the
          top-8 most frequent desires; we filter the long frame to just
          those classes so the chart is readable.
    """
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
    except Exception as exc:
        print(f"[warn] matplotlib/seaborn unavailable: {exc}", file=sys.stderr)
        return

    sns.set_theme(style="whitegrid", font_scale=0.95)
    plt.figure(figsize=(10, 5))
    order = manager_summary.sort_values("avg_context_score", ascending=False)["manager"]
    sns.barplot(data=manager_summary, x="avg_context_score", y="manager", order=order, color="#2E6F95")
    plt.title("Average context depth score by manager")
    plt.xlabel("Context depth score")
    plt.ylabel("")
    plt.tight_layout()
    plt.savefig(out_dir / "manager_context_depth.png", dpi=180)
    plt.close()

    plt.figure(figsize=(12, 6))
    monthly = df.groupby(["month", "primary_desire"]).size().reset_index(name="tickets")
    top_desires = df["primary_desire"].value_counts().head(8).index
    monthly = monthly[monthly["primary_desire"].isin(top_desires)]
    sns.lineplot(data=monthly, x="month", y="tickets", hue="primary_desire", marker="o")
    plt.xticks(rotation=45, ha="right")
    plt.title("User desire trends over time")
    plt.xlabel("Month")
    plt.ylabel("Tickets")
    plt.tight_layout()
    plt.savefig(out_dir / "desire_trends.png", dpi=180)
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x="context_depth_band", y="context_depth_score", hue="is_unresolved")
    plt.title("Context depth distribution and unresolved outcome")
    plt.xlabel("Context depth band")
    plt.ylabel("Context depth score")
    plt.tight_layout()
    plt.savefig(out_dir / "context_depth_vs_outcome.png", dpi=180)
    plt.close()


def write_markdown_report(
    out_dir: Path,
    df: pd.DataFrame,
    manager_summary: pd.DataFrame,
    adjusted: pd.DataFrame,
    desire: pd.DataFrame,
    cluster_summary: pd.DataFrame,
    backend_info: pd.DataFrame,
) -> None:
    """Compose the human-facing ``executive_findings.md`` summary.

    Renders a Markdown report with: a header (timestamps, counts, resolved
    share, NLP backend), a "what this measures" preamble, the top manager
    by context depth, the top 8 desires, the top 10 semantic clusters, and
    the OLS-adjusted manager deltas. This is the file a non-technical
    stakeholder reads first.

    Args:
        out_dir: Run output directory.
        df: Enriched + clustered ticket DataFrame.
        manager_summary: Output of :func:`build_manager_summary`.
        adjusted: Output of :func:`adjusted_manager_context`.
        desire: Output of :func:`desire_summary`.
        cluster_summary: Output of :func:`cluster_texts`.
        backend_info: One-row backend-provenance DataFrame.

    Teaching:
        - Building a list of strings and ``"\\n".join(...)``-ing once at the
          end is dramatically faster than ``+=`` string concatenation in a
          loop (Python strings are immutable, so each ``+=`` allocates).
        - ``manager_summary.iloc[0].to_dict()`` grabs the top row (after
          sorting in :func:`build_manager_summary`) and turns it into a
          dict for easy ``.get()`` access.
        - The ``len(...) else {}`` guard prevents an IndexError when a
          frame is empty — common defensive idiom for "default to empty".
        - ``f"{x:.1%}"`` is the percent-format specifier: takes a 0-1 float
          and renders it as ``"23.4%"``. Equivalent to manually multiplying
          by 100 and appending ``%``.
        - ``timespec="seconds"`` on ``datetime.now().isoformat()`` trims the
          microseconds tail (``2026-05-03T14:30:11`` rather than
          ``2026-05-03T14:30:11.123456``).
        - ``write_text(..., encoding="utf-8")`` is explicit about encoding
          — important on Windows, where the default would be ``cp1252`` and
          would corrupt CJK and Cyrillic characters in the report.
    """
    top_manager = manager_summary.iloc[0].to_dict() if len(manager_summary) else {}
    top_desire = desire.iloc[0].to_dict() if len(desire) else {}
    backend = backend_info.iloc[0].to_dict().get("nlp_backend", "unknown") if len(backend_info) else "unknown"
    resolved = float(df["is_resolved"].mean()) if len(df) else 0.0
    rich_share = float(df["context_depth_band"].isin(["rich", "forensic"]).mean()) if len(df) else 0.0

    lines = [
        "# Option 2 User-Needs Analysis",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Tickets analyzed: {len(df):,}",
        f"Unique users: {df.loc[df['uid'].astype(str).str.strip().ne(''), 'uid'].nunique():,}",
        f"Date range: {df['date'].min().date() if df['date'].notna().any() else 'unknown'} to {df['date'].max().date() if df['date'].notna().any() else 'unknown'}",
        f"Resolved share: {resolved:.1%}",
        f"Rich/forensic context share: {rich_share:.1%}",
        f"NLP backend used: {backend}",
        "",
        "## What This Pipeline Measures",
        "",
        "This analysis treats long notes as evidence, not noise. It extracts URLs, screenshots, timestamps, ban/reason language, room/group IDs, user claims, money/SVIP/account signals, and multiline forensic detail. The context_depth_score is designed to reward tickets that make downstream analysis and escalation possible.",
        "",
        "## Strongest Context Signal",
        "",
    ]
    if top_manager:
        lines.append(
            f"Top manager by average context depth: {top_manager.get('manager')} "
            f"with score {top_manager.get('avg_context_score')} across {int(top_manager.get('tickets', 0)):,} tickets."
        )
    lines += ["", "## Top Human Desires", ""]
    for _, row in desire.head(8).iterrows():
        lines.append(
            f"- {row['desire']}: {int(row['tickets']):,} tickets, unresolved {row['unresolved_share']:.1%}, avg context {row['avg_context_score']}"
        )
    lines += ["", "## Largest Semantic Clusters", ""]
    for _, row in cluster_summary[cluster_summary["cluster_id"] != -1].sort_values("tickets", ascending=False).head(10).iterrows():
        lines.append(
            f"- Cluster {int(row['cluster_id'])}: {int(row['tickets']):,} tickets; terms: {row['top_terms']}; desires: {row['top_desires']}"
        )
    if (cluster_summary["cluster_id"] == -1).any():
        noise = cluster_summary[cluster_summary["cluster_id"] == -1].iloc[0]
        lines.append(f"- Noise/outlier tickets: {int(noise['tickets']):,}; these are good candidates for manual review or new emerging issue discovery.")

    lines += ["", "## Adjusted Manager Context Model", ""]
    if "note" in adjusted.columns:
        lines.append(str(adjusted["note"].iloc[0]))
    else:
        lines.append("Positive deltas mean the manager writes richer evidence after controlling for category, question kind, role, status, and month.")
        for _, row in adjusted.head(8).iterrows():
            lines.append(
                f"- {row['manager']}: delta {row['adjusted_context_delta_vs_baseline']}, p={row['p_value']}, baseline={row['baseline_manager']}"
            )

    lines += [
        "",
        "## Output Files",
        "",
        "- enriched_tickets.csv: row-level analytical dataset with evidence/context/desire features",
        "- manager_context_quality.csv: manager comparison that rewards rich evidence",
        "- adjusted_manager_context_model.csv: statistical control model for manager context depth",
        "- desire_summary.csv: human-desire taxonomy, volume, unresolved share",
        "- semantic_clusters.csv: discovered clusters/topics from text",
        "- semantic_cluster_assignments.csv: row-level cluster assignments and 2D coordinates",
        "- semantic_ticket_map.html: interactive semantic map if Plotly/UMAP are available",
        "- charts/*.png: manager/context/desire visuals",
        "- parquet/*.parquet: analytical table copies for fast Python/R/Julia/DuckDB use",
        "- analysis.duckdb: local analytical database with all output tables",
    ]
    (out_dir / "executive_findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_excel(out_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Write all output tables to a single multi-sheet Excel workbook.

    Args:
        out_dir: Run output directory; the workbook lands at
            ``option2_analysis_workbook.xlsx``.
        tables: Dict of ``{table_name: dataframe}``. Each becomes one sheet.

    Teaching:
        - ``pd.ExcelWriter`` used as a context manager (``with ... as``)
          opens the file, lets us add multiple sheets, and finalises on exit
          — the ``__exit__`` method writes the workbook header and closes
          the file. Without the ``with``, you'd need ``writer.close()``
          manually.
        - ``engine="openpyxl"`` is the pure-Python xlsx writer (no native
          deps); slower than ``xlsxwriter`` but ships with most installs.
        - Excel sheet names have hard limits: max 31 chars, no special chars
          like ``/ \\ ? * [ ]``. The ``re.sub(r"[^A-Za-z0-9 _-]", "", name)``
          strips anything else; ``[:31]`` truncates; ``or "Sheet"`` provides
          a fallback if the name was entirely junk.
        - ``table.head(1_000_000)`` caps row count — Excel's hard limit is
          1,048,576 rows per sheet; we leave a safety margin. The underscore
          numeric literal is just readability sugar (Python 3.6+).
    """
    path = out_dir / "option2_analysis_workbook.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, table in tables.items():
            safe = re.sub(r"[^A-Za-z0-9 _-]", "", name)[:31] or "Sheet"
            table.head(1_000_000).to_excel(writer, sheet_name=safe, index=False)


def export_analytical_store(out_dir: Path, tables: dict[str, pd.DataFrame]) -> None:
    """Write Parquet copies of every table and a DuckDB database with all of them.

    Two analytical stores, complementary:

    * **Parquet** files (``parquet/<name>.parquet``) — columnar, compressed,
      ~10x faster than CSV for large reads, and supported by every modern
      data tool (pandas, polars, R/arrow, Spark, DuckDB).
    * **DuckDB** database (``analysis.duckdb``) — a single-file embedded SQL
      database. Lets analysts run SQL queries across tables with joins and
      window functions without spinning up Postgres. Two views are also
      created: ``manager_context_rank`` (sorted manager quality) and
      ``high_risk_user_needs`` (desires with high unresolved share or rich
      context).

    Args:
        out_dir: Run output directory.
        tables: ``{name: dataframe}``.

    Teaching:
        - Why both? Parquet is a portable file format; DuckDB is a query
          engine. Some analysts open the parquet files directly in pandas;
          others connect to the DuckDB file with ``duckdb.connect()``.
          Writing both costs little and serves both audiences.
        - ``con.register("_tmp_table", table)`` creates a temporary view of
          the pandas DataFrame inside DuckDB without copying the data —
          DuckDB reads the underlying numpy arrays directly. Then
          ``CREATE OR REPLACE TABLE ... AS SELECT * FROM _tmp_table`` copies
          the data into a real DuckDB table; we ``unregister`` afterwards
          to keep the namespace clean.
        - ``re.sub(r"[^A-Za-z0-9_]", "_", name).lower()`` produces a SQL-safe
          table name (``high_context_examples`` not ``high-context examples``).
        - The ``try/finally`` guarantees ``con.close()`` runs even if a
          query raises — proper resource hygiene for database handles.
        - ``CREATE OR REPLACE`` makes the export idempotent: running the
          pipeline a second time into the same database is safe.
    """
    parquet_dir = out_dir / "parquet"
    ensure_dir(parquet_dir)
    for name, table in tables.items():
        table.to_parquet(parquet_dir / f"{name}.parquet", index=False)

    try:
        import duckdb
    except Exception as exc:
        print(f"[warn] DuckDB unavailable; database export skipped: {exc}", file=sys.stderr)
        return

    con = duckdb.connect(str(out_dir / "analysis.duckdb"))
    try:
        for name, table in tables.items():
            safe = re.sub(r"[^A-Za-z0-9_]", "_", name).lower()
            con.register("_tmp_table", table)
            con.execute(f'CREATE OR REPLACE TABLE "{safe}" AS SELECT * FROM _tmp_table')
            con.unregister("_tmp_table")
        con.execute(
            """
            CREATE OR REPLACE VIEW manager_context_rank AS
            SELECT *
            FROM manager_context_quality
            ORDER BY avg_context_score DESC, tickets DESC
            """
        )
        con.execute(
            """
            CREATE OR REPLACE VIEW high_risk_user_needs AS
            SELECT desire, tickets, unresolved_share, avg_context_score
            FROM desire_summary
            WHERE unresolved_share >= 0.20 OR avg_context_score >= 24
            ORDER BY unresolved_share DESC, tickets DESC
            """
        )
    finally:
        con.close()


def run(args: argparse.Namespace) -> Path:
    """Top-level orchestrator. Reads CSV, runs every stage, writes all outputs.

    Args:
        args: Argparse namespace from :func:`parse_args`. Must include
            ``input``, ``output_dir``, ``embedding_backend``, ``embedding_model``.

    Returns:
        The path to the timestamped run directory.

    Raises:
        FileNotFoundError: If ``args.input`` does not point to a real file.

    Teaching:
        - ``Path(args.input).expanduser().resolve()`` is the canonical way
          to take a user-supplied path string and produce an absolute path:
          ``expanduser()`` swaps ``~`` for the home directory; ``resolve()``
          makes it absolute and follows symlinks.
        - ``datetime.now().strftime("%Y%m%d_%H%M%S")`` produces a sortable
          timestamp like ``20260503_143011``. Used in the output directory
          name so concurrent runs don't collide and historical runs sort
          chronologically in a file listing.
        - ``getattr(args, "keep_pivot_columns", False)`` reads an attribute
          with a default — defends against older Namespaces that predate the
          flag (so you can call ``run(args)`` from a notebook without
          rebuilding the parser).
        - The ``tables`` dict is the single source of truth for "what's in
          this run": every output (CSV, Excel sheet, parquet file, DuckDB
          table) is generated from it. Adding a new analytical table = one
          new dict entry + one new SQL view.
        - ``json.dumps(metadata, indent=2)`` pretty-prints. The metadata
          file (``run_metadata.json``) is the audit log — it records input
          path, row counts, dropped column lists, backend used, and
          timestamp. Reproducibility 101.
        - The ``print(json.dumps(...))`` at the end echoes the same metadata
          to stdout so a calling shell script or CI job can capture and
          parse it.
    """
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir).expanduser().resolve() / f"option2_{stamp}"
    ensure_dir(out_dir)

    raw = read_raw_csv(input_path)
    raw_rows = len(raw)
    raw_cols = list(raw.columns)

    if not getattr(args, "keep_pivot_columns", False):
        raw, dropped_cols = drop_noise_columns(raw)
        if dropped_cols:
            print(
                f"[info] Dropped {len(dropped_cols)} colleague pivot/cohort columns: "
                + ", ".join(repr(c) for c in dropped_cols),
                file=sys.stderr,
            )
    else:
        dropped_cols = []

    if not getattr(args, "keep_summary_rows", False):
        raw, dropped = drop_summary_rows(raw)
        if dropped:
            print(
                f"[info] Dropped {dropped:,} summary/aggregation rows "
                f"(rows with no Question text and no UID).",
                file=sys.stderr,
            )
    else:
        dropped = 0
    cleaned = canonicalize(raw)
    enriched = featurize_tickets(cleaned)

    manager_summary = build_manager_summary(enriched)
    adjusted = adjusted_manager_context(enriched)
    examples = top_examples(enriched)
    desire = desire_summary(enriched)
    network_nodes = build_network(enriched, out_dir)

    cluster_assignments, cluster_summary, backend_info = cluster_texts(
        enriched,
        out_dir=out_dir,
        backend=args.embedding_backend,
        model_name=args.embedding_model,
    )

    enriched_with_clusters = enriched.merge(
        cluster_assignments[["source_row", "cluster_id", "cluster_probability", "x", "y", "nlp_backend"]],
        on="source_row",
        how="left",
    )

    tables = {
        "enriched_tickets": enriched_with_clusters,
        "manager_context_quality": manager_summary,
        "adjusted_manager_context_model": adjusted,
        "desire_summary": desire,
        "semantic_clusters": cluster_summary,
        "semantic_cluster_assignments": cluster_assignments,
        "high_context_examples": examples,
        "network_nodes": network_nodes,
    }
    for name, table in tables.items():
        table.to_csv(out_dir / f"{name}.csv", index=False)
    export_excel(out_dir, tables)
    export_analytical_store(out_dir, tables)
    create_charts(enriched_with_clusters, manager_summary, out_dir)
    write_markdown_report(out_dir, enriched_with_clusters, manager_summary, adjusted, desire, cluster_summary, backend_info)

    metadata = {
        "input": str(input_path),
        "output_dir": str(out_dir),
        "rows_in_csv": int(raw_rows),
        "rows_dropped_as_summary": int(dropped),
        "rows_after_cleaning": int(len(raw)),
        "rows_enriched": int(len(enriched_with_clusters)),
        "columns_in_csv": int(len(raw_cols)),
        "columns_dropped_as_noise": dropped_cols,
        "embedding_backend_requested": args.embedding_backend,
        "nlp_backend_used": backend_info.to_dict(orient="records"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return out_dir


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments for the pipeline.

    Args:
        argv: A list of CLI tokens (typically ``sys.argv[1:]``).

    Returns:
        An :class:`argparse.Namespace` with attributes ``input``,
        ``output_dir``, ``embedding_backend``, ``embedding_model``,
        ``keep_summary_rows``, ``keep_pivot_columns``.

    Teaching:
        - ``argparse`` is the stdlib CLI parser. ``add_argument`` declares
          one flag at a time. The dashes in ``--output-dir`` get converted
          to underscores in the namespace (``args.output_dir``).
        - ``choices=["tfidf", "local", "openai"]`` does input validation
          for free: argparse rejects any other value with a friendly error.
        - ``action="store_true"`` makes a boolean flag — present means
          ``True``, absent means ``False``. No value follows the flag.
        - ``default=...`` provides the value when a flag isn't supplied.
        - Taking ``argv`` as a parameter (rather than reading
          ``sys.argv`` internally) makes the function testable: a unit test
          can call ``parse_args(["--input", "x.csv"])`` directly.
        - The ``help=`` strings show up under ``-h``/``--help``. Triple-quoted
          parenthesised strings concatenate at compile time — neat way to
          keep long help wrapped in source.
    """
    parser = argparse.ArgumentParser(description="Run Option 2 data-science/NLP analysis on support ticket CSV.")
    parser.add_argument("--input", default="data_2may.csv", help="Path to source CSV")
    parser.add_argument("--output-dir", default="outputs", help="Directory for analysis outputs")
    parser.add_argument(
        "--embedding-backend",
        choices=["tfidf", "local", "openai"],
        default="tfidf",
        help="tfidf is fully local/no model download; local uses sentence-transformers; openai uses OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--embedding-model",
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="Local sentence-transformers model or OpenAI embedding model name.",
    )
    parser.add_argument(
        "--keep-summary-rows",
        action="store_true",
        help=(
            "Keep rows that have no Question text and no UID. "
            "By default these colleague-added empty/aggregation rows are dropped."
        ),
    )
    parser.add_argument(
        "--keep-pivot-columns",
        action="store_true",
        help=(
            "Keep colleague-added Google-Sheets pivot/cohort columns "
            "(Role/SVIP cohort dates, Russian Статус used as a count column). "
            "By default these are dropped at ingest."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    run(parse_args(sys.argv[1:]))
