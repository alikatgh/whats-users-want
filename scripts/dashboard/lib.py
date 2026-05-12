"""Shared helpers for the dashboard pages.

Auto-discovers run directories under ``outputs/option2_*`` and exposes a tiny
catalog API so each page can ask for "the latest run", "all runs", or "table X
from run Y" without reinventing it.

Teaching
--------
This module is imported by every Streamlit page in this dashboard. Treat it as
a tiny "library of conveniences" — none of these functions are mathematically
deep, but together they spare each page from re-implementing path handling,
caching, defensive parsing, and column renaming.

A few cross-cutting Python / data-science ideas appear repeatedly here:

* **Pathlib over strings.** ``Path(__file__).resolve().parents[2]`` walks two
  parents above the current file and resolves any symlinks; the result is the
  project root. We never join paths with ``"/"`` or ``os.path.join`` — the
  ``/`` operator on a ``Path`` does the right thing on every operating system.

* **Streamlit caching.** ``@st.cache_data`` and ``@st.cache_resource`` are
  function decorators. The first time a decorated function is called with a
  given set of argument values, the result is computed and stored. Every
  subsequent call with the same arguments returns the stored value instantly.
  Streamlit reruns the page top-to-bottom on every interaction, so without
  this caching even a small CSV would be re-read on every click.

* **Defensive coercion.** ``safe_int`` / ``safe_float`` wrap a ``try/except``
  around ``int(value)`` / ``float(value)``. Real-world CSV cells are dirty —
  empty strings, ``None``, the literal text "NaN" — and crashing on the first
  bad cell would make the dashboard unusable.

* **Code-to-human dictionaries.** ``DESIRE_LABELS`` and ``JOB_TITLE_PREFIX``
  map the machine-readable codes the analysis pipeline emits ("recover_access")
  to the friendly labels users see ("Recover account access"). Keeping the
  mapping in one place lets every page render the same words.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

#: Project root directory (``/Users/.../2026-what-users``).
#:
#: ``Path(__file__)`` is the path to this file. ``.resolve()`` converts it to
#: an absolute, symlink-free path. ``.parents`` is a tuple-like sequence where
#: ``parents[0]`` is the immediate parent directory, ``parents[1]`` the
#: grandparent, and so on. We are at ``scripts/dashboard/lib.py``, so
#: ``parents[2]`` walks up to the project root. This lets the dashboard locate
#: the ``outputs/`` folder no matter where the user invokes Streamlit from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Directory holding every analysis run. Each subdirectory inside
#: ``outputs/option2_<timestamp>/`` is one full run with its own CSVs.
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def list_runs() -> list[Path]:
    """Return every ``option2_*`` run directory, newest first.

    The dashboard wants to show "the latest run" by default and let users pick
    older runs from a dropdown. This function is the canonical way to enumerate
    them.

    Returns:
        Sorted list of ``Path`` objects, one per run directory. Sorting is by
        directory name in reverse, which works because the names embed a
        timestamp in ``YYYYMMDD_HHMMSS`` format — lexicographic sort and
        chronological sort agree.

    Teaching:
        ``Path.glob("option2_*")`` is the pathlib equivalent of the shell
        ``ls outputs/option2_*``. The ``*`` is a wildcard. The list
        comprehension ``[p for p in ... if p.is_dir()]`` drops anything that is
        not a directory (e.g. a stray ``.zip`` file). ``sorted(..., key=...,
        reverse=True)`` is the standard Python idiom for custom sorting; we
        sort by ``p.name`` (a string) and ask for descending order.
    """
    runs = sorted(
        [p for p in OUTPUTS_DIR.glob("option2_*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    return runs


def latest_run() -> Path | None:
    """Return the most recent run directory, or ``None`` if there are none.

    A convenience wrapper that picks the first item out of :func:`list_runs`.
    Returning ``None`` rather than raising lets callers handle a fresh-clone
    state ("no runs yet") gracefully.

    Returns:
        The newest ``option2_*`` directory, or ``None`` when ``outputs/`` is
        empty.

    Teaching:
        The "first of a sorted-descending list" pattern is everywhere in this
        codebase. It is cheaper than scanning for the maximum and reads
        naturally: "list the runs, take the first one." The ternary
        ``runs[0] if runs else None`` is Python's preferred way to express
        "default to ``None`` when the list is empty" — an empty list is
        falsy, so ``if runs`` is true only when at least one run exists.
    """
    runs = list_runs()
    return runs[0] if runs else None


def run_label(run_dir: Path) -> str:
    """Build a human-friendly label for a run directory.

    Used in the sidebar dropdown so users see ``"option2_20260415_142233  ·
    2026-04-15 14:22"`` instead of a raw folder name. If the trailing portion
    isn't a parseable timestamp, falls back to the raw name.

    Args:
        run_dir: Path to a run directory under ``outputs/``.

    Returns:
        A pretty label combining the directory name with a parsed datetime.

    Teaching:
        ``datetime.strptime(stamp, "%Y%m%d_%H%M%S")`` parses a string into a
        datetime object using a format string (``%Y`` = 4-digit year, ``%m`` =
        month, etc.). The reverse, ``dt.strftime("%Y-%m-%d %H:%M")``, formats a
        datetime back into a string. The whole thing is wrapped in
        ``try/except ValueError`` because ``strptime`` raises ``ValueError``
        when the input doesn't match the format — and we'd rather show the raw
        folder name than crash the page.
    """
    stamp = run_dir.name.replace("option2_", "")
    try:
        dt = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
        return f"{run_dir.name}  ·  {dt.strftime('%Y-%m-%d %H:%M')}"
    except ValueError:
        return run_dir.name


@st.cache_data(show_spinner=False)
def list_csvs(run_dir_str: str) -> list[str]:
    """List every ``*.csv`` file in a run directory, sorted by name.

    Args:
        run_dir_str: Path to the run directory, as a string. (Streamlit's cache
            requires hashable arguments; a ``Path`` object is technically
            hashable but converting to ``str`` makes the cache key obvious.)

    Returns:
        Sorted list of bare CSV file names (no directory prefix).

    Teaching:
        The ``@st.cache_data(show_spinner=False)`` decorator memoises this
        function: Streamlit hashes the argument values, looks up the result in
        a dict, and returns the cached value when the same call comes in
        again. ``show_spinner=False`` suppresses the "Running list_csvs…"
        overlay because this is fast enough that the spinner would be
        distracting. The cache key is the function name plus the arguments,
        so calling ``list_csvs("path/A")`` and ``list_csvs("path/B")`` gets
        two separate cache entries.
    """
    return sorted(p.name for p in Path(run_dir_str).glob("*.csv"))


@st.cache_data(show_spinner=False)
def list_other_files(run_dir_str: str) -> dict[str, list[str]]:
    """Group every non-CSV file in a run by extension.

    Used by the home page to show how many JSON / JSONL / HTML / XLSX / MD /
    PNG files this run produced. The keys of the returned dict are file
    extensions without the dot.

    Args:
        run_dir_str: Path to the run directory, as a string.

    Returns:
        Dict like ``{"json": ["status.json", ...], "jsonl": [...], ...}``,
        with each list sorted alphabetically.

    Teaching:
        A dict comprehension would be slightly more compact, but the explicit
        listing makes the supported extensions discoverable at a glance.
        ``Path.glob("*.json")`` matches every file ending in ``.json``; it
        does not recurse into subdirectories — for that you would use
        ``rglob`` or ``glob("**/*.json")``.
    """
    run_dir = Path(run_dir_str)
    return {
        "json": sorted(p.name for p in run_dir.glob("*.json")),
        "jsonl": sorted(p.name for p in run_dir.glob("*.jsonl")),
        "html": sorted(p.name for p in run_dir.glob("*.html")),
        "xlsx": sorted(p.name for p in run_dir.glob("*.xlsx")),
        "md": sorted(p.name for p in run_dir.glob("*.md")),
        "png": sorted(p.name for p in run_dir.glob("*.png")),
    }


@st.cache_data(show_spinner=False)
def load_csv(run_dir_str: str, name: str) -> pd.DataFrame:
    """Load a CSV from the run, returning an empty DataFrame when missing.

    Args:
        run_dir_str: Path to the run directory, as a string.
        name: Bare file name, e.g. ``"enriched_tickets.csv"``.

    Returns:
        A pandas DataFrame, or an empty DataFrame if the file does not exist.

    Teaching:
        Returning an empty DataFrame on missing-file is a deliberate design
        choice: callers can do ``len(df)`` or ``df.columns`` without first
        checking ``None``, and any ``.head()`` / ``.value_counts()`` will
        simply return empty results. The cost is that callers can't tell
        "missing" from "empty" — when that distinction matters, use
        :func:`maybe_load_csv` instead.
    """
    path = Path(run_dir_str) / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def maybe_load_csv(run_dir: Path, name: str) -> pd.DataFrame | None:
    """Load a CSV, returning ``None`` when the file is absent.

    Use this when "the file isn't there" should trigger a different code path
    (e.g. a warning, a fallback table, an early ``st.stop()``). Internally
    this still goes through the cached :func:`load_csv` once existence is
    confirmed.

    Args:
        run_dir: Run directory.
        name: Bare file name relative to ``run_dir``.

    Returns:
        DataFrame on success, ``None`` if the file does not exist.

    Teaching:
        The pattern of "two functions, one returns a sentinel and one returns
        ``None``" is a common Python convention. The ``Optional[T]`` return
        type (written ``T | None`` since Python 3.10) signals to readers and
        to type checkers that the caller must handle a missing value.
    """
    path = run_dir / name
    if not path.exists():
        return None
    return load_csv(str(run_dir), name)


@st.cache_data(show_spinner=False)
def load_json(run_dir_str: str, name: str) -> dict[str, Any] | None:
    """Read a JSON file from the run, returning ``None`` on any failure.

    Args:
        run_dir_str: Path to the run directory, as a string.
        name: Bare file name, e.g. ``"llm_extraction_status.json"``.

    Returns:
        Parsed JSON as a dict, or ``None`` if the file is missing or invalid.

    Teaching:
        ``json.loads(text)`` parses a JSON string into Python objects:
        objects become dicts, arrays become lists, etc. The bare
        ``except Exception`` is intentionally broad because we genuinely
        don't care *why* parsing failed — the dashboard should just degrade
        gracefully when a sidecar file is corrupt. In production code you
        would normally catch only the specific exceptions you expect
        (``json.JSONDecodeError``, ``UnicodeDecodeError``, etc.).
    """
    path = Path(run_dir_str) / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def jsonl_line_count(path: Path) -> int:
    """Count the number of lines in a JSONL file.

    JSONL ("JSON Lines") files store one JSON record per line, which makes
    them append-friendly during long extractions. Counting lines is the
    cheapest possible "how many records have we written so far" check.

    Args:
        path: Path to the JSONL file.

    Returns:
        Number of lines, or 0 if the file does not exist.

    Teaching:
        ``sum(1 for _ in f)`` is the idiomatic Python "count items in an
        iterable" expression. It opens the file, walks line-by-line (files
        are iterable line-by-line in Python), produces a ``1`` for each, and
        sums them. Crucially it never holds the whole file in memory — even
        a 10-GB JSONL costs ~constant memory.
    """
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def tail_jsonl(path: Path, n: int = 25) -> list[dict[str, Any]]:
    """Return the last ``n`` parsed records from a JSONL file.

    Used by the live extraction monitor to show "the most recent N tickets the
    model just processed." Bad lines (mid-write or truncated) are skipped
    silently.

    Args:
        path: Path to the JSONL file.
        n: Number of trailing lines to read.

    Returns:
        List of parsed records (dicts), in original order. Empty list if the
        file is missing.

    Teaching:
        ``f.readlines()[-n:]`` is the simplest way to take the last ``n``
        lines, but it loads the whole file. For very large files you would
        seek to ``size - some_buffer`` and walk forward. For a few-hundred-MB
        extraction log, the simple version is fine. The per-line ``try /
        except continue`` is the live-monitor's defense against reading a
        line while the writer is mid-flush.
    """
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def file_mtime(path: Path) -> datetime | None:
    """Return the file's last-modified time as a ``datetime``.

    Used to detect "is the extraction still running?" by comparing the JSONL
    file's mtime to ``datetime.now()``.

    Args:
        path: Any file path.

    Returns:
        The modification timestamp, or ``None`` if the file does not exist.

    Teaching:
        ``Path.stat()`` returns an ``os.stat_result`` with file metadata.
        ``st_mtime`` is "modified time" as a Unix timestamp (seconds since
        1970). ``datetime.fromtimestamp(...)`` converts it to a localised
        ``datetime`` object. ``Path.exists()`` is the safe pre-check; calling
        ``.stat()`` on a missing file would raise ``FileNotFoundError``.
    """
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime)


def file_size_bytes(path: Path) -> int:
    """Return the file size in bytes, or 0 if the file is missing.

    Args:
        path: Any file path.

    Returns:
        Size in bytes, or 0 when the file does not exist.

    Teaching:
        ``stat().st_size`` is the byte size on disk, which can differ from
        the in-memory pandas footprint by 5-50x depending on dtypes. We use
        this only for "how big is the file on disk" displays, not for
        memory-pressure decisions.
    """
    return path.stat().st_size if path.exists() else 0


def human_size(num: int) -> str:
    """Format a byte count as a short human-readable string.

    ``human_size(1536)`` returns ``"1.5 KB"``. ``human_size(0)`` returns
    ``"0 B"``. The largest unit is TB.

    Args:
        num: Number of bytes.

    Returns:
        A short string like ``"42 B"``, ``"1.5 KB"``, or ``"3.2 GB"``.

    Teaching:
        The ``for unit in [...]`` loop walks the units in ascending size,
        dividing ``num`` by 1024 each round. We stop the first time ``num``
        fits below 1024 in the current unit. The final ``return`` after the
        loop catches anything that exceeded GB (i.e. is now in TB). The
        ``# type: ignore[assignment]`` comment silences a strict type
        checker complaining that ``num`` was declared ``int`` but is being
        rebound to a ``float`` — this is a deliberate, contained mutation.
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} {unit}"
        num /= 1024  # type: ignore[assignment]
    return f"{num:.1f} TB"


