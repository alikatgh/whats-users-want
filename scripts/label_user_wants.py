#!/usr/bin/env python3
"""Use a local Ollama model to write a short human title and summary for each
discovered user-want cluster.

Reads ``user_wants_taxonomy.csv`` from a run directory. For each cluster
(want_id != -1), packages the dominant jobs, dominant emotions, and three
example tickets, then asks the local Ollama model for a 3-7 word title
and a one-sentence summary.

Outputs:
    user_wants_human_labels.csv  with columns:
        want_id, want_label, human_title, human_summary

The dashboard picks this CSV up automatically. Re-run this script after every
new taxonomy build to refresh the labels.

No paid APIs. Requires Ollama running locally with a suitable model pulled
(``ollama pull mistral-small3.2:24b`` is recommended for new runs).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SYSTEM_PROMPT = (
    "You write short human-readable titles for clusters of customer-support "
    "tickets. Each title must be a complete English phrase, 3 to 7 words, "
    "describing what the user is trying to accomplish. Do not use snake_case, "
    "ALL CAPS, or technical jargon. Do not echo the input. Return one valid "
    "JSON object only."
)

USER_TEMPLATE = """Cluster ID: {want_id}
Top jobs to be done: {top_jobs}
Top emotions: {top_emotions}
Average money risk (1-5): {money}
Average trust risk (1-5): {trust}
Average urgency (1-5): {urgency}

Three example tickets in this cluster:
1. {ex1}
2. {ex2}
3. {ex3}

Return JSON like this, with no other text:
{{
  "human_title": "<3 to 7 words, plain English, sentence case>",
  "human_summary": "<one sentence, 12 to 25 words, what this cluster is about>"
}}
"""


def clamp(text: str, n: int) -> str:
    """Normalise whitespace and shorten ``text`` to at most ``n`` characters.

    Used to:

    * Trim each example ticket to 240 characters before feeding it into the
      Gemma prompt (otherwise the prompt explodes past Gemma's small context).
    * Trim Gemma's returned ``human_title`` and ``human_summary`` to safe
      lengths before writing them to CSV.

    Args:
        text: Anything stringy. ``None`` is treated as ``""`` via ``text or ""``.
        n: Maximum length of the output, ellipsis included.

    Returns:
        Cleaned, possibly truncated string.

    Teaching:
        * ``str(text or "")`` — the ``or "")`` guards against ``None``.
          Useful when reading from pandas, which produces ``NaN``/``None`` for
          empty CSV cells.
        * ``re.sub(r"\\s+", " ", ...)`` collapses every run of whitespace
          (including newlines) to a single space — important because the
          Ollama JSON encoder will otherwise embed real newlines into the
          prompt and break length budgeting.
        * The truncation idiom ``text[: n - 3].rstrip() + "..."`` reserves
          room for the three-dot ellipsis and strips trailing whitespace
          left behind by chopping mid-token.
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= n:
        return text
    return text[: n - 3].rstrip() + "..."


def call_ollama(model: str, ollama_url: str, prompt: str, timeout: int) -> dict:
    """Send one chat message to a local Ollama server and return parsed JSON.

    Args:
        model: Ollama model tag, e.g. ``"mistral-small3.2:24b"`` (must already be
            ``ollama pull``-ed).
        ollama_url: Base URL, typically ``http://localhost:11434``.
        prompt: The user-message prompt (system prompt is added here).
        timeout: Seconds to wait before raising ``URLError``.

    Returns:
        The dict produced by :func:`parse_json_object` — possibly ``{}`` if
        the model returned something unparseable.

    Raises:
        RuntimeError: Wraps any ``URLError`` (server down, connection
            refused, timeout) with a helpful message.

    Teaching:
        * **No requests dependency.** This script uses only the standard
          library's ``urllib.request`` so the environment stays minimal.
          The shape: build a ``Request`` object, then ``urlopen`` it inside
          a ``with`` block.
        * **Building the Request.** ``data=json.dumps(payload).encode("utf-8")``
          serialises the body to bytes (``urlopen`` does not encode for
          you). Setting ``Content-Type: application/json`` and ``method=
          "POST"`` makes Ollama's chat endpoint happy.
        * **``format="json"``** is an Ollama-specific option that forces the
          model into a constrained JSON-output mode. This is crucial: small
          models love to wrap their output in prose ("Sure,
          here's the JSON: ..."), and ``format=json`` cuts most of that
          off. ``parse_json_object`` cleans up whatever still leaks through.
        * **``temperature=0``** makes the model deterministic. We want the
          *same* title for the *same* cluster on every run, otherwise the
          dashboard would re-shuffle labels each time you re-cluster.
          ``num_ctx=4096`` reserves enough context for our system prompt
          plus three example tickets.
        * **``urlopen(request, timeout=...)``** raises ``URLError`` on
          connection failure or read timeout. We wrap it with a friendlier
          ``RuntimeError`` (using ``raise ... from exc`` so the original
          exception is preserved as ``__cause__``) so the caller can show a
          one-line "is Ollama running?" hint.
        * **Defensive lookup.** ``(body.get("message") or {}).get("content")``
          — Ollama responses *should* contain a ``message.content``, but
          guarding against both keys missing is cheap insurance against
          API drift.
    """
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        ollama_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {ollama_url}. Is it running? ({exc})"
        ) from exc
    content = (body.get("message") or {}).get("content") or "{}"
    return parse_json_object(content)


