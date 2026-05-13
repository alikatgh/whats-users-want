#!/usr/bin/env python3
"""Stage 5 — extract structured ticket meaning with a local LLM.

Picks rich tickets from the run directory, builds a prompt, sends each to one
of four backends, validates the output against an enum schema, normalizes
known aliases, and flags bad outputs without throwing them away.

Backends (chosen via ``--backend``):

* ``rules``         — deterministic regex+lookup. Free, no model. Weakest output
  but useful as a baseline for sanity comparison and as the skeleton for the
  hybrid backend.
* ``ollama``        — local LLM via Ollama HTTP API at ``localhost:11434``.
  Default model: ``mistral-small3.2:24b`` for stronger instruction-following
  and structured extraction. Free, no data leaves the machine.
* ``ollama_hybrid`` — runs the rules layer first, then asks the local model
  only for narrative interpretation fields (literal_request, actual_user_want,
  support_next_step, product_opportunity, emotion). Robust on small models.
* ``openai``        — OpenAI Chat Completions with ``response_format=json_object``.
  Optional, requires ``OPENAI_API_KEY``. Currently unused due to no API budget.

Sampling strategies (``--strategy``):

* ``highest_context`` — top N by ``context_depth_score``.
* ``risk_balanced``   — adds money/status/ban_reason/user_claim flags + unresolved
  to a risk score, sorts by risk × context. **Used in the current run.**
* ``issue_balanced``  — round-robin top context per ``issue_label``, padded with
  highest-context leftovers.

The schema (extracted into JSON):

* ``literal_request``, ``actual_user_want`` — free strings.
* ``job_to_be_done`` — one of 13 enum values.
* ``user_emotion`` — one of 9 enum values.
* ``urgency_level``, ``trust_risk_level``, ``money_risk_level``,
  ``safety_policy_risk_level`` — int 1-5.
* ``evidence_present``, ``evidence_missing`` — lists.
* ``entities`` — uids, room_or_group_ids, timestamps, ban_reasons,
  money_or_diamond_amounts, counterparties, url_count.
* ``support_next_step``, ``product_opportunity`` — free strings.
* ``manager_note_quality`` — one of 4 enum values.
* ``needs_human_review`` — bool.
* ``confidence`` — 0-1.

Validation:

* :func:`output_quality_flag` checks for schema-echo, source_row mismatch,
  empty required fields, invalid enums, and overly vague output.
* :func:`normalize_result_enums` rewrites known aliases (``investigate_fraud`` →
  ``avoid_scam``, ``stressed`` → ``anxious``, etc.) and records the original
  value in ``_normalized_*_from``.
* Each result gets ``_status`` ∈ {``ok``, ``bad_output``, ``error``} and the
  raw failure flag in ``_quality_flag``.

Resume support:

* Each backend writes one JSONL line per ticket to ``<output_stem>.jsonl``.
* On rerun without ``--no-resume``, already-processed ``source_row`` values
  are skipped.

See :doc:`docs/engineering/05-stage5-llm` for the full validation pipeline,
:doc:`docs/engineering/08-prompts-and-extraction` for the exact prompts and
alias map, and :doc:`docs/engineering/09-formulas-cheatsheet` for the rule
backend's risk-level formulas.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA: dict[str, Any] = {
    "source_row": "string",
    "literal_request": "short string: what the user explicitly asked for",
    "actual_user_want": "short string: deeper user want behind the request",
    "job_to_be_done": "one of: recover_access, prove_innocence, restore_income, grow_channel, avoid_scam, buy_or_sell_diamonds, gain_status, understand_punishment, restore_visibility, protect_community, fix_product_flow, customize_identity, other",
    "user_emotion": "one of: neutral, confused, anxious, angry, desperate, betrayed, urgent, hopeful, unknown",
    "urgency_level": "integer 1-5",
    "trust_risk_level": "integer 1-5",
    "money_risk_level": "integer 1-5",
    "safety_policy_risk_level": "integer 1-5",
    "evidence_present": ["screenshots", "urls", "timestamps", "uid", "room_or_group_id", "ban_reason", "money_amount", "counterparty", "user_claim", "none"],
    "evidence_missing": ["list of evidence needed to resolve or escalate safely"],
    "entities": {
        "uids": ["string"],
        "room_or_group_ids": ["string"],
        "timestamps": ["string"],
        "ban_reasons": ["string"],
        "money_or_diamond_amounts": ["string"],
        "counterparties": ["string"],
        "url_count": "integer",
    },
    "support_next_step": "specific next operational action",
    "product_opportunity": "what product/system should exist so user does not need to ask again",
    "manager_note_quality": "one of: thin, adequate, rich, forensic",
    "needs_human_review": "boolean",
    "confidence": "number 0-1",
}

SYSTEM_PROMPT = """You are analyzing messy support tickets from IMO/BIGO-style support operations.
Extract what the user actually wants, not only the literal category.
Preserve uncertainty. Do not invent facts. If evidence is missing, say what is missing.
Treat screenshots/URLs/timestamps/ban reasons/IDs as evidence, not noise.
Return exactly one JSON object matching the requested schema. No markdown.
"""

USER_TEMPLATE = """Ticket metadata:
source_row: {source_row}
manager: {manager}
date: {date_raw}
category: {category}
question_kind: {question_kind}
status: {status_en}
primary_desire_rule_based: {primary_desire}
semantic_issue_label: {issue_label}
context_depth_score: {context_depth_score}

Ticket text:
{text}
"""

JOB_VALUES = [
    "recover_access",
    "prove_innocence",
    "restore_income",
    "grow_channel",
    "avoid_scam",
    "buy_or_sell_diamonds",
    "gain_status",
    "understand_punishment",
    "restore_visibility",
    "protect_community",
    "fix_product_flow",
    "customize_identity",
    "other",
]
EMOTION_VALUES = ["neutral", "confused", "anxious", "angry", "desperate", "betrayed", "urgent", "hopeful", "unknown"]
EVIDENCE_VALUES = ["screenshots", "urls", "timestamps", "uid", "room_or_group_id", "ban_reason", "money_amount", "counterparty", "user_claim", "none"]
NOTE_QUALITY_VALUES = ["thin", "adequate", "rich", "forensic"]
JOB_ALIASES = {
    "investigate_fraud": "avoid_scam",
    "report_fraud": "avoid_scam",
    "fraud_report": "avoid_scam",
    "verify_ban_and_reason": "understand_punishment",
    "ban_verification": "understand_punishment",
    "unblock_account": "recover_access",
    "restore_account": "recover_access",
    "account_recovery": "recover_access",
}


def extraction_response_schema() -> dict[str, Any]:
    """Formal JSON Schema used by Ollama structured outputs for full extraction.

    ``SCHEMA`` above is intentionally human-readable because it is written to
    docs and prompt artifacts. Ollama's structured-output mode expects a real
    JSON Schema object, so we keep this machine contract separate and derive
    enum values from the canonical lists.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source_row": {"type": "string"},
            "literal_request": {"type": "string"},
            "actual_user_want": {"type": "string"},
            "job_to_be_done": {"type": "string", "enum": JOB_VALUES},
            "user_emotion": {"type": "string", "enum": EMOTION_VALUES},
            "urgency_level": {"type": "integer", "minimum": 1, "maximum": 5},
            "trust_risk_level": {"type": "integer", "minimum": 1, "maximum": 5},
            "money_risk_level": {"type": "integer", "minimum": 1, "maximum": 5},
            "safety_policy_risk_level": {"type": "integer", "minimum": 1, "maximum": 5},
            "evidence_present": {
                "type": "array",
                "items": {"type": "string", "enum": EVIDENCE_VALUES},
            },
            "evidence_missing": {"type": "array", "items": {"type": "string"}},
            "entities": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "uids": {"type": "array", "items": {"type": "string"}},
                    "room_or_group_ids": {"type": "array", "items": {"type": "string"}},
                    "timestamps": {"type": "array", "items": {"type": "string"}},
                    "ban_reasons": {"type": "array", "items": {"type": "string"}},
                    "money_or_diamond_amounts": {"type": "array", "items": {"type": "string"}},
                    "counterparties": {"type": "array", "items": {"type": "string"}},
                    "url_count": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "uids",
                    "room_or_group_ids",
                    "timestamps",
                    "ban_reasons",
                    "money_or_diamond_amounts",
                    "counterparties",
                    "url_count",
                ],
            },
            "support_next_step": {"type": "string"},
            "product_opportunity": {"type": "string"},
            "manager_note_quality": {"type": "string", "enum": NOTE_QUALITY_VALUES},
            "needs_human_review": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": [
            "source_row",
            "literal_request",
            "actual_user_want",
            "job_to_be_done",
            "user_emotion",
            "urgency_level",
            "trust_risk_level",
            "money_risk_level",
            "safety_policy_risk_level",
            "evidence_present",
            "evidence_missing",
            "entities",
            "support_next_step",
            "product_opportunity",
            "manager_note_quality",
            "needs_human_review",
            "confidence",
        ],
    }