def run_picker(label: str = "Run directory") -> Path | None:
    """Render a sidebar dropdown for choosing which run to view.

    Every page calls this near the top so the user always sees a consistent
    "switch run" widget. The default selection is the newest run.

    Args:
        label: Visible label for the selectbox.

    Returns:
        Path to the chosen run, or ``None`` when no runs exist (in which case
        the page should call ``st.stop()``).

    Teaching:
        ``st.sidebar.selectbox`` adds a dropdown to the left-hand sidebar.
        The dict ``options`` maps friendly labels to ``Path`` objects;
        ``list(options.keys())`` is what the user sees, and we recover the
        ``Path`` via ``options.get(sel, runs[0])``. The fallback to
        ``runs[0]`` is paranoid — it should never trigger because ``sel`` is
        always one of the keys we passed in.
    """
    runs = list_runs()
    if not runs:
        st.error(f"No option2_* run directories found under {OUTPUTS_DIR}.")
        return None
    options = {run_label(r): r for r in runs}
    default_label = next(iter(options))
    sel = st.sidebar.selectbox(label, list(options.keys()), index=0)
    return options.get(sel, runs[0])


def kpi_row(items: list[tuple[str, Any, str | None]]) -> None:
    """Render a row of KPI cards using ``st.columns`` and ``st.metric``.

    Args:
        items: A list of ``(label, value, delta)`` tuples. Set ``delta`` to
            ``None`` (or any falsy value) to omit the small change indicator
            beneath the value.

    Teaching:
        ``st.columns(N)`` creates N equally-wide layout columns; using each
        column as a context (``col.metric(...)``) places the widget inside
        that column. ``st.metric`` is Streamlit's KPI primitive: a big
        number, a small label above, and optionally a delta indicator
        showing change.
    """
    cols = st.columns(len(items))
    for col, (label, value, delta) in zip(cols, items):
        col.metric(label, value, delta if delta else None)