def check_ollama_ready(model: str, ollama_url: str, timeout: int = 5) -> None:
    """Fail fast if Ollama or the requested local model is unavailable."""
    request = urllib.request.Request(ollama_url.rstrip("/") + "/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {ollama_url}. Start it with: ollama serve"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama at {ollama_url} returned invalid JSON from /api/tags") from exc

    model_names = {
        str(item.get("name") or item.get("model") or "").strip()
        for item in body.get("models", [])
        if isinstance(item, dict)
    }
    if model_names and model not in model_names:
        raise RuntimeError(
            f"Ollama is running, but model '{model}' is not installed. Run: ollama pull {model}"
        )


def parse_json_object(text: str) -> dict:
    """Best-effort extract a JSON object from a possibly-prose-wrapped string.

    Even with ``format="json"`` set, small local LLMs sometimes emit:

    * ```` ```json {"...": "..."} ``` ```` (markdown code fences),
    * ``Here's the JSON: {"...": "..."}`` (preamble),
    * ``{"...": "..."}\\nThanks!`` (trailing prose),

    none of which ``json.loads`` accepts. This function strips whatever it
    can and returns the parsed dict, or ``{}`` on failure.

    Args:
        text: Raw model output.

    Returns:
        The parsed JSON object, or an empty ``{}`` if parsing fails.

    Teaching:
        Three layers of defence:

        1. **Strip Markdown fences.** The regex
           ``r"^```(?:json)?\\s*|\\s*```$"`` matches an opening fence
           (optionally tagged ``json``) at the start *or* a closing fence at
           the end. ``re.S`` (DOTALL) lets ``.`` match newlines if the regex
           ever needs it. ``re.sub`` with the alternation removes both ends
           in one call.
        2. **Find the outermost braces.** ``text.find("{")`` returns the
           index of the *first* ``{``; ``text.rfind("}")`` returns the index
           of the *last* ``}``. Slicing ``text[start : end + 1]`` keeps
           everything between (inclusive). This handles "Here's the JSON:
           {...}" and "{...}. Thanks!" simultaneously without writing a real
           JSON parser.
        3. **Try / except json.loads.** Even after cleanup, the model may
           emit invalid JSON. Returning ``{}`` lets the caller's validation
           step (``title_is_clean``) flag the cluster as ``bad_output``
           rather than crashing the whole run.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def title_is_clean(title: str) -> bool:
    """Validate that a Gemma-generated title looks like a real human phrase.

    Gemma loves to occasionally regress to:

    * Echoing the input slug (``access_account_recover``).
    * Returning ALL CAPS shouting (``RECOVER ACCOUNT ACCESS``).
    * One-word non-titles (``Recovery``).
    * Paragraph-length essays.

    This function rejects all of those so the caller can mark the cluster
    as ``bad_output`` and either retry or fall back.

    Args:
        title: Candidate title (already :func:`clamp`-ed to 80 chars).

    Returns:
        ``True`` only if the title passes every rule below.

    Teaching:
        Walk through each rule:

        * ``isinstance(title, str)`` — guards against the model returning
          something that isn't a string at all (e.g. a list because the
          JSON contained ``"human_title": ["..."]``).
        * ``len(t) < 4 or len(t) > 80`` — too short means probably a single
          token; too long means the model started writing a summary.
        * ``"_" in t`` — explicit anti-snake_case rule. Our prompt forbids
          underscores, but this catches relapses.
        * ``re.search(r"[A-Z]{4,}", t) and t.upper() == t`` — the ``re.search``
          finds at least one run of 4+ consecutive capitals (so titles like
          "API" don't get punished alone), and ``t.upper() == t`` confirms
          the *whole* title is uppercase. Both must be true to reject. This
          way "Fix API Access" passes but "RECOVER ACCOUNT ACCESS" fails.
        * ``2 <= len(words) <= 9`` — enforces "phrase, not word, not essay".
          We allow up to 9 words (slightly more than the prompt's 7) to be
          forgiving of small overruns.
    """
    if not isinstance(title, str):
        return False
    t = title.strip()
    if len(t) < 4 or len(t) > 80:
        return False
    if "_" in t:
        return False
    if re.search(r"[A-Z]{4,}", t) and t.upper() == t:
        return False
    words = t.split()
    if not (2 <= len(words) <= 9):
        return False
    return True


def main() -> int:
    """CLI entry point: load taxonomy, prompt Gemma per cluster, write labels.

    Returns:
        Exit code (0 on success, 2 if inputs are missing).

    Teaching:
        Five things this orchestrator demonstrates:

        * **Argparse with typed paths.** ``type=Path`` converts the
          positional ``run_dir`` straight into a ``pathlib.Path`` object.
          Cleaner than calling ``Path(args.run_dir)`` everywhere.
        * **Resume-from-cache.** Calling Gemma 30+ times takes minutes; we
          must not re-run it on every script invocation. We read any
          previous ``user_wants_human_labels.csv`` into a dict keyed by
          ``want_id``, and for each cluster we check if a clean title is
          already cached. ``--force`` opts out of this behaviour.
        * **Exclude noise (``want_id != -1``).** The clustering stage marks
          unclusterable rows with ``-1``, just like BERTopic does in Stage
          2. There is no point asking the model to title "the noise bucket".
        * **Status tagging.** Each row gets a ``_status`` field —
          ``cached``, ``ok``, ``bad_output``, or ``error: ...``. This lets
          you grep the CSV later to see which clusters need a manual rewrite
          or a model upgrade, without having to re-run anything.
        * **Metadata sidecar.** ``user_wants_human_labels_meta.json`` records
          when, with which model, and how successfully the labels were
          generated. ``datetime.now(timezone.utc).isoformat(timespec="seconds")``
          gives a sortable, timezone-aware timestamp.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path, help="outputs/option2_<timestamp>")
    parser.add_argument("--model", default="mistral-small3.2:24b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-label every cluster even if the cache file already has it.",
    )
    args = parser.parse_args()

    run_dir: Path = args.run_dir
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2

    taxonomy_path = run_dir / "user_wants_taxonomy.csv"
    if not taxonomy_path.exists():
        print(f"Missing: {taxonomy_path}", file=sys.stderr)
        return 2

    taxonomy = pd.read_csv(taxonomy_path)
    if "want_id" not in taxonomy.columns:
        print("Taxonomy file is missing 'want_id' column.", file=sys.stderr)
        return 2

    out_path = run_dir / "user_wants_human_labels.csv"
    existing: dict[int, dict] = {}
    if out_path.exists() and not args.force:
        prev = pd.read_csv(out_path)
        for _, r in prev.iterrows():
            try:
                existing[int(r["want_id"])] = {
                    "want_label": r.get("want_label", ""),
                    "human_title": r.get("human_title", ""),
                    "human_summary": r.get("human_summary", ""),
                }
            except (TypeError, ValueError):
                continue

    rows = []
    todo = taxonomy[taxonomy["want_id"] != -1].copy()
    needs_model = [
        int(r["want_id"])
        for _, r in todo.iterrows()
        if not (
            int(r["want_id"]) in existing
            and existing[int(r["want_id"])].get("human_title")
            and not args.force
        )
    ]
    print(f"Labelling {len(todo)} clusters with {args.model} via {args.ollama_url} ...")
    if needs_model:
        try:
            check_ollama_ready(args.model, args.ollama_url, timeout=min(args.timeout, 5))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            print("No label file was written; existing cached labels were left unchanged.", file=sys.stderr)
            return 2

    for _, row in todo.iterrows():
        wid = int(row["want_id"])
        if wid in existing and existing[wid].get("human_title") and not args.force:
            rows.append(
                {
                    "want_id": wid,
                    "want_label": row.get("want_label", ""),
                    "human_title": existing[wid]["human_title"],
                    "human_summary": existing[wid].get("human_summary", ""),
                    "_status": "cached",
                }
            )
            continue

        prompt = USER_TEMPLATE.format(
            want_id=wid,
            top_jobs=str(row.get("top_jobs", "")),
            top_emotions=str(row.get("top_emotions", "")),
            money=row.get("avg_money_risk", ""),
            trust=row.get("avg_trust_risk", ""),
            urgency=row.get("avg_urgency", ""),
            ex1=clamp(row.get("example_1", ""), 240),
            ex2=clamp(row.get("example_2", ""), 240),
            ex3=clamp(row.get("example_3", ""), 240),
        )
        try:
            result = call_ollama(args.model, args.ollama_url, prompt, args.timeout)
            title = clamp(result.get("human_title", ""), 80)
            summary = clamp(result.get("human_summary", ""), 220)
            status = "ok" if title_is_clean(title) and summary else "bad_output"
            if status != "ok":
                # Soft fallback: use top job + first distinctive token from want_label
                title = ""
                summary = summary or ""
        except Exception as exc:
            title = ""
            summary = ""
            status = f"error: {exc}"

        row_out = {
            "want_id": wid,
            "want_label": row.get("want_label", ""),
            "human_title": title,
            "human_summary": summary,
            "_status": status,
        }
        rows.append(row_out)
        print(f"  cluster {wid:>3}  status={status:<10}  title='{title}'")

    out = pd.DataFrame(rows)
    out.to_csv(out_path, index=False)
    print(f"\nWrote: {out_path}")
    ok = (out["_status"] == "ok").sum() if "_status" in out.columns else 0
    cached = (out["_status"] == "cached").sum() if "_status" in out.columns else 0
    bad = len(out) - ok - cached
    print(f"OK: {ok}  cached: {cached}  bad/error: {bad}")

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": args.model,
        "ollama_url": args.ollama_url,
        "rows": int(len(out)),
        "ok": int(ok),
        "cached": int(cached),
        "bad_or_error": int(bad),
    }
    (run_dir / "user_wants_human_labels_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