def hybrid_response_schema() -> dict[str, Any]:
    """Formal JSON Schema for the smaller rules+LLM hybrid response."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "literal_request": {"type": "string"},
            "actual_user_want": {"type": "string"},
            "user_emotion": {"type": "string", "enum": EMOTION_VALUES},
            "support_next_step": {"type": "string"},
            "product_opportunity": {"type": "string"},
            "manager_note_quality": {"type": "string", "enum": NOTE_QUALITY_VALUES},
            "needs_human_review": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": [
            "literal_request",
            "actual_user_want",
            "user_emotion",
            "support_next_step",
            "product_opportunity",
            "manager_note_quality",
            "needs_human_review",
            "confidence",
        ],
    }

OLLAMA_SYSTEM_PROMPT = """You extract support-ticket meaning into JSON.
Infer the user's real goal from the ticket. Do not copy labels, enum lists, or template placeholders.
Write concrete short phrases, not enum tokens, for literal_request, actual_user_want, support_next_step, and product_opportunity.
If unsure, use "other", "unknown", empty lists, and lower confidence.
Return one valid JSON object only.
"""

HYBRID_OLLAMA_SYSTEM_PROMPT = """You write concise human interpretation fields for support-ticket analysis.
A deterministic rules layer already extracted IDs, evidence, risk levels, and job classification.
Do not reclassify the ticket. Do not invent facts. Use the supplied evidence and uncertainty.
Return one valid JSON object only.
"""

URL_RE = re.compile(r"https?://\S+", re.I)
IMAGE_RE = re.compile(r"https?://\S+?\.(?:jpg|jpeg|png|webp|gif)(?:\?\S*)?", re.I)
TIMESTAMP_RE = re.compile(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?\b")
UID_RE = re.compile(r"\b\d{8,18}\b")
ROOM_RE = re.compile(r"\b(?:bg|sg|cg|my|voice|room|channel|group)[._:-]?[a-z0-9][a-z0-9._:-]{5,}\b", re.I)
BAN_REASON_RE = re.compile(r"\b(?:pornographic|pornography|moaning|insults?|personal attacks?|severe|abuse|scam|fraud|spam|competitor|blacklist|category [abc]|class [abc]|penalty|violation|ban reason|review reason)\b", re.I)
MONEY_RE = re.compile(r"\b(?:money|withdraw|withdrawal|salary|cash|payment|pay|payout|diamonds?|crystals?|beans?|recharge|top.?up|seller|dealer|reseller|rubles?|₽|income|earn|scammed|fraud)\b", re.I)
TRANSACTION_RE = re.compile(r"\b(?:diamond sales|sent money|took the money|payment|withdraw|withdrawal|recharge|top.?up|diamonds?|crystals?|beans?|seller|buyer|dealer|reseller|rubles?|₽|salary|payout|income)\b", re.I)
SCAM_REPORT_RE = re.compile(r"\b(?:this is a scammer|is a scammer|scammer,|scammed|deceived|tricked|cheated|took the money|sent money|owes|didn'?t send|did not send|send the money back|return the money|official dealer)\b", re.I)
BAN_STATE_RE = re.compile(r"\b(?:ban|banned|blocked|unblock|unblocked|unban|blacklist|penalty|violation|review reason|review time|block start|block duration|category [abc]|class [abc]|voice room ban)\b", re.I)
GAME_RE = re.compile(r"\b(?:game|fishing|fish-themed|fish themed|win|winning|level|play|bonus|lottery|draw)\b", re.I)
ABUSE_REPORT_RE = re.compile(r"\b(?:insult|insults|abuse|abusive|harass|harassment|threat|violence|foul language)\b", re.I)
STATUS_RE = re.compile(r"\b(?:svip|vip|level|points?|badge|status|privilege|frame)\b", re.I)
CLAIM_RE = re.compile(r"\b(?:i did nothing|did absolutely nothing|without reason|no reason|by mistake|mistake|unfair|wrongly|false|i don't know|dont know|do not understand|why was i|why i was|did not violate|didn't violate|not guilty)\b", re.I)
URGENT_RE = re.compile(r"\b(?:urgent|asap|please|plz|help|immediately|now|very|again|many times|still|cannot|can't|failed|why|complaint)\b", re.I)
SNAKE_TOKEN_RE = re.compile(r"[a-z]+(?:_[a-z0-9]+)+", re.I)
GENERIC_PHRASES = {
    "unknown",
    "infer goal",
    "resolve issue",
    "analyze",
    "investigate",
    "n/a",
    "none",
    "fix issue",
    "block user",
    "unblock user",
    "account restored",
    "ban audit",
    "ban verification",
    "ban resolution",
    "improve user experience",
    "improve dispute resolution process",
    "review rule layer and data integrity",
}


def latest_run(outputs_dir: Path) -> Path:
    """Find the most recent ``option2_<timestamp>`` run directory.

    Lets the operator run ``llm_extract_rich_tickets.py`` without re-typing
    the run path each time. The pipeline writes one timestamped subfolder per
    invocation; this helper picks the alphabetically last one that has the
    required ``enriched_tickets.csv`` file.

    Args:
        outputs_dir: The ``outputs/`` directory containing ``option2_*`` runs.

    Returns:
        ``Path`` to the most recent valid run directory.

    Raises:
        FileNotFoundError: If no ``option2_*`` directory contains
            ``enriched_tickets.csv``.

    Teaching:
        ``Path.glob("option2_*")`` returns a generator of paths matching the
        shell-style pattern. Wrapping in ``sorted(...)`` materializes them and
        relies on the fact that ISO-8601 timestamps sort lexicographically the
        same as chronologically — which is why the upstream stages name folders
        ``option2_2026-04-30T14-22-01``. ``runs[-1]`` is the Pythonic "last
        element" idiom; this works because list indexing supports negative
        indices that count from the end.
    """
    runs = sorted([p for p in outputs_dir.glob("option2_*") if (p / "enriched_tickets.csv").exists()])
    if not runs:
        raise FileNotFoundError(f"No option2_* run folders under {outputs_dir}")
    return runs[-1]


def compact(text: str, max_chars: int) -> str:
    """Normalize line endings and truncate ticket text to a character budget.

    LLMs are billed per token (and local models have a fixed ``num_ctx``
    window), so feeding them a 30k-character message is wasteful and will
    sometimes silently get clipped server-side. This function caps the body
    and leaves a visible breadcrumb so the model knows it was truncated.

    Args:
        text: Raw ticket text (may contain Windows ``\\r\\n`` or old-Mac
            ``\\r`` line endings from CSV exports).
        max_chars: Maximum characters allowed in the returned string.

    Returns:
        Either the original text (if under budget) or a truncated version
        ending with ``"\\n...[TRUNCATED FOR LLM INPUT]"``.

    Teaching:
        ``str.replace("\\r\\n", "\\n").replace("\\r", "\\n")`` is the standard
        normalize-newlines trick: handle the two-char Windows form first so
        you don't double-convert. The ``- 80`` margin reserves room for the
        truncation marker so the *final* string still fits in ``max_chars``.
        ``rstrip()`` cleans trailing whitespace at the cut point, which can
        otherwise produce ugly mid-word breaks like ``"... and the    "``.
    """
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text if len(text) <= max_chars else text[: max_chars - 80].rstrip() + "\n...[TRUNCATED FOR LLM INPUT]"


def load_candidates(run_dir: Path, limit: int, min_context_score: float, strategy: str, max_chars: int) -> pd.DataFrame:
    """Pick rich-evidence tickets for LLM extraction.

    Filters to tickets with ``context_depth_score >= min_context_score`` and
    ``len(question_flat) >= 40`` to ensure the model has substance to work with.
    Joins outlier subtopic and BERTopic labels into ``issue_label`` if available.

    Args:
        run_dir: Existing run directory containing ``enriched_tickets.csv``.
        limit: Maximum number of candidates to return.
        min_context_score: Minimum ``context_depth_score`` to qualify.
        strategy: One of ``highest_context``, ``risk_balanced``, ``issue_balanced``.
        max_chars: Truncation limit for ``llm_input_text`` (the prompt body).

    Returns:
        DataFrame with one row per candidate, including ``llm_input_text``
        which is the compacted ticket prepared for the prompt.

    Teaching:
        Three sampling strategies, each appropriate for a different question:

        * ``highest_context`` is the most defensible default: take the tickets
          that already scored highest on contextual richness. Right when you
          want maximum signal-per-LLM-call (research, qualitative review).
        * ``risk_balanced`` upweights tickets that mention money, status,
          ban-reasons, or user claims, plus unresolved cases. Right when the
          dashboard's job is to find escalation-worthy operational risk —
          which is the default for the BIGO/IMO ticket dataset (6,728 rows).
        * ``issue_balanced`` round-robins across ``issue_label`` so each
          semantic issue gets at least one example. Right for *coverage* (you
          don't want all 250 tickets to be the same scam complaint).

        Note the use of ``df.get(col, default)`` for optional columns: this
        is forgiving — earlier pipeline stages may or may not have produced
        ``outlier_subtopic_label`` / ``bertopic_label``, and we don't want a
        ``KeyError`` to abort the run.

        ``df["x"].astype(str).str.lower().isin(["true", "1"])`` is the canonical
        "this column was loaded from CSV and might be a real bool, the literal
        string ``'True'``, or ``'1'``" defense. Cast everything to lowercase
        string and check membership.

        ``groupby("issue_label", dropna=False).head(k)`` is the round-robin
        primitive: group, then take the top ``k`` per group. We size ``k`` as
        ``limit // unique_groups`` so the totals roughly add up to ``limit``.
    """
    df = pd.read_csv(run_dir / "enriched_tickets.csv")
    df["source_row"] = df["source_row"].astype(str)
    df["question_flat"] = df["question_flat"].fillna("").astype(str)
    df["question"] = df["question"].fillna(df["question_flat"]).astype(str)
    for col in ["manager", "date_raw", "category", "question_kind", "status_en", "primary_desire"]:
        df[col] = df[col].fillna("").astype(str)

    issue_label = None
    if (run_dir / "refined_opportunity_backlog.csv").exists() and (run_dir / "outlier_subtopic_assignments.csv").exists():
        out = pd.read_csv(run_dir / "outlier_subtopic_assignments.csv", usecols=["source_row", "outlier_subtopic_label"])
        out["source_row"] = out["source_row"].astype(str)
        df = df.merge(out, on="source_row", how="left")
        issue_label = df.get("outlier_subtopic_label")
    if (run_dir / "bertopic_assignments.csv").exists():
        bert = pd.read_csv(run_dir / "bertopic_assignments.csv", usecols=["source_row", "Name"])
        bert["source_row"] = bert["source_row"].astype(str)
        df = df.merge(bert.rename(columns={"Name": "bertopic_label"}), on="source_row", how="left")
    df["issue_label"] = df.get("outlier_subtopic_label", pd.Series(index=df.index, dtype=str)).fillna(df.get("bertopic_label", pd.Series(index=df.index, dtype=str))).fillna("")

    rich = df[df["context_depth_score"].ge(min_context_score) & df["question_flat"].str.len().ge(40)].copy()
    if strategy == "highest_context":
        selected = rich.sort_values(["context_depth_score", "char_count"], ascending=False).head(limit)
    elif strategy == "risk_balanced":
        risk_cols = ["has_money_terms", "has_status_or_svip_terms", "has_ban_reason_language", "has_user_claim"]
        for col in risk_cols:
            if col not in rich.columns:
                rich[col] = False
            rich[col] = rich[col].astype(str).str.lower().isin(["true", "1"])
        rich["risk_score"] = rich[risk_cols].sum(axis=1) + rich["is_unresolved"].astype(str).str.lower().isin(["true", "1"]).astype(int)
        selected = rich.sort_values(["risk_score", "context_depth_score"], ascending=False).head(limit)
    else:
        # Balanced by semantic issue: take top context examples per issue first.
        selected = (
            rich.sort_values("context_depth_score", ascending=False)
            .groupby("issue_label", dropna=False)
            .head(max(1, limit // max(rich["issue_label"].nunique(), 1)))
            .head(limit)
        )
        if len(selected) < limit:
            remaining = rich.loc[~rich.index.isin(selected.index)].sort_values("context_depth_score", ascending=False).head(limit - len(selected))
            selected = pd.concat([selected, remaining], ignore_index=False)
    selected = selected.copy()
    selected["llm_input_text"] = selected["question"].map(lambda x: compact(x, max_chars))
    columns = [
        "source_row",
        "date_raw",
        "manager",
        "uid",
        "category",
        "question_kind",
        "status_en",
        "primary_desire",
        "issue_label",
        "context_depth_score",
        "context_depth_band",
        "char_count",
        "url_count",
        "image_url_count",
        "timestamp_count",
        "room_or_group_id_count",
        "llm_input_text",
    ]
    return selected[[c for c in columns if c in selected.columns]].reset_index(drop=True)


def candidate_prompt(row: pd.Series) -> str:
    """Render the per-ticket user prompt by substituting metadata into the template.

    The template :data:`USER_TEMPLATE` is a multi-line f-string-shaped block
    using ``{name}`` placeholders. We don't use ``f""`` here because the
    template is defined at module level (before ``row`` exists) — instead we
    pass it through ``str.format(**kwargs)`` once per call. Passing metadata
    (manager, category, primary_desire) tells the LLM what the upstream
    pipeline already knows, so it doesn't waste capacity re-deriving it from
    raw text.

    Args:
        row: A pandas Series for a single candidate ticket. Required keys are
            ``source_row``, ``manager``, ``date_raw``, ``category``,
            ``question_kind``, ``status_en``, ``primary_desire``,
            ``issue_label``, ``context_depth_score``, ``llm_input_text``.

    Returns:
        The fully rendered user prompt string.

    Teaching:
        ``row.get(key, default)`` mirrors ``dict.get``. It avoids ``KeyError``
        if a column is missing — important here because we sometimes feed
        rows that came from older runs missing some optional fields. The
        empty-string default is safe because ``str.format`` is happy to
        substitute ``""`` and Python's f-string-style formatting won't
        complain about missing keys when you've supplied them all explicitly.
    """
    return USER_TEMPLATE.format(
        source_row=row.get("source_row", ""),
        manager=row.get("manager", ""),
        date_raw=row.get("date_raw", ""),
        category=row.get("category", ""),
        question_kind=row.get("question_kind", ""),
        status_en=row.get("status_en", ""),
        primary_desire=row.get("primary_desire", ""),
        issue_label=row.get("issue_label", ""),
        context_depth_score=row.get("context_depth_score", ""),
        text=row.get("llm_input_text", ""),
    )


def parse_json_object(text: str) -> dict[str, Any]:
    """Defensively extract a JSON object from possibly-noisy LLM output.

    Even when prompted "return JSON only", small models add markdown code
    fences (\\`\\`\\`json ... \\`\\`\\`), apologies ("Here is the JSON:"), or
    trailing commentary. Calling ``json.loads`` on the raw response will
    almost always raise. This function strips the most common decorations
    before parsing.

    Args:
        text: The model's raw output string.

    Returns:
        Parsed JSON dict.

    Raises:
        json.JSONDecodeError: If the cleaned text is still invalid JSON.

    Teaching:
        Two defensive layers:

        1. **Markdown fence stripping** — ``re.sub`` with the ``re.S`` (DOTALL)
           flag so ``.`` matches newlines. The pattern uses alternation
           (``A|B``) to strip either the opening fence (``\\`\\`\\`json``)
           or the closing one (\\`\\`\\`).
        2. **Outermost-brace extraction** — ``find('{')`` returns the index
           of the first ``{``, ``rfind('}')`` returns the index of the last
           ``}``. Slicing between them grabs the largest substring that
           *could* be a JSON object, even if the model rambled before or
           after it.

        ``json.loads`` is strict: it expects the entire string to be one JSON
        value. That's why we slice down before calling it. This is the
        "best-effort parse" pattern: try increasingly aggressive cleanup
        rather than failing on the first malformed character.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def call_openai(row: pd.Series, model: str) -> dict[str, Any]:
    """Send one ticket to OpenAI's Chat Completions API and return parsed JSON.

    This is the "premium" backend: it produces the best output but costs
    money and sends the ticket text outside the machine. For 6,728 tickets
    at GPT-4-class pricing it would have been prohibitive, which is why the
    project defaults to the local ``ollama`` and ``ollama_hybrid`` backends.

    Args:
        row: pandas Series for one candidate ticket.
        model: OpenAI model name (e.g. ``"gpt-4o-mini"``).

    Returns:
        Parsed JSON dict with ``source_row`` patched in if missing.

    Teaching:
        Three OpenAI-specific tricks worth memorizing:

        * ``from openai import OpenAI`` is **inside** the function. This is
          a deferred import: the OpenAI library is optional, so importing it
          at module level would break users who only run the rules backend.
          Lazy imports trade a microsecond at call time for a much friendlier
          dependency story.
        * ``response_format={"type": "json_object"}`` tells the API to refuse
          to emit non-JSON. The model is constrained at decode time, so the
          response is *guaranteed* parseable. (You still need to validate the
          schema yourself — ``json_object`` mode doesn't enforce field names.)
        * ``temperature=0`` makes generation greedy/deterministic. The same
          input produces the same output. Crucial for reproducible analysis
          pipelines: without this, rerunning the script would give different
          extractions and your CSVs would churn.

        ``setdefault`` only inserts the key if it's missing, which means we
        don't overwrite the model's own correct ``source_row`` (and, if it
        forgot, we patch in the truth from our metadata).
    """
    from openai import OpenAI

    client = OpenAI()
    schema_text = json.dumps(SCHEMA, ensure_ascii=False, indent=2)
    user_prompt = candidate_prompt(row) + "\n\nReturn JSON with this schema:\n" + schema_text
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    result = parse_json_object(content)
    result.setdefault("source_row", str(row.get("source_row", "")))
    return result


def local_json_template(row: pd.Series) -> dict[str, Any]:
    """Build a fully-populated JSON skeleton for the local model to overwrite.

    Local models like ``gemma3:4b`` are smaller and weaker than GPT-class
    models. They struggle with "produce JSON matching this schema" but
    succeed reliably at "fill in the blanks of *this exact* JSON object".
    So we hand them a complete object with safe defaults already in place
    and ask them to overwrite fields. If the model fails to fill some field,
    the safe default ("unknown", 3, [], False) survives.

    Args:
        row: pandas Series for one ticket. Only ``source_row`` is read.

    Returns:
        A dict with every schema key present, populated with neutral defaults
        (``""`` for strings, ``"unknown"``/``"other"`` for enums, mid-scale 3
        for risk levels, empty lists for entity collections, ``True`` for
        ``needs_human_review``, and ``0.5`` for ``confidence``).

    Teaching:
        Notice the defaults are *deliberately conservative*:

        * ``needs_human_review = True`` means "if the model fails, route this
          to a human" — the safe default is to escalate, not to auto-resolve.
        * ``confidence = 0.5`` means "I have no information" — neither
          confident nor confidently-wrong.
        * Risk levels default to 3 (the middle), not 1 (no risk) or 5 (max
          risk), so a missing extraction doesn't bias the dashboard either way.

        This pattern is called "pre-filled scaffolding" or "JSON in-fill" and
        is one of the highest-leverage tricks for working with small local
        models.
    """
    return {
        "source_row": str(row.get("source_row", "")),
        "literal_request": "",
        "actual_user_want": "",
        "job_to_be_done": "other",
        "user_emotion": "unknown",
        "urgency_level": 3,
        "trust_risk_level": 3,
        "money_risk_level": 1,
        "safety_policy_risk_level": 1,
        "evidence_present": [],
        "evidence_missing": [],
        "entities": {
            "uids": [],
            "room_or_group_ids": [],
            "timestamps": [],
            "ban_reasons": [],
            "money_or_diamond_amounts": [],
            "counterparties": [],
            "url_count": 0,
        },
        "support_next_step": "",
        "product_opportunity": "",
        "manager_note_quality": "adequate",
        "needs_human_review": True,
        "confidence": 0.5,
    }


def hybrid_json_template() -> dict[str, Any]:
    """Smaller skeleton: only the narrative fields the hybrid model fills in.

    In hybrid mode the rules layer has already produced job_to_be_done, risk
    levels, evidence lists, and entities — those are deterministic and we
    don't want the model to second-guess them. The model is only asked for
    the *human-feeling* fields: literal_request, actual_user_want, emotion,
    next_step, product_opportunity, plus quality/confidence self-assessment.

    Returns:
        A dict with eight keys, all set to neutral defaults.

    Teaching:
        Compare against :func:`local_json_template`: the full template has
        ~17 fields, this one has 8. Smaller surface area = fewer ways for a
        small model to mess up. This is the "minimum viable prompt" principle:
        ask the model only for what only the model can produce, and let
        deterministic code handle the rest.
    """
    return {
        "literal_request": "",
        "actual_user_want": "",
        "user_emotion": "unknown",
        "support_next_step": "",
        "product_opportunity": "",
        "manager_note_quality": "adequate",
        "needs_human_review": True,
        "confidence": 0.5,
    }


def ollama_chat_json(
    model: str,
    ollama_url: str,
    timeout: int,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST a chat request to a local Ollama server and return parsed JSON.

    Ollama is a local LLM runtime that exposes an HTTP API on
    ``localhost:11434``. We don't import the ``ollama`` Python package because
    we want zero extra dependencies — the standard library's ``urllib`` is
    enough.

    Args:
        model: Ollama model tag (e.g. ``"gemma3:4b"``, ``"llama3.1:8b"``).
        ollama_url: Base URL, typically ``"http://localhost:11434"``.
        timeout: HTTP timeout in seconds. Local generation can be slow on
            CPU; 180s is a reasonable default for ``gemma3:4b`` on Apple
            Silicon.
        system_prompt: The system message (role/persona instructions).
        user_prompt: The user message (per-ticket payload).
        response_schema: Optional JSON Schema object for Ollama structured
            outputs. When omitted, falls back to plain JSON mode.

    Returns:
        Parsed JSON dict from the model's response.

    Raises:
        RuntimeError: If the HTTP request fails (Ollama not running, wrong
            URL, timeout). The original exception is chained via
            ``raise ... from exc`` so the traceback shows both layers.

    Teaching:
        Three standard-library HTTP idioms in 12 lines:

        * ``json.dumps(payload).encode("utf-8")`` — convert dict to JSON
          string, then to bytes. ``urllib`` requires bytes, not str.
        * ``urllib.request.Request(url, data=..., headers=..., method="POST")``
          — explicit verb construction. Without ``method="POST"``, urllib
          defaults to GET when ``data`` is None, or POST when data is given,
          but being explicit avoids surprises.
        * ``with urllib.request.urlopen(...) as response:`` — context manager
          ensures the socket is closed even if parsing throws.

        Ollama-specific options:

        * ``"stream": False`` — get the whole response at once instead of
          line-delimited streaming chunks.
        * ``"format": <JSON Schema>`` — Ollama structured-output mode. This
          constrains both valid JSON and the shape/enums of the extraction.
          We fall back to ``"json"`` only when no schema is supplied.
        * ``"num_ctx": 8192`` — context window size in tokens. Default is
          2048 in older Ollama builds; 8192 matters for the longer BIGO
          tickets (some are 6,500 chars after compaction ≈ 2k+ tokens).

        ``raise RuntimeError(...) from exc`` is exception chaining: the new
        error keeps a reference to the cause, so tracebacks show both the
        urllib URLError *and* the friendly RuntimeError. Critical for
        debuggability.
    """
    payload = {
        "model": model,
        "stream": False,
        "format": response_schema or "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ollama_url.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed. Is Ollama running at {ollama_url}? {exc}") from exc
    content = (body.get("message") or {}).get("content") or "{}"
    return parse_json_object(content)


def call_ollama(row: pd.Series, model: str, ollama_url: str, timeout: int) -> dict[str, Any]:
    """Send the candidate to a local Ollama server and return parsed JSON.

    Uses the defensive prompt :data:`OLLAMA_SYSTEM_PROMPT` plus the per-ticket
    user prompt with the full local JSON template embedded. Includes explicit
    enum-list reminders and forbids template-echoing for narrative fields.

    Ollama is contacted via ``POST /api/chat`` with ``format=json``,
    ``temperature=0``, ``num_ctx=8192``.

    Args:
        row: A pd.Series with ticket metadata + ``llm_input_text``.
        model: Ollama model tag, e.g. ``gemma3:4b``.
        ollama_url: Base URL, default ``http://localhost:11434``.
        timeout: HTTP timeout in seconds.

    Returns:
        Parsed JSON dict. ``source_row`` is forced to match the input.

    Raises:
        RuntimeError: If Ollama is unreachable.

    Teaching:
        The user prompt is built by concatenation rather than ``str.format``
        because we want to inject *runtime values* — the enum lists are
        joined here so the model sees the live values from :data:`JOB_VALUES`,
        :data:`EMOTION_VALUES`, etc. If you ever expand the enum, the prompt
        updates automatically.

        Why so many "do not" sentences? Small models have a strong tendency
        to:

        * Repeat the JSON template back unchanged (template echo).
        * Output the enum lists verbatim ("one of: recover_access, ...").
        * Use snake_case tokens like ``infer_goal`` instead of plain English
          for free-text fields.

        Each "do not" line is a scar from observed failure. This is the
        "defensive prompting" pattern: the prompt grows by one rule every
        time you see the model do something stupid in production.
    """
    template_text = json.dumps(local_json_template(row), ensure_ascii=False, indent=2)
    user_prompt = (
        candidate_prompt(row)
        + "\n\nFill the JSON template below with inferred values from the ticket."
        + "\nDo not repeat the template placeholders. Do not output the enum lists."
        + "\nliteral_request: summarize what the user explicitly asks, in plain English."
        + "\nactual_user_want: infer the outcome the user needs, in plain English."
        + "\nsupport_next_step: write a concrete support action, starting with a verb."
        + "\nproduct_opportunity: write a concrete product/system improvement; avoid just 'unknown'."
        + "\nDo not use vague phrases like 'infer_goal', 'resolve issue', 'analyze', or just an enum token."
        + "\nUse exactly one job_to_be_done token from: "
        + ", ".join(JOB_VALUES)
        + "\nUse exactly one user_emotion token from: "
        + ", ".join(EMOTION_VALUES)
        + "\nUse evidence_present values only from: "
        + ", ".join(EVIDENCE_VALUES)
        + "\nUse manager_note_quality from: "
        + ", ".join(NOTE_QUALITY_VALUES)
        + "\nInteger risk levels must be 1 to 5. confidence must be 0.0 to 1.0."
        + "\nReturn JSON only:\n"
        + template_text
    )
    result = ollama_chat_json(
        model,
        ollama_url,
        timeout,
        OLLAMA_SYSTEM_PROMPT,
        user_prompt,
        response_schema=extraction_response_schema(),
    )
    result.setdefault("source_row", str(row.get("source_row", "")))
    return result


def is_concrete_phrase(value: Any, field: str | None = None) -> bool:
    """Return True if a free-text field looks like real human content.

    The hybrid backend asks the model to write narrative fields, but small
    local models often fall back to placeholder phrases ("unknown", "n/a",
    "investigate", a snake_case token like ``fix_issue``). We don't want
    those substitutions to overwrite the rules-layer skeleton, so this
    function gates the merge: only "concrete-looking" values are accepted.

    Args:
        value: The model's proposed value (any type; coerced to string).
        field: Optional field name for stricter per-field rules. Currently
            ``"support_next_step"`` requires ≥24 chars and
            ``"product_opportunity"`` requires ≥36 chars *and* one of a
            list of product-flavored terms.

    Returns:
        ``True`` if the value passes all checks; ``False`` otherwise.

    Teaching:
        Five layered checks, in increasing specificity:

        1. **Length floor** (≥8 chars). Anything shorter is almost certainly
           ``"unknown"``, ``"n/a"``, or empty.
        2. **No underscores / not a snake_case token**. The model is supposed
           to write English; a ``snake_case_thing`` is an enum-token leak.
           ``re.fullmatch`` requires the whole string to match the pattern,
           so a sentence containing one underscore is OK only if it's not
           *purely* snake_case.
        3. **Not in the GENERIC_PHRASES blacklist**. The blacklist captures
           model-output ruts observed in practice ("investigate", "ban
           audit", "improve user experience").
        4. **Per-field length** for support_next_step (operational actions
           need to be *specific*, e.g. "Check ban history and timestamps").
        5. **Per-field semantic terms** for product_opportunity (must mention
           a real product surface like ``system``, ``dashboard``, ``form``).

        ``str(value or "")`` handles ``None`` cleanly: ``None or ""`` is
        ``""``. Without this guard, ``str(None)`` would give ``"None"`` and
        pass the length check.

        ``re.sub(r"\\s+", " ", ...)`` collapses any whitespace run (spaces,
        tabs, newlines) into one space — important for matching the
        blacklist regardless of how the model formatted its output.
    """
    text = str(value or "").strip()
    if len(text) < 8:
        return False
    normalized = re.sub(r"\s+", " ", text.replace("_", " ")).strip().lower()
    if "_" in text or SNAKE_TOKEN_RE.fullmatch(text):
        return False
    if normalized in GENERIC_PHRASES:
        return False
    if field == "support_next_step" and len(text) < 24:
        return False
    if field == "product_opportunity":
        if len(text) < 36:
            return False
        product_terms = (
            "system",
            "workflow",
            "flow",
            "dashboard",
            "form",
            "tool",
            "receipt",
            "evidence",
            "appeal",
            "status",
            "timeline",
            "validation",
            "dispute",
            "self-service",
            "automation",
        )
        if not any(term in normalized for term in product_terms):
            return False
    return True


def narrative_quality_flag(update: dict[str, Any]) -> str | None:
    """Inspect the hybrid model's narrative fields and return a failure tag.

    Used by :func:`call_ollama_hybrid` to record *why* a model output was
    considered weak. The result still gets merged into the final dict (with
    rules-layer fallbacks where the model failed), but the flag is preserved
    in ``_hybrid_model_quality_flag`` for downstream auditing.

    Args:
        update: The model's narrative dict (the small hybrid template).

    Returns:
        ``"empty_narrative_fields"`` — any required field is blank.
        ``"too_vague_narrative"`` — ≥2 of the four required fields fail
        :func:`is_concrete_phrase`.
        ``"invalid_emotion"`` — emotion not in :data:`EMOTION_VALUES`.
        ``"invalid_note_quality"`` — manager_note_quality not in the enum.
        ``None`` — output is good.

    Teaching:
        Field-by-field checks ordered cheapest-first: empty-check is one
        ``str.strip``, vagueness check calls ``is_concrete_phrase`` per
        field. ``sum(boolean_expression for x in seq) >= 2`` is the
        Pythonic "count how many failed" pattern — booleans subclass int,
        so ``True`` adds 1 and ``False`` adds 0.

        ``str(update.get(...)).strip()`` is repeated everywhere because
        model output may be ``None``, an int, or a whitespace-padded string.
        Defensive coercion is cheaper than a try/except on every access.
    """
    required = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
    if any(not str(update.get(field, "")).strip() for field in required):
        return "empty_narrative_fields"
    if sum(not is_concrete_phrase(update.get(field), field) for field in required) >= 2:
        return "too_vague_narrative"
    if str(update.get("user_emotion", "unknown")).strip() not in EMOTION_VALUES:
        return "invalid_emotion"
    if str(update.get("manager_note_quality", "adequate")).strip() not in NOTE_QUALITY_VALUES:
        return "invalid_note_quality"
    return None


def bounded_confidence(value: Any, fallback: float) -> float:
    """Coerce a model-supplied confidence to a float in ``[0.0, 1.0]``.

    Models sometimes emit ``"high"``, ``"0.8 (low)"``, ``None``, or a number
    outside the unit interval. This function clamps the value to a safe
    range and falls back to a known-good default on any parse failure.

    Args:
        value: The model's confidence (any type).
        fallback: The value to return if ``value`` can't be coerced.

    Returns:
        A float in ``[0.0, 1.0]``, or ``fallback``.

    Teaching:
        ``max(0.0, min(1.0, x))`` is the **clamp idiom**. Read it inside-out:
        ``min(1.0, x)`` caps at 1.0, then ``max(0.0, ...)`` floors at 0.0.
        Equivalent to ``np.clip(x, 0, 1)`` but doesn't need numpy.

        The double ``float()`` is intentional: the inner one parses the
        input (raises ``ValueError`` on garbage like ``"high"``); the outer
        one just confirms the type after clamping.

        Catching both ``TypeError`` (for ``None`` or other un-floatable
        types) and ``ValueError`` (for un-parseable strings) is the canonical
        "this should be a number" defense.
    """
    try:
        return float(max(0.0, min(1.0, float(value))))
    except (TypeError, ValueError):
        return fallback


def call_ollama_hybrid(row: pd.Series, model: str, ollama_url: str, timeout: int) -> dict[str, Any]:
    """Run rules first, then ask the local model only for narrative fields.

    This is the central design of the project. The intuition: small local
    models like ``gemma3:4b`` are unreliable at structured classification
    (they pick wrong job_to_be_done values, hallucinate UIDs, or output
    impossible risk scores) but they *are* good at writing one English
    sentence describing what a user wants. So we let the rules layer handle
    structured classification deterministically, then ask the model only for
    interpretation. The result is a dataset that has the rigor of rules with
    the readability of LLM output.

    Pipeline:

    1. Run :func:`call_rules` to get a deterministic skeleton.
    2. Build a snapshot of the rules' classification (job, risk levels,
       evidence, entities) and put it *inside* the user prompt with the
       instruction "you must respect this".
    3. Ask the model to fill only the small :func:`hybrid_json_template`.
    4. If the model errored, return the rules result with an error tag.
    5. If the model succeeded, validate each field with
       :func:`is_concrete_phrase` / enum membership. **Only merge values
       that pass validation.** Bad model output is dropped, not propagated.
    6. Confidence is the *max* of the rules' baseline (0.55) and the
       model's self-reported confidence (clamped to ``[0,1]``). We never
       go below the rules' floor.

    Args:
        row: pandas Series for one ticket.
        model: Ollama model tag.
        ollama_url: Ollama base URL.
        timeout: HTTP timeout seconds.

    Returns:
        Merged dict with rules-layer structure, model-supplied narrative
        (where it passed validation), plus diagnostic fields:
        ``_hybrid_model_status`` (``ok`` / ``bad_output`` / ``error``),
        ``_hybrid_model_quality_flag``, ``_hybrid_model_error``,
        ``_hybrid_rules_job``.

    Teaching:
        Why is this robust to weak models?

        * If the model crashes → we fall back to rules (line: ``except
          Exception``). The ticket still gets a useful extraction.
        * If the model hallucinates → ``is_concrete_phrase`` rejects the
          hallucination and we keep the rules-layer phrase.
        * If the model picks an invalid emotion → the membership check in
          :data:`EMOTION_VALUES` filters it out.
        * If the model says ``confidence=0.95`` but rules already said
          ``0.55``, we use ``max`` — the model can *raise* confidence (it
          read the text and saw something coherent) but we don't drop below
          the rules floor.

        ``json.loads(json.dumps(rules_result))`` is the cheapskate's
        ``copy.deepcopy``: serialize then deserialize. It only works on
        JSON-able values, but it's faster than ``copy.deepcopy`` for small
        dicts and avoids the import.

        The pattern of writing a "snapshot" of upstream work into a prompt
        is sometimes called *prompt grounding*: by showing the model what
        a deterministic system already concluded, you constrain its
        creativity to the part you actually want creative.
    """
    rules_result = call_rules(row)
    rules_snapshot = {
        "job_to_be_done": rules_result["job_to_be_done"],
        "urgency_level": rules_result["urgency_level"],
        "trust_risk_level": rules_result["trust_risk_level"],
        "money_risk_level": rules_result["money_risk_level"],
        "safety_policy_risk_level": rules_result["safety_policy_risk_level"],
        "evidence_present": rules_result["evidence_present"],
        "evidence_missing": rules_result["evidence_missing"],
        "entities": rules_result["entities"],
    }
    template_text = json.dumps(hybrid_json_template(), ensure_ascii=False, indent=2)
    user_prompt = (
        candidate_prompt(row)
        + "\n\nRules layer output that you must respect:\n"
        + json.dumps(rules_snapshot, ensure_ascii=False, indent=2)
        + "\n\nWrite only the interpretation JSON below."
        + "\nDo not include job_to_be_done, risk levels, evidence lists, or entities."
        + "\nliteral_request: what the user explicitly asks, using ticket details."
        + "\nactual_user_want: the deeper outcome the user needs, not a category label."
        + "\nsupport_next_step: concrete operational action, starting with a verb."
        + "\nproduct_opportunity: concrete product/system improvement so this ticket becomes unnecessary."
        + "\nUse normal plain English. Do not use snake_case, enum-like labels, or generic phrases."
        + "\nUse exactly one user_emotion token from: "
        + ", ".join(EMOTION_VALUES)
        + "\nUse manager_note_quality from: "
        + ", ".join(NOTE_QUALITY_VALUES)
        + "\nReturn JSON only:\n"
        + template_text
    )
    result = json.loads(json.dumps(rules_result))
    try:
        update = ollama_chat_json(
            model,
            ollama_url,
            timeout,
            HYBRID_OLLAMA_SYSTEM_PROMPT,
            user_prompt,
            response_schema=hybrid_response_schema(),
        )
    except Exception as exc:
        result["_hybrid_model_status"] = "error"
        result["_hybrid_model_error"] = str(exc)
        result["_hybrid_rules_job"] = rules_result["job_to_be_done"]
        return result

    quality_flag = narrative_quality_flag(update)
    result["_hybrid_model_status"] = "bad_output" if quality_flag else "ok"
    if quality_flag:
        result["_hybrid_model_quality_flag"] = quality_flag
    result["_hybrid_rules_job"] = rules_result["job_to_be_done"]

    for field in ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]:
        if is_concrete_phrase(update.get(field), field):
            result[field] = str(update[field]).strip()
    if str(update.get("user_emotion", "")).strip() in EMOTION_VALUES:
        result["user_emotion"] = str(update["user_emotion"]).strip()
    if str(update.get("manager_note_quality", "")).strip() in NOTE_QUALITY_VALUES:
        result["manager_note_quality"] = str(update["manager_note_quality"]).strip()
    if isinstance(update.get("needs_human_review"), bool):
        result["needs_human_review"] = bool(update["needs_human_review"]) or bool(result["needs_human_review"])
    result["confidence"] = round(max(float(result["confidence"]), bounded_confidence(update.get("confidence"), float(result["confidence"]))), 2)
    return result


def output_quality_flag(result: dict[str, Any], expected_source_row: str) -> str | None:
    """Validate an LLM output against schema rules and return a failure flag.

    Returns one of the following strings (or ``None`` if the output passes):

    * ``source_row_schema_echo`` — model returned literal ``"string"`` or empty
    * ``source_row_mismatch`` — model returned a different source_row
    * ``empty_required_fields`` — any of literal_request / actual_user_want /
      support_next_step / product_opportunity is blank
    * ``schema_echo`` — output text contains schema descriptors like
      ``"one of:"``, ``"short string"``
    * ``invalid_job`` — job_to_be_done not in :data:`JOB_VALUES`
    * ``invalid_emotion`` — user_emotion not in :data:`EMOTION_VALUES`
    * ``too_vague`` — ≥2 narrative fields contain only generic phrases

    Args:
        result: The parsed JSON dict from the LLM call.
        expected_source_row: The source_row we sent in the prompt.

    Returns:
        A flag string if validation failed, else ``None``.

    Teaching:
        Each flag is a *named failure mode* observed in production. Naming
        them lets us count them in the executive report ("12 outputs were
        ``schema_echo``, 4 were ``invalid_job``") and track them over time
        as we tune prompts and models.

        * ``source_row_schema_echo`` — model literally returned the descriptor
          string ``"string"`` (it copied the schema instead of filling it).
        * ``source_row_mismatch`` — model swapped in a *different* row's id,
          usually because it confused itself across our few-shot examples.
        * ``schema_echo`` — narrative fields contain text from the schema
          like ``"short string"`` or ``"one of:"`` (template echo).
        * ``invalid_job`` / ``invalid_emotion`` — model invented an enum
          value (``"investigate_fraud"`` instead of ``"avoid_scam"``). Note
          that :func:`normalize_result_enums` runs *after* this and rewrites
          some known aliases — this check sees only un-aliasable invalid
          values.
        * ``too_vague`` — at least two of the four narrative fields are
          generic placeholders.

        Returning ``None`` for "passed" is a Python idiom: the caller writes
        ``if flag := output_quality_flag(...):`` (Python 3.8+ walrus) or
        ``if flag is not None:`` to detect failure.
    """
    if str(result.get("source_row", "")).strip() in {"", "string"}:
        return "source_row_schema_echo"
    if str(result.get("source_row", "")).strip() != expected_source_row:
        return "source_row_mismatch"
    required_text_fields = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
    if any(not str(result.get(field, "")).strip() for field in required_text_fields):
        return "empty_required_fields"
    echoed_needles = [
        "one of:",
        "short string",
        "what the user explicitly asked for",
        "deeper user want",
        "specific next operational action",
        "what product/system should exist",
        "number 0-1",
    ]
    fields = [
        result.get("literal_request"),
        result.get("actual_user_want"),
        result.get("job_to_be_done"),
        result.get("user_emotion"),
        result.get("support_next_step"),
        result.get("product_opportunity"),
        result.get("confidence"),
    ]
    text = " ".join(str(v).lower() for v in fields if v is not None)
    if any(needle in text for needle in echoed_needles):
        return "schema_echo"
    if str(result.get("job_to_be_done", "")).strip() not in JOB_VALUES:
        return "invalid_job"
    if str(result.get("user_emotion", "")).strip() not in EMOTION_VALUES:
        return "invalid_emotion"
    vague_values = {"unknown", "infer_goal", "resolve issue", "analyze", "investigate", "n/a", "none"}
    concrete_fields = ["literal_request", "actual_user_want", "support_next_step", "product_opportunity"]
    vague_count = sum(str(result.get(field, "")).strip().lower() in vague_values for field in concrete_fields)
    if vague_count >= 2:
        return "too_vague"
    return None


def normalize_result_enums(result: dict[str, Any]) -> dict[str, Any]:
    """Rewrite known model-output aliases to canonical enum values.

    Different models settle on different vocabularies. ``gemma3`` likes
    ``investigate_fraud``; we want ``avoid_scam`` (matches our schema).
    Rather than tightening the prompt forever, we accept these aliases and
    rewrite them post-hoc. The original token is stored in
    ``_normalized_*_from`` so the audit trail survives.

    Args:
        result: The parsed (and possibly noisy) extraction dict.

    Returns:
        The same dict, mutated in place. ``job_to_be_done`` and
        ``user_emotion`` may be rewritten; ``_normalized_job_from`` /
        ``_normalized_emotion_from`` keys may be added.

    Teaching:
        :data:`JOB_ALIASES` is a one-way map: many model words → one
        canonical word. If we ever want to count "how often did the model
        pick a non-canonical token", filter the dataframe on
        ``_normalized_job_from.notna()``.

        Why mutate in place rather than copy? It's cheaper and we own the
        result dict at this point in the pipeline. The convention "function
        also returns the mutated arg" is common in pandas (``df.fillna``
        returns df, but ``df.fillna(inplace=True)`` mutates).
    """
    job = str(result.get("job_to_be_done", "")).strip()
    if job in JOB_ALIASES:
        result["job_to_be_done"] = JOB_ALIASES[job]
        result["_normalized_job_from"] = job
    emotion = str(result.get("user_emotion", "")).strip()
    if emotion == "stressed":
        result["user_emotion"] = "anxious"
        result["_normalized_emotion_from"] = emotion
    return result


def bounded_level(score: float) -> int:
    """Clamp a numeric risk score into the ``[1, 5]`` integer range.

    The schema requires every risk level to be ``1..5``. The rule formulas
    in :func:`call_rules` produce raw scores that can fall outside that
    range — e.g. urgency = ``1 + 5 + 1 + 1 = 8`` when a ticket has many
    urgent words plus claim plus scam. This clamps to the schema.

    Args:
        score: A float (could be ≥0, including non-integer like 2.5).

    Returns:
        Integer in ``[1, 5]``.

    Teaching:
        ``round(score)`` first maps the float to the nearest int; then the
        ``max(1, min(5, ...))`` clamp ensures it lands in the legal range.
        ``int(...)`` is technically redundant since ``round(int_or_float)``
        on Python 3 returns an int when called with a single argument, but
        explicit conversion makes the type guarantee obvious to readers.

        Banker's rounding alert: Python's ``round`` uses round-half-to-even,
        so ``round(2.5) == 2``, not 3. Usually fine here because the rule
        scores are small integers; rarely matters in practice.
    """
    return int(max(1, min(5, round(score))))


def call_rules(row: pd.Series) -> dict[str, Any]:
    """Deterministic regex-based extraction. No LLM, no API.

    Computes job_to_be_done via a priority cascade (game complaint without ban
    → fix_product_flow; abuse-protection desire or scam-report regex →
    avoid_scam; abuse report → protect_community; user-claim or ban-state →
    prove_innocence; otherwise rule-based primary desire mapping; finally
    falls through to ``other``).

    Risk levels are computed from feature counts (see
    :doc:`docs/engineering/09-formulas-cheatsheet`):

    * urgency = clip(1 + len(urgent_matches)/2 + claim + scam, 1, 5)
    * trust   = clip(1 + 2·has_ban + 2·has_scam + has_status, 1, 5)
    * money   = clip(1 + 3·has_money + has_scam, 1, 5)
    * safety  = clip(1 + 3·has_severe_terms, 1, 5)

    Narrative fields (``actual_user_want``, ``support_next_step``,
    ``product_opportunity``) come from a job-keyed dictionary of canonical
    phrases. This is intentionally rigid: the rules backend exists for
    sanity comparison, not nuanced output.

    Args:
        row: A pd.Series with ``llm_input_text``, ``primary_desire``,
            ``context_depth_score``.

    Returns:
        A complete extraction dict matching :data:`SCHEMA`.

    Teaching:
        Why have a rules baseline at all when you have an LLM?

        * **Reproducibility** — the rules backend produces byte-identical
          output every run. Useful as a regression baseline.
        * **Cost** — runs in ~1ms per ticket vs ~3s for Ollama. For 6,728
          tickets that's the difference between 7 seconds and 5 hours.
        * **Skeleton for the hybrid backend** — :func:`call_ollama_hybrid`
          calls this function first and uses its output as deterministic
          structure that the model is forbidden to override.
        * **Comparator** — when the LLM disagrees with rules, you have a
          named anomaly to investigate.

        The risk-level formulas use a "linear with hand-tuned weights"
        shape:

        * ``urgency = 1 + count(urgent_words)/2 + has_claim + has_scam``.
          Each urgent word adds 0.5; user-claim or scam each add a full 1.
          The baseline is 1 (no urgency at all).
        * ``trust_risk = 1 + 2·has_ban + 2·has_scam + has_status``. Bans
          and scams are weighted double because they're stronger trust
          signals than mere status mention.
        * ``money_risk = 1 + 3·has_money + has_scam``. Money keywords are
          weighted heavily — if it's about money, it matters.
        * ``safety_risk = 1 + 3·has_severe_terms``. Binary multiplier:
          severe content (porn, threats, abuse) gets max risk fast.

        These weights were tuned by eyeballing the resulting distribution
        on a sample. They're not learned — they're encoded judgment.

        The job-keyed dictionary at the bottom (``actual = {...}[job]``) is
        a *lookup table* used as a poor-man's pattern-match. Once you've
        decided the job, the canonical narrative is fixed. This is rigid
        on purpose: rules backend trades nuance for predictability.

        Note ``has_game_complaint = bool(GAME_RE.search(text)) and not has_ban``
        — game complaints get classified as ``fix_product_flow`` *unless*
        there's also a ban, in which case the ban dominates. This kind of
        priority ordering is why the cascade is a chain of ``elif``: order
        matters and the first match wins.
    """
    text = str(row.get("llm_input_text", ""))
    flat = re.sub(r"\s+", " ", text).strip()
    primary_desire = str(row.get("primary_desire", "")).strip().lower()
    urls = URL_RE.findall(text)
    images = IMAGE_RE.findall(text)
    timestamps = TIMESTAMP_RE.findall(text)
    uids = UID_RE.findall(text)
    rooms = ROOM_RE.findall(text)
    ban_reasons = sorted(set(m.group(0) for m in BAN_REASON_RE.finditer(text)))[:8]
    money_amounts = re.findall(r"(?:\d[\d\s,.]*\s?(?:₽|rubles?|diamonds?|crystals?|beans?)|(?:₽|rubles?)\s?\d[\d\s,.]*)", text, flags=re.I)[:8]
    has_money = bool(MONEY_RE.search(text))
    has_transaction = bool(TRANSACTION_RE.search(text))
    has_status = bool(STATUS_RE.search(text))
    has_claim = bool(CLAIM_RE.search(text))
    has_ban = bool(BAN_STATE_RE.search(text))
    has_room = bool(rooms or re.search(r"\b(?:channel|group|room|voice)\b", text, re.I))
    has_account = bool(re.search(r"\b(?:account|restore|recover|login|phone|sim|number|access)\b", text, re.I))
    has_scam = bool(re.search(r"\b(?:scam|fraud|deceived|tricked|cheated|impersonat|official dealer)\b", text, re.I))
    has_scam_report = bool(SCAM_REPORT_RE.search(text))
    has_game_complaint = bool(GAME_RE.search(text)) and not has_ban
    has_abuse_report = bool(ABUSE_REPORT_RE.search(text)) and not has_ban
    primary_job = {
        "clear_name_or_get_fairness": "prove_innocence",
        "recover_access": "recover_access",
        "earn_or_transact_money": "buy_or_sell_diamonds",
        "protect_from_abuse_or_scam": "avoid_scam",
        "grow_audience_or_community": "grow_channel",
        "gain_status_or_privileges": "gain_status",
        "understand_rules_or_system_logic": "understand_punishment",
        "fix_product_or_technical_flow": "fix_product_flow",
        "customize_identity_or_assets": "customize_identity",
    }.get(primary_desire)

    if has_game_complaint:
        job = "fix_product_flow"
    elif primary_desire == "protect_from_abuse_or_scam" or has_scam_report:
        job = "avoid_scam"
    elif has_abuse_report:
        job = "protect_community"
    elif has_claim or has_ban:
        job = "prove_innocence"
    elif primary_job:
        job = primary_job
    elif has_scam:
        job = "avoid_scam"
    elif has_transaction:
        job = "buy_or_sell_diamonds"
    elif has_room:
        job = "grow_channel"
    elif has_account:
        job = "recover_access"
    elif has_status:
        job = "gain_status"
    else:
        job = "other"

    if has_scam or "betray" in flat.lower():
        emotion = "betrayed"
    elif re.search(r"\b(?:urgent|asap|immediately|please help|why is no one)\b", flat, re.I):
        emotion = "urgent"
    elif has_claim or re.search(r"\b(?:why|don't understand|unfair)\b", flat, re.I):
        emotion = "confused"
    elif re.search(r"\b(?:angry|complain|wtf|fuck|insult)\b", flat, re.I):
        emotion = "angry"
    else:
        emotion = "unknown"

    evidence_present = []
    if images:
        evidence_present.append("screenshots")
    if urls:
        evidence_present.append("urls")
    if timestamps:
        evidence_present.append("timestamps")
    if uids:
        evidence_present.append("uid")
    if rooms:
        evidence_present.append("room_or_group_id")
    if ban_reasons:
        evidence_present.append("ban_reason")
    if money_amounts:
        evidence_present.append("money_amount")
    if has_claim:
        evidence_present.append("user_claim")
    if not evidence_present:
        evidence_present.append("none")

    missing = []
    if has_ban:
        if not timestamps:
            missing.append("exact ban/review timestamp")
        if not ban_reasons:
            missing.append("copied ban/review reason")
        if not has_claim:
            missing.append("user's own claim/denial")
    if has_money or has_scam:
        if not money_amounts:
            missing.append("amount/currency/diamond quantity")
        if len(uids) < 2:
            missing.append("buyer/seller/counterparty UID")
        if not images and not urls:
            missing.append("payment or chat proof screenshots")
    if has_room and not rooms:
        missing.append("room/group/channel ID")
    if not missing:
        missing.append("none obvious from rules preview")

    urgency_level = bounded_level(1 + len(URGENT_RE.findall(text)) / 2 + (1 if has_claim else 0) + (1 if has_scam else 0))
    trust_risk = bounded_level(1 + 2 * int(has_ban) + 2 * int(has_scam) + int(has_status))
    money_risk = bounded_level(1 + 3 * int(has_money) + int(has_scam))
    safety_risk = bounded_level(1 + 3 * int(bool(re.search(r"\b(?:pornographic|insult|abuse|scam|fraud|violence|threat)\b", text, re.I))))
    note_quality = "forensic" if float(row.get("context_depth_score", 0)) >= 60 else "rich" if float(row.get("context_depth_score", 0)) >= 35 else "adequate"

    literal = flat[:180]
    actual = {
        "avoid_scam": "User wants protection or redress from a scam/fraud dispute.",
        "buy_or_sell_diamonds": "User wants a safer money/diamonds transaction path.",
        "prove_innocence": "User wants fairness, ban transparency, or an appeal path.",
        "grow_channel": "User wants channel/group growth, visibility, ownership, or room functionality restored.",
        "recover_access": "User wants access/account identity restored.",
        "gain_status": "User wants SVIP/status/points/privilege clarity or restoration.",
        "understand_punishment": "User wants a clear explanation of rules, penalties, and what to do next.",
        "restore_visibility": "User wants visibility, reach, or discoverability restored.",
        "fix_product_flow": "User wants a broken product/support flow fixed.",
        "customize_identity": "User wants profile, naming, avatar, or identity assets changed or restored.",
        "restore_income": "User wants lost income, payout, or monetization restored.",
        "protect_community": "User wants moderation action to protect a room, group, or community.",
        "other": "User wants support to interpret and resolve a product/support problem.",
    }[job]

    if job == "prove_innocence":
        next_step = "Check ban history, reason, timestamp, room/user IDs, and compare against provided user claim/evidence."
        product = "Expose ban reason, evidence summary, penalty timeline, and self-serve appeal requirements."
    elif job in {"avoid_scam", "buy_or_sell_diamonds"}:
        next_step = "Verify payment/diamond evidence, identify counterparties, and route to fraud/commerce escalation if proof is sufficient."
        product = "Create safer dealer/payment flow with receipt validation, counterparty identity, and dispute workflow."
    elif job == "grow_channel":
        next_step = "Check channel/group ID, feed visibility, limits, ownership, and active restrictions."
        product = "Build creator ops dashboard for visibility, limits, ownership, and restriction status."
    elif job == "recover_access":
        next_step = "Verify account ownership, phone/SIM status, deletion/block state, and recovery eligibility."
        product = "Build account recovery flow that explains deletion/block/login states and required proof."
    elif job == "understand_punishment":
        next_step = "Translate the rule, penalty, duration, and eligibility requirements into a user-readable explanation."
        product = "Expose a penalty explainer with rule text, timeline, appeal eligibility, and required evidence."
    elif job == "fix_product_flow":
        next_step = "Reproduce the reported flow, capture device/account context, and route to the owning product team."
        product = "Add guided diagnostics that collect context and route broken flows to the right owner automatically."
    elif job == "customize_identity":
        next_step = "Verify the requested identity/profile asset change and check account safety restrictions."
        product = "Build a self-service identity asset workflow with status, rejection reason, and appeal path."
    elif job == "protect_community":
        next_step = "Review reported abuse proof, identify the user/dealer/room, and decide the correct moderation action."
        product = "Create an abuse-report workflow that captures proof, actor identity, room context, and moderation status."
    elif job == "restore_income":
        next_step = "Verify payout, balance, transaction, and monetization records before routing to finance or creator ops."
        product = "Build a monetization ledger with payout status, failed-step diagnostics, and dispute escalation."
    else:
        next_step = "Review evidence and classify into product fix, support macro, or escalation owner."
        product = "Convert repeated support patterns into self-service explanations and escalation forms."

    return {
        "source_row": str(row.get("source_row", "")),
        "literal_request": literal,
        "actual_user_want": actual,
        "job_to_be_done": job,
        "user_emotion": emotion,
        "urgency_level": urgency_level,
        "trust_risk_level": trust_risk,
        "money_risk_level": money_risk,
        "safety_policy_risk_level": safety_risk,
        "evidence_present": evidence_present,
        "evidence_missing": missing,
        "entities": {
            "uids": sorted(set(uids))[:12],
            "room_or_group_ids": sorted(set(rooms))[:12],
            "timestamps": timestamps[:12],
            "ban_reasons": ban_reasons,
            "money_or_diamond_amounts": money_amounts,
            "counterparties": [],
            "url_count": len(urls),
        },
        "support_next_step": next_step,
        "product_opportunity": product,
        "manager_note_quality": note_quality,
        "needs_human_review": bool(trust_risk >= 4 or money_risk >= 4 or safety_risk >= 4),
        "confidence": 0.55,
    }


def write_static_assets(run_dir: Path, candidates: pd.DataFrame) -> None:
    """Emit pre-extraction artifacts: candidates, schemas, sample prompt.

    Even before any model has been called, we want operators to be able to
    audit *what* will be sent. These three files let a human review the
    candidate selection, the schema we're asking the model to follow, and
    a representative prompt — without spending a single API call.

    Args:
        run_dir: The run directory to write into.
        candidates: The DataFrame returned by :func:`load_candidates`.

    Teaching:
        Four file types, four purposes:

        * ``llm_extraction_candidates.csv`` — auditable list of what got
          picked, with all the metadata that drove the decision.
        * ``llm_extraction_schema.json`` — the schema as JSON. Useful
          because the schema is the *contract* between us and the model.
        * ``llm_extraction_response_schema.json`` — the formal JSON Schema
          passed to Ollama structured-output mode.
        * ``llm_extraction_prompt.md`` — a Markdown rendering of the
          system + sample-user prompt, for human review.

        The "render an example artifact before doing the expensive thing"
        pattern is one of the most underrated production-engineering moves.
        It's what enables ``--dry-run`` to be useful.
    """
    candidates.to_csv(run_dir / "llm_extraction_candidates.csv", index=False)
    (run_dir / "llm_extraction_schema.json").write_text(json.dumps(SCHEMA, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "llm_extraction_response_schema.json").write_text(
        json.dumps(extraction_response_schema(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    sample_prompt = candidate_prompt(candidates.iloc[0]) if len(candidates) else USER_TEMPLATE
    (run_dir / "llm_extraction_prompt.md").write_text(
        "# System Prompt\n\n" + SYSTEM_PROMPT + "\n\n# Sample User Prompt\n\n```text\n" + sample_prompt + "\n```\n",
        encoding="utf-8",
    )


def safe_model_slug(model: str) -> str:
    """Convert a model name into a filesystem-safe slug for filenames.

    Model names like ``"gemma3:4b"`` or ``"gpt-4o-mini@2024-08"`` contain
    colons and ``@``, which are illegal on some filesystems and confusing
    on all of them. This produces a tame slug like ``"gemma3-4b"``.

    Args:
        model: The model name (e.g. ``"gemma3:4b"``).

    Returns:
        A lowercase slug containing only letters, digits, ``.``, ``_``,
        and ``-``. Returns ``"model"`` if the input was empty.

    Teaching:
        ``re.sub(pattern, replacement, string)`` substitutes every match.
        The pattern ``[^A-Za-z0-9._-]+`` matches any run of characters
        that are *not* in the allowed set (the ``^`` inside ``[...]``
        means negation). The ``+`` makes the run greedy — multiple bad
        characters collapse to one ``-``.

        ``.strip("-._")`` removes leading/trailing instances of any of
        those characters (it's a charset strip, not a substring strip).
        This avoids slugs like ``"-gemma3-4b-"``.

        The fallback ``slug or "model"`` covers the edge case of an
        all-punctuation input that strips to ``""``.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(model)).strip("-._").lower()
    return slug or "model"


def default_output_stem(backend: str, model: str) -> str:
    """Compute the default output filename stem for a (backend, model) combo.

    Naming convention:

    * Backends that vary by model (``ollama``, ``openai``) get a
      model-suffixed stem like ``ollama_gemma3-4b_extractions``. This lets
      you keep multiple model runs in the same run_dir for comparison.
    * Backends that don't vary (``rules``, ``ollama_hybrid``) get a plain
      ``rules_extractions`` / ``ollama_hybrid_extractions`` stem.

    Args:
        backend: One of ``rules``, ``ollama``, ``ollama_hybrid``, ``openai``.
        model: Model name (only consulted for variable-model backends).

    Returns:
        A filename stem (no extension).

    Teaching:
        ``backend in {"ollama", "openai"}`` uses a *set* literal for
        membership testing. Sets give O(1) lookup vs lists' O(n), but with
        only 2 elements the speed difference is meaningless — it's just a
        readability convention: "these are unordered choices".
    """
    if backend in {"ollama", "openai"}:
        return f"{backend}_{safe_model_slug(model)}_extractions"
    return f"{backend}_extractions"


def run_extraction(
    run_dir: Path,
    candidates: pd.DataFrame,
    model: str,
    sleep_seconds: float,
    resume: bool,
    backend: str,
    ollama_url: str,
    timeout: int,
    output_stem: str,
) -> pd.DataFrame:
    """Iterate candidates, dispatch to the chosen backend, and write JSONL+CSV.

    This is the main extraction loop. It's designed to be **resumable** and
    **defensive**: every successful row is flushed to JSONL immediately, so
    a crash at row 4,000 doesn't lose rows 1-3,999. Any per-ticket exception
    is caught and recorded as ``_status="error"`` rather than aborting the
    whole batch.

    Pipeline per ticket:

    1. Skip if ``source_row`` already in the JSONL (resume support).
    2. Dispatch to the right backend function.
    3. Run :func:`normalize_result_enums` to rewrite known aliases.
    4. Run :func:`output_quality_flag` (model-only backends) to set
       ``_status``.
    5. Stamp ``_backend`` and ``_model`` for provenance.
    6. Write the JSON line, flush, append to in-memory list.
    7. Sleep (rate-limit) between calls.

    After the loop, the JSONL is re-read into a DataFrame and three CSVs
    are produced:

    * ``<output_stem>.csv`` — the model-specific result.
    * ``<backend>_extractions.csv`` — backend-generic alias for dashboards.
    * ``llm_extractions.csv`` — historic generic alias pointing at the
      most recent free/local extraction.

    Args:
        run_dir: The run directory.
        candidates: DataFrame from :func:`load_candidates`.
        model: Model name.
        sleep_seconds: Inter-call delay (rate limiting; 0 disables).
        resume: If True, skip rows already in the JSONL.
        backend: Backend to call.
        ollama_url: Ollama base URL.
        timeout: HTTP timeout seconds.
        output_stem: Filename stem (no extension).

    Returns:
        The full extracted DataFrame (re-read from JSONL).

    Teaching:
        Three production engineering patterns layered together:

        * **JSONL append + flush** — line-delimited JSON is the right
          on-disk format for streaming results. Each call ends with
          ``out.flush()`` so the OS write buffer is drained; if the process
          dies mid-batch, you don't lose buffered rows.
        * **Resume by content** — we don't track "I'm on row 4,000" with a
          counter; instead we read the JSONL and remember which
          ``source_row`` values are already done. This survives reorders,
          deduplication, and partial writes.
        * **Per-call exception isolation** — the ``try: ... except
          Exception:`` around the dispatch means one bad ticket doesn't
          crash the run. The error becomes a record (``_status="error"``)
          rather than a stack trace, and the remaining 99% of tickets
          still complete.

        ``pd.json_normalize`` flattens nested dicts (``entities.uids``,
        ``entities.url_count``) into dot-separated columns. This is what
        lets the resulting CSV have one row per ticket with everything in
        scalar cells.

        The "stable alias" file copies are a *workflow* feature: dashboard
        scripts read ``llm_extractions.csv`` regardless of which model
        produced it, so analysts don't have to update paths.
    """
    output_path = run_dir / f"{output_stem}.jsonl"
    done: set[str] = set()
    if not resume and output_path.exists():
        output_path.unlink()
    if resume and output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(str(json.loads(line).get("source_row", "")))
                except Exception:
                    pass
    rows = []
    with output_path.open("a", encoding="utf-8") as out:
        for _, row in candidates.iterrows():
            source_row = str(row["source_row"])
            if source_row in done:
                continue
            try:
                if backend == "rules":
                    result = call_rules(row)
                elif backend == "ollama":
                    result = call_ollama(row, model=model, ollama_url=ollama_url, timeout=timeout)
                elif backend == "ollama_hybrid":
                    result = call_ollama_hybrid(row, model=model, ollama_url=ollama_url, timeout=timeout)
                elif backend == "openai":
                    result = call_openai(row, model=model)
                else:
                    raise ValueError(f"Unknown backend: {backend}")
                result = normalize_result_enums(result)
                quality_flag = output_quality_flag(result, source_row) if backend in {"ollama", "ollama_hybrid", "openai"} else None
                result["_status"] = "bad_output" if quality_flag else "ok"
                if quality_flag:
                    result["_quality_flag"] = quality_flag
                result["_backend"] = backend
                result["_model"] = model
            except Exception as exc:
                result = {"source_row": source_row, "_status": "error", "_backend": backend, "_model": model, "_error": str(exc)}
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            rows.append(result)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    all_rows = []
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    all_rows.append(json.loads(line))
                except Exception:
                    pass
    extracted = pd.json_normalize(all_rows)
    extracted.to_csv(run_dir / f"{output_stem}.csv", index=False)
    if output_stem != f"{backend}_extractions":
        # Keep stable aliases for dashboards/manual review while preserving per-model files.
        (run_dir / f"{backend}_extractions.jsonl").write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")
        extracted.to_csv(run_dir / f"{backend}_extractions.csv", index=False)
    if backend in {"rules", "ollama", "ollama_hybrid"}:
        # Keep the historical generic filenames pointed at the current free/local result.
        extracted.to_csv(run_dir / "llm_extractions.csv", index=False)
    return extracted


def append_report(run_dir: Path, candidates: pd.DataFrame, extracted: pd.DataFrame | None, dry_run: bool, model: str, backend: str, output_stem: str) -> None:
    """Append (or rewrite) the LLM Extraction Layer section in executive_findings.md.

    The pipeline writes one combined ``executive_findings.md`` covering all
    stages. This function is responsible for the ``## LLM Extraction Layer``
    section. To make repeated runs idempotent, it splits on the section
    marker and replaces only that block.

    Args:
        run_dir: The run directory.
        candidates: Candidate DataFrame.
        extracted: Result DataFrame (None if dry-run).
        dry_run: True if no model calls were made.
        model: Model name (string for the report).
        backend: Backend name.
        output_stem: Filename stem.

    Teaching:
        **Marker-based section idempotency**: the function reads the
        existing report, finds ``"\\n## LLM Extraction Layer\\n"``, splits
        on it, keeps the part *before* the marker, then re-writes its own
        section. Re-running the script doesn't accumulate duplicate
        sections — it replaces.

        ``existing.split(marker, 1)[0]`` — the ``1`` limits the split to
        the first occurrence. ``[0]`` takes the part before the split. The
        ``.rstrip() + "\\n"`` normalizes trailing whitespace before the
        new section is appended.

        Reporting strategy:

        * Always show: candidate count, backend, model, output stem.
        * Dry-run: explain that no calls were made.
        * Real run: count ``_status`` values (ok / bad_output / error),
          show top 10 quality flags and top 10 jobs.

        ``df["col"].value_counts().head(10)`` is the canonical "top-N
        values" idiom in pandas. ``.fillna("ok")`` and ``.fillna("unknown")``
        bucket missing values into a meaningful category instead of
        dropping them.
    """
    report = run_dir / "executive_findings.md"
    existing = report.read_text(encoding="utf-8") if report.exists() else ""
    marker = "\n## LLM Extraction Layer\n"
    if marker in existing:
        existing = existing.split(marker, 1)[0].rstrip() + "\n"
    lines = [
        "",
        "## LLM Extraction Layer",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Candidate rich tickets queued: {len(candidates):,}",
        f"Backend configured: {backend}",
        f"Model configured: {model}",
        f"Output stem: {output_stem}",
    ]
    if dry_run:
        lines.append("Dry run only: no model/API calls were made. Use llm_extraction_candidates.csv, llm_extraction_schema.json, and llm_extraction_prompt.md to review before extraction.")
    else:
        ok = int((extracted.get("_status") == "ok").sum()) if extracted is not None and "_status" in extracted.columns else 0
        errors = int((extracted.get("_status") == "error").sum()) if extracted is not None and "_status" in extracted.columns else 0
        bad = int((extracted.get("_status") == "bad_output").sum()) if extracted is not None and "_status" in extracted.columns else 0
        lines.append(f"Completed extractions: {ok}; bad model outputs: {bad}; errors: {errors}.")
        if extracted is not None and "_quality_flag" in extracted.columns and bad:
            lines += ["", "### Model Output Quality Flags", ""]
            for flag, count in extracted["_quality_flag"].fillna("ok").value_counts().head(10).items():
                lines.append(f"- {flag}: {int(count)}")
        scored = extracted[extracted["_status"].eq("ok")] if extracted is not None and "_status" in extracted.columns else extracted
        if scored is not None and len(scored) and "job_to_be_done" in scored.columns:
            lines += ["", "### Extracted Jobs To Be Done", ""]
            for job, count in scored["job_to_be_done"].fillna("unknown").value_counts().head(10).items():
                lines.append(f"- {job}: {int(count)}")
    lines += [
        "",
        "### Files",
        "",
        "- llm_extraction_candidates.csv",
        "- llm_extraction_schema.json",
        "- llm_extraction_response_schema.json",
        "- llm_extraction_prompt.md",
        "- rules_extractions.jsonl / rules_extractions.csv for deterministic free preview",
        "- ollama_<model>_extractions.jsonl / ollama_<model>_extractions.csv for local Ollama model runs",
        "- ollama_hybrid_<model>_extractions.jsonl / ollama_hybrid_<model>_extractions.csv for rules+local-model runs",
        "- ollama_extractions.jsonl / ollama_extractions.csv points to the latest local Ollama run",
        "- llm_extractions.csv points to the latest free/local extraction output",
    ]
    report.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    """Top-level orchestrator: resolve run dir, load candidates, extract, report.

    Sequence:

    1. Resolve ``run_dir`` (explicit or via :func:`latest_run`).
    2. Compute the output stem from backend + model.
    3. Load candidates.
    4. Always write static assets (candidates CSV, schema JSON, sample
       prompt MD) — even in dry-run mode.
    5. Force dry-run if backend is openai and no API key is set.
    6. Either skip extraction (dry-run) or call :func:`run_extraction`.
    7. Write ``llm_extraction_status.json`` and print it.
    8. Update ``executive_findings.md`` via :func:`append_report`.

    Args:
        args: Parsed CLI namespace from :func:`parse_args`.

    Teaching:
        ``Path(args.run_dir).expanduser().resolve()`` — ``expanduser``
        expands ``~/`` to the home directory; ``resolve`` makes the path
        absolute and follows symlinks. Both are essential for any path
        the user might type.

        The conditional dry-run (``if backend == "openai" and not
        OPENAI_API_KEY``) is a kindness: instead of crashing later with a
        confusing OpenAI auth error, we detect the missing setup and
        gracefully degrade to dry-run, with a ``"reason"`` field in the
        status JSON explaining why.

        The status dict is written to a file *and* printed to stdout. The
        printed JSON is the script's primary external contract — other
        tools can pipe it into ``jq`` or parse it for monitoring.
    """
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else latest_run(Path(args.outputs_dir).expanduser().resolve())
    output_stem = args.output_stem or default_output_stem(args.backend, args.model)
    candidates = load_candidates(
        run_dir,
        limit=args.limit,
        min_context_score=args.min_context_score,
        strategy=args.strategy,
        max_chars=args.max_chars,
    )
    write_static_assets(run_dir, candidates)
    dry_run = args.dry_run
    if args.backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
        dry_run = True
    extracted = None
    if dry_run:
        status = {
            "run_dir": str(run_dir),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "dry_run": True,
            "backend": args.backend,
            "model": args.model,
            "output_stem": output_stem,
            "reason": "--dry-run was used or the selected backend is missing required local/API setup",
            "candidates": int(len(candidates)),
        }
    else:
        extracted = run_extraction(
            run_dir,
            candidates,
            model=args.model,
            sleep_seconds=args.sleep_seconds,
            resume=not args.no_resume,
            backend=args.backend,
            ollama_url=args.ollama_url,
            timeout=args.timeout,
            output_stem=output_stem,
        )
        status_counts = (
            extracted.get("_status", pd.Series(dtype=str))
            .fillna("unknown")
            .astype(str)
            .value_counts()
            .to_dict()
        )
        status = {
            "run_dir": str(run_dir),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "dry_run": False,
            "backend": args.backend,
            "model": args.model,
            "output_stem": output_stem,
            "candidates": int(len(candidates)),
            "extractions_rows": int(len(extracted)),
            "ok_rows": int(status_counts.get("ok", 0)),
            "bad_output_rows": int(status_counts.get("bad_output", 0)),
            "error_rows": int(status_counts.get("error", 0)),
            "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        }
    (run_dir / "llm_extraction_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    append_report(run_dir, candidates, extracted, dry_run=dry_run, model=args.model, backend=args.backend, output_stem=output_stem)
    print(json.dumps(status, indent=2))


def parse_args() -> argparse.Namespace:
    """Define and parse the CLI for ``llm_extract_rich_tickets.py``.

    Returns:
        ``argparse.Namespace`` with parsed flags.

    Teaching:
        Notable flags:

        * ``run_dir`` is positional but ``nargs="?"`` makes it optional —
          if omitted, ``run`` falls back to :func:`latest_run`. This is
          the most ergonomic CLI for a script you'll re-run dozens of
          times in the same project.
        * ``--strategy {highest_context, risk_balanced, issue_balanced}``
          uses ``choices=`` so argparse validates the input for us.
          ``risk_balanced`` is the default because the dataset's most
          interesting tickets are the ones with money/ban/scam signals.
        * ``--backend {rules, ollama, ollama_hybrid, openai}`` defaults to
          ``rules`` — the cheapest option, so accidentally running with
          no flags doesn't burn API budget or local CPU.
        * ``--model`` reads ``LOCAL_LLM_MODEL`` then ``OPENAI_MODEL`` env
          vars, finally falling back to ``mistral-small3.2:24b``. The ``or``
          chain is the canonical "first non-empty value wins" pattern in
          Python.
        * ``--ollama-url`` defaults to ``OLLAMA_URL`` env var or
          ``localhost:11434``. Same pattern.
        * ``--no-resume`` is a flag, not a value. ``action="store_true"``
          flips it to True when present. Used for "wipe and re-run".
        * ``--dry-run`` produces all static assets but no model calls.
          Critical for prompt iteration.

        Reading env vars in defaults (``os.environ.get(..., default)``) is
        the 12-Factor App convention: configuration in the environment,
        with sensible fallbacks for local development.
    """
    parser = argparse.ArgumentParser(description="Queue or run LLM extraction for rich support tickets.")
    parser.add_argument("run_dir", nargs="?", help="Path to outputs/option2_<timestamp>; defaults to latest")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--min-context-score", type=float, default=24.0)
    parser.add_argument("--strategy", choices=["highest_context", "risk_balanced", "issue_balanced"], default="risk_balanced")
    parser.add_argument("--backend", choices=["rules", "ollama", "ollama_hybrid", "openai"], default="rules")
    parser.add_argument("--model", default=os.environ.get("LOCAL_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "mistral-small3.2:24b")
    parser.add_argument("--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-chars", type=int, default=6500)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--output-stem", help="Optional output basename without extension; defaults to backend/model-specific stem")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