def safe_int(value: Any, fallback: int = 0) -> int:
    """Coerce ``value`` to ``int``, returning ``fallback`` on failure.

    Real CSV cells contain empty strings, ``None``, the literal text "NaN",
    booleans — anything but a clean integer. ``int("")`` raises a
    ``ValueError``; ``int(None)`` raises a ``TypeError``. This helper catches
    both and substitutes a default.

    Args:
        value: Anything that *might* be intable.
        fallback: What to return when conversion fails.

    Returns:
        ``int(value)`` on success, ``fallback`` otherwise.

    Teaching:
        Catching multiple exception types in one ``except`` clause uses a
        tuple: ``except (TypeError, ValueError):``. This is the
        "look-before-you-leap" alternative to ``EAFP`` ("easier to ask
        forgiveness than permission"); ``EAFP`` is generally more Pythonic
        when the failure case is rare.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_float(value: Any, fallback: float = 0.0) -> float:
    """Coerce ``value`` to ``float``, returning ``fallback`` on failure.

    The float twin of :func:`safe_int`. See that function's teaching note.

    Args:
        value: Anything that might be floatable.
        fallback: What to return when conversion fails.

    Returns:
        ``float(value)`` on success, ``fallback`` otherwise.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def counts_df(series: pd.Series, name_col: str = "value", count_col: str = "count") -> pd.DataFrame:
    """Convert any Series (typically from value_counts) into a clean 2-column DataFrame.

    Robust against both old-pandas ("series.name == None, index.name == None")
    and new-pandas ("series.name == 'count', index.name == <orig_col>") behavior.

    Args:
        series: A pandas Series, usually the output of ``df[col].value_counts()``.
        name_col: Name to give the column holding the series' index values.
        count_col: Name to give the column holding the values themselves.

    Returns:
        A two-column DataFrame ready for ``px.bar(... x=count_col, y=name_col)``.

    Teaching:
        Across pandas versions the behaviour of ``value_counts().reset_index()``
        is annoyingly inconsistent. In older pandas the index column came back
        named ``"index"`` and the value column was unnamed; in newer pandas the
        index column inherits the original column's name and the value column
        is named ``"count"``. Charts built one way break the other way. The
        bullet-proof workaround used here is: never trust the auto-naming.
        Build the DataFrame manually from ``list(series.index)`` and
        ``list(series.values)`` and assign the column names yourself.
    """
    if series is None or len(series) == 0:
        return pd.DataFrame({name_col: [], count_col: []})
    return pd.DataFrame({name_col: list(series.index), count_col: list(series.values)})


