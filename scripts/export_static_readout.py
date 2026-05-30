#!/usr/bin/env python3
"""Bake a pipeline run's data into the self-contained static readout.

The deliverable is the folder ``static/what_users_want_cdn/`` itself: a plain
static site whose data lives in ``data/bundle.js`` (``window.WUW_DATA``), loaded
via a ``<script>`` tag. No ``fetch()``, no server — open ``index.html`` directly
(``file://``) or upload the folder to any CDN.

By DEFAULT this script writes ``data/bundle.js`` (+ ``manifest.json``) straight
into ``static/what_users_want_cdn/data/`` — it does not create a separate copy.
Pass ``--out-dir DIR`` to ALSO emit a standalone copy (shell + data) elsewhere.

It runs no embeddings/LLM/clustering — just reads existing outputs. Person-
attribution columns (manager names) are dropped before baking.

Usage:
  python scripts/export_static_readout.py <run_dir> [--out-dir DIR] [--force]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "static" / "what_users_want_cdn"

# run_dir filename -> the key the browser app (app.js FILES) expects in window.WUW_DATA
FILE_TO_KEY = {
    "longitudinal_metadata.json": "longitudinalMeta",
    "run_metadata.json": "runMeta",
    "user_wants_projection_metadata.json": "projectionMeta",
    "longitudinal_want_monthly_trends.csv": "trends",
    "longitudinal_emerging_wants.csv": "emerging",
    "longitudinal_user_journeys.csv": "journeys",
    "longitudinal_user_journey_events.csv": "events",
    "longitudinal_journey_archetypes.csv": "archetypes",
    "user_wants_all_assignments.csv": "assignments",
    "user_wants_full_corpus_summary.csv": "summary",
}
DATA_FILES = list(FILE_TO_KEY)

ATTRIBUTION_COLUMNS = {
    "manager",
    "managers_touched",
    "top_managers",
    "managers_seen",
    "benchmark_manager",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bake run data into the self-contained static readout.")
    parser.add_argument("run_dir", type=Path, help="Pipeline run dir, e.g. outputs/option2_20260513_030517.")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Optional: also write a standalone copy (shell + data) here, for upload.")
    parser.add_argument("--force", action="store_true", help="Replace --out-dir if it already exists.")
    return parser.parse_args()


def copy_template(out_dir: Path) -> None:
    """Copy the static shell (index.html, assets, vendor, …) but not any data/."""
    for item in TEMPLATE_DIR.iterdir():
        if item.name == "data":
            continue
        target = out_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def is_attribution_column(name: str) -> bool:
    return name.strip().lower() in ATTRIBUTION_COLUMNS


def read_redacted_rows(source: Path) -> list[dict[str, str]]:
    """Read a CSV into row dicts, dropping person-attribution columns."""
    with source.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames is None:
            return []
        keep = [n for n in reader.fieldnames if not is_attribution_column(n)]
        return [{k: (row.get(k) or "") for k in keep} for row in reader]


def build_data(run_dir: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    data: dict[str, object] = {}
    files: list[dict[str, object]] = []
    missing: list[str] = []
    for name in DATA_FILES:
        source = run_dir / name
        if not source.exists():
            missing.append(name)
            continue
        key = FILE_TO_KEY[name]
        data[key] = read_redacted_rows(source) if source.suffix.lower() == ".csv" else json.loads(source.read_text(encoding="utf-8"))
        files.append({"name": name, "key": key, "rows": len(data[key]) if isinstance(data[key], list) else None})
    if missing:
        raise FileNotFoundError("The run directory is missing required readout files: " + ", ".join(missing))
    return data, files


def write_bundle(folder: Path, data: dict[str, object], manifest: dict[str, object]) -> int:
    """Write data/bundle.js (window.WUW_DATA) + manifest.json into a readout folder."""
    data_dir = folder / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bundle = data_dir / "bundle.js"
    bundle.write_text("window.WUW_DATA = " + json.dumps({**data, "manifest": manifest}, ensure_ascii=False) + ";\n", encoding="utf-8")
    (data_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return bundle.stat().st_size


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    if not TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Static template directory does not exist: {TEMPLATE_DIR}")

    data, files = build_data(run_dir)
    manifest = {
        "packaged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_name": run_dir.name,
        "source_run_dir": str(run_dir.resolve()),
        "note": "Self-contained static readout: data baked into data/bundle.js (window.WUW_DATA). "
        "No fetch, no server — runs from file:// or any CDN. Person-attribution columns removed.",
        "files": files,
    }

    # Default: bake straight into the CDN folder (the deliverable).
    bundle_bytes = write_bundle(TEMPLATE_DIR, data, manifest)
    targets = [str(TEMPLATE_DIR)]

    # Optional: also emit a standalone copy (shell + data) for upload elsewhere.
    if args.out_dir is not None:
        out = args.out_dir.resolve()
        if out.exists():
            if not args.force:
                raise FileExistsError(f"--out-dir already exists. Use --force to replace it: {out}")
            shutil.rmtree(out)
        out.mkdir(parents=True)
        copy_template(out)
        write_bundle(out, data, manifest)
        targets.append(str(out))

    print(
        json.dumps(
            {
                "status": "ok",
                "deliverable": str(TEMPLATE_DIR),
                "index": str(TEMPLATE_DIR / "index.html"),
                "bundle_bytes": bundle_bytes,
                "data_keys": len(files),
                "wrote": targets,
                "note": "Open static/what_users_want_cdn/index.html directly (file://) or upload that folder to the CDN.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