def chart_picker(
    df: pd.DataFrame,
    label_col: str,
    value_col: str,
    key_prefix: str,
    height: int | None = None,
    default: str = "Horizontal bars",
    options: tuple[str, ...] = ("Horizontal bars", "Vertical bars", "Donut", "Treemap", "Table"),
    sort_descending: bool = True,
) -> None:
    """Render a chart-type selector + the chosen visualization of a counts DataFrame.

    Used wherever the dashboard has a "category vs count" relationship. Lets the
    viewer flip between horizontal bars, vertical bars, donut, treemap, funnel,
    pie, or a sortable table without us hardcoding a single shape.

    Args:
        df: Two-column DataFrame, typically the output of :func:`counts_df`.
        label_col: Name of the categorical column (e.g. "Profile").
        value_col: Name of the numeric column (e.g. "Customers").
        key_prefix: Unique string for Streamlit widget keys; lets multiple
            chart_pickers coexist on one page without collisions.
        height: Chart height in pixels. Auto-calculated when omitted.
        default: Default chart type. Must be one of ``options``.
        options: Tuple of chart types to expose. Re-order to taste.
        sort_descending: Whether to sort by ``value_col`` descending.
    """
    import plotly.express as px
    import streamlit as st

    if df is None or len(df) == 0:
        st.info("No data to display.")
        return

    work = df.copy()
    if sort_descending:
        work = work.sort_values(value_col, ascending=False).reset_index(drop=True)

    chart_type = st.radio(
        "View as",
        options,
        index=options.index(default) if default in options else 0,
        horizontal=True,
        key=f"{key_prefix}_chart_type",
    )

    n = len(work)
    auto_h = max(360, 26 * n) if n else 360
    h = height or auto_h

    if chart_type == "Horizontal bars":
        fig = px.bar(work, x=value_col, y=label_col, orientation="h", height=h)
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(fig, use_container_width=True)
    elif chart_type == "Vertical bars":
        fig = px.bar(work, x=label_col, y=value_col, height=h)
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        fig.update_xaxes(tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)
    elif chart_type == "Donut":
        fig = px.pie(work, names=label_col, values=value_col, hole=0.55, height=max(h, 460))
        fig.update_traces(textposition="outside", textinfo="label+percent")
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    elif chart_type == "Pie":
        fig = px.pie(work, names=label_col, values=value_col, height=max(h, 460))
        fig.update_traces(textposition="outside", textinfo="label+percent")
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    elif chart_type == "Treemap":
        fig = px.treemap(work, path=[label_col], values=value_col, height=max(h, 460))
        fig.update_traces(textinfo="label+value+percent root")
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    elif chart_type == "Funnel":
        fig = px.funnel(work, x=value_col, y=label_col, height=h)
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    elif chart_type == "Table":
        total = float(work[value_col].sum()) if len(work) else 0.0
        display = work.copy()
        if total > 0:
            display["Share"] = (display[value_col] / total * 100).round(1).astype(str) + "%"
        st.dataframe(display, use_container_width=True, hide_index=True, height=h)


def manager_view_enabled() -> bool:
    """Return whether manager-comparison content should be shown.

    Reads ``scripts/dashboard/settings.SHOW_MANAGER_COMPARISONS``. Every page
    that surfaces manager names, ranks, or filters should gate that content
    behind this helper so a single flag turns it all on / off.
    """
    try:
        import settings as _s
        return bool(getattr(_s, "SHOW_MANAGER_COMPARISONS", True))
    except Exception:
        return True


def density_picker(key_prefix: str, default: int = 1, label: str = "Layout") -> int:
    """Sidebar-friendly 1 / 2 / 3 column layout selector.

    Returns the number of columns the caller should use for the next set of
    charts. Pair with :func:`column_cycle` to fan a series of charts across
    that many columns automatically.

    Args:
        key_prefix: Unique string for the radio's session key.
        default: Default column count, 1 / 2 / 3.
        label: Optional label shown above the radio.

    Returns:
        ``1``, ``2``, or ``3``.
    """
    import streamlit as st

    options = ["1 column", "2 columns", "3 columns"]
    default_idx = max(0, min(2, default - 1))
    choice = st.radio(
        label,
        options,
        index=default_idx,
        horizontal=True,
        key=f"{key_prefix}_density",
        label_visibility="visible",
    )
    return int(choice[0])


def column_cycle(n: int):
    """Return a stateful "next column" callable that rotates through ``n`` columns.

    Usage::

        n = density_picker("my_page")
        cols = st.columns(n)
        next_col = column_cycle_from(cols)
        with next_col():
            chart_one()
        with next_col():
            chart_two()

    Each call advances to the next column; wraps when it runs out.
    """
    import streamlit as st
    import itertools

    cols = st.columns(n)
    cycler = itertools.cycle(cols)

    def _next():
        return next(cycler)

    return _next


#: Mapping from machine-readable "primary desire" codes to human labels.
#:
#: The extraction pipeline emits short snake_case codes so they are stable
#: across pandas string operations and easy to use as dict keys. The
#: dashboard renders them via :func:`humanize_desire`, which falls back to a
#: title-cased version of the code for any unmapped value.
DESIRE_LABELS = {
    "recover_access": "Recover account access",
    "clear_name_or_get_fairness": "Get fairness / appeal a ban",
    "earn_or_transact_money": "Earn or move money",
    "grow_audience_or_community": "Grow channel or group",
    "gain_status_or_privileges": "Gain SVIP / status",
    "protect_from_abuse_or_scam": "Protect from abuse / scam",
    "fix_product_or_technical_flow": "Report a product issue",
    "understand_rules_or_system_logic": "Understand the rules",
    "customize_identity_or_assets": "Customize profile / identity",
    "play_or_entertainment": "Play games / entertainment",
    "unclear_or_needs_llm": "Unclear (needs review)",
}


def humanize_desire(value: str) -> str:
    """Translate a desire code to its friendly label.

    Falls back to a generic ``"Snake case capitalized"`` rendering when the
    code isn't in :data:`DESIRE_LABELS`. This is what powers every "Primary
    desire" column the user sees in the dashboard.

    Args:
        value: A desire code like ``"recover_access"``.

    Returns:
        The friendly label, or a fallback like ``"Some new desire"``.

    Teaching:
        ``dict.get(key, default)`` returns the default when the key is
        absent — much cleaner than ``if key in d: d[key] else default``.
        The fallback chain ``value.replace("_", " ").capitalize()`` turns
        ``"some_new_code"`` into ``"Some new code"``: this is graceful
        degradation when the pipeline introduces a new code before the
        dashboard's mapping is updated.
    """
    if not isinstance(value, str):
        return ""
    return DESIRE_LABELS.get(value.strip(), value.replace("_", " ").capitalize())


#: Code-to-prefix mapping used by :func:`friendly_want_title` to build
#: deterministic cluster titles when no Gemma-generated cache is available.
JOB_TITLE_PREFIX = {
    "recover_access": "Recover access",
    "prove_innocence": "Appeal a ban",
    "restore_income": "Restore income",
    "grow_channel": "Grow channel / group",
    "avoid_scam": "Stop a scammer",
    "buy_or_sell_diamonds": "Diamond / money issue",
    "gain_status": "SVIP / status",
    "understand_punishment": "Understand the punishment",
    "restore_visibility": "Restore visibility",
    "protect_community": "Protect community",
    "fix_product_flow": "Product issue",
    "customize_identity": "Identity / profile",
    "other": "Other",
}

#: Stopword set for cluster-label cleanup.
#:
#: Tokens we never want as the "subject" in a deterministic friendly title.
#: These are generic concepts that appear in many cluster labels — picking
#: them as the distinctive token would produce useless titles like
#: "Recover access — account". Membership lookup in a ``set`` is O(1).
_FRIENDLY_STOP = {
    "recover", "access", "account", "unban", "regain", "unblocked", "blocks",
    "blocked", "block", "reasons", "reason", "appeal", "want", "wants",
    "punishment", "understand", "restore", "channel", "group", "scam", "avoid",
    "fraudulent", "fraud", "activity", "detection", "prevent", "protect",
    "community", "abusive", "behavior", "reporting", "content", "voice", "room",
    "money", "diamonds", "diamond", "investigate", "transactions", "transaction",
    "action", "dealer", "points", "determine", "level", "status", "receive",
    "gifts", "purchase", "tools", "allow", "notifications", "appeal_unblocked",
    "the", "and", "for", "with", "from",
}


def _top_job(top_jobs: str) -> str:
    """Return the dominant job string from `top_jobs` like 'recover_access:29, fix:2'.

    The taxonomy CSV stores per-cluster job histograms as a single string —
    job codes paired with counts, joined by commas. We only need the head
    item to label the cluster.

    Args:
        top_jobs: Comma-separated ``"<job>:<count>"`` pairs, e.g.
            ``"recover_access:29, fix_product_flow:2"``.

    Returns:
        The first job code, or ``"other"`` when the input is empty / malformed.

    Teaching:
        The leading underscore in ``_top_job`` marks this as "module-private"
        — Python doesn't enforce visibility, but the convention tells other
        developers "don't import this from outside ``lib``." Splitting twice
        (first on commas, then on colons) is the simplest robust way to
        extract a single field from this micro-format.
    """
    if not isinstance(top_jobs, str) or not top_jobs.strip():
        return "other"
    first = top_jobs.split(",")[0].strip()
    return first.split(":")[0].strip() or "other"


def _distinctive_token(want_label: str) -> str:
    """Pick the first token in want_label that isn't a generic concept.

    Cluster labels look like ``"recover_access_unblocked_dealer"``. We split
    on underscore and take the first token that is (a) longer than 3
    characters and (b) not in :data:`_FRIENDLY_STOP`. The result becomes the
    suffix of a generated title.

    Args:
        want_label: An underscore-joined cluster label.

    Returns:
        The first non-generic token, or an empty string when nothing
        qualifies.

    Teaching:
        The ``parts = [p for p in ... if p]`` list comprehension drops empty
        strings (from leading/trailing underscores). The early ``return tok``
        inside the loop is the standard "first match wins" pattern — much
        cleaner than building a full list and indexing.
    """
    if not isinstance(want_label, str):
        return ""
    parts = [p for p in want_label.split("_") if p]
    for tok in parts:
        if tok.lower() not in _FRIENDLY_STOP and len(tok) > 3:
            return tok
    return ""


def friendly_want_title(want_label: str, top_jobs: str) -> str:
    """Build a short human title from the dominant job + the cluster's distinctive token.

    Used as a deterministic fallback when no Gemma-generated title cache exists.

    Args:
        want_label: Underscore-joined cluster label, e.g.
            ``"recover_access_unblocked_dealer"``.
        top_jobs: Per-cluster job histogram string (see :func:`_top_job`).

    Returns:
        A short title like ``"Recover access — dealer"``. Falls back to just
        the job prefix when no distinctive token can be extracted.

    Teaching:
        "Deterministic" here means: same inputs always produce the same
        output. That matters because the dashboard caches titles, and a
        nondeterministic generator would produce a confusing UX where the
        same cluster shows different names between page reloads. The em-dash
        ``—`` (U+2014) is a typographic touch that distinguishes a generated
        title from a raw underscore-joined cluster ID.
    """
    if not isinstance(want_label, str):
        return "(unlabelled)"
    job = _top_job(top_jobs)
    base = JOB_TITLE_PREFIX.get(job, "Other")
    tok = _distinctive_token(want_label)
    if tok:
        return f"{base} — {tok}"
    return base


def load_human_labels(run_dir: Path) -> dict[int, dict[str, str]]:
    """Load Gemma-generated human titles if the cache exists.

    Returns mapping ``want_id -> {"title": ..., "summary": ...}``. Empty dict if
    the cache file is missing.

    Args:
        run_dir: Run directory that may contain ``user_wants_human_labels.csv``.

    Returns:
        ``{want_id: {"title": ..., "summary": ...}}``. Empty dict when the
        cache is absent or malformed — every page handles "no cache" by
        falling back to :func:`friendly_want_title`.

    Teaching:
        ``df.iterrows()`` yields ``(index, row)`` tuples. Inside the loop we
        defensively cast ``want_id`` to ``int`` because CSVs round-trip
        numeric IDs as strings sometimes. ``str(r.get("col", "")).strip()``
        is the standard "give me a clean string even if the value is NaN"
        idiom — pandas' missing-value sentinel ``NaN`` is a float, and
        ``str(NaN)`` is ``"nan"``, which is rarely what you want; here we
        accept that tradeoff because the truthy/falsy check downstream
        normalises it.
    """
    path = run_dir / "user_wants_human_labels.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if "want_id" not in df.columns or "human_title" not in df.columns:
        return {}
    out: dict[int, dict[str, str]] = {}
    for _, r in df.iterrows():
        try:
            wid = int(r["want_id"])
        except (TypeError, ValueError):
            continue
        out[wid] = {
            "title": str(r.get("human_title", "")).strip(),
            "summary": str(r.get("human_summary", "")).strip() if "human_summary" in df.columns else "",
        }
    return out


def attach_friendly_titles(
    df: pd.DataFrame,
    human_labels: dict[int, dict[str, str]],
    want_id_col: str = "want_id",
    want_label_col: str = "want_label",
    top_jobs_col: str = "top_jobs",
    title_col: str = "want_title",
    summary_col: str = "want_summary",
) -> pd.DataFrame:
    """Add `want_title` and `want_summary` columns using the human cache when present.

    Resolves each row's title in two steps:
    1. If a Gemma-generated title exists for this ``want_id``, use it.
    2. Otherwise fall back to :func:`friendly_want_title`.

    Args:
        df: Source DataFrame; must contain at least ``want_id_col`` and
            ``want_label_col``.
        human_labels: Output of :func:`load_human_labels`.
        want_id_col: Column holding integer cluster IDs.
        want_label_col: Column holding underscore-joined cluster labels.
        top_jobs_col: Column holding the per-cluster job histogram string.
        title_col: Output column name for the friendly title.
        summary_col: Output column name for the friendly summary.

    Returns:
        A copy of ``df`` with ``title_col`` and ``summary_col`` added.

    Teaching:
        Closures over ``human_labels`` (the inner functions ``title_for`` /
        ``summary_for``) are how we pass the lookup table into ``df.apply``
        without making it a global. ``df.apply(fn, axis=1)`` calls ``fn``
        once per row, passing the row as a Series; this is more flexible —
        but slower — than vectorised operations. We use it here because the
        per-row branching (cache hit vs deterministic fallback) is tricky to
        express in pure pandas.
    """
    out = df.copy()

    def title_for(row: pd.Series) -> str:
        try:
            wid = int(row.get(want_id_col))
        except (TypeError, ValueError):
            wid = None
        if wid is not None and wid in human_labels and human_labels[wid].get("title"):
            return human_labels[wid]["title"]
        return friendly_want_title(row.get(want_label_col, ""), row.get(top_jobs_col, ""))

    def summary_for(row: pd.Series) -> str:
        try:
            wid = int(row.get(want_id_col))
        except (TypeError, ValueError):
            wid = None
        if wid is not None and wid in human_labels:
            return human_labels[wid].get("summary", "")
        return ""

    out[title_col] = out.apply(title_for, axis=1) if want_label_col in out.columns else ""
    out[summary_col] = out.apply(summary_for, axis=1) if want_label_col in out.columns else ""
    return out


def status_badge(status: str) -> str:
    """Translate an internal status code to a friendly label.

    Args:
        status: Code like ``"ok"`` / ``"bad_output"`` / ``"error"`` /
            ``"running"`` / ``"idle"`` / ``"done"``.

    Returns:
        The friendly label, or ``status`` itself when no mapping exists.

    Teaching:
        Yet another instance of the code-to-human mapping pattern. By
        keeping the mapping inside the function (rather than as a
        module-level constant) we signal "this lookup is only used here."
        That is fine for small tables; for larger ones, hoist them out so
        callers can import and reuse.
    """
    labels = {
        "ok": "Valid",
        "bad_output": "Flagged",
        "error": "Failed",
        "running": "Running now",
        "idle": "Idle",
        "done": "Done",
    }
    return labels.get(status, status)
