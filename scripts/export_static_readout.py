#!/usr/bin/env python3
"""Package the static management readout from already-generated run outputs.

This script deliberately does not run embeddings, LLM extraction, clustering, or
Streamlit. It copies the static HTML/CSS/JS shell and the existing CSV/JSON files
needed by the browser app into one CDN-ready folder.
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
DEFAULT_OUT_DIR = ROOT / "outputs" / "static_what_users_want"

DATA_FILES = [
    "longitudinal_metadata.json",
    "run_metadata.json",
    "user_wants_projection_metadata.json",
    "longitudinal_want_monthly_trends.csv",
    "longitudinal_emerging_wants.csv",
    "longitudinal_user_journeys.csv",
    "longitudinal_user_journey_events.csv",
    "longitudinal_journey_archetypes.csv",
    "user_wants_all_assignments.csv",
    "user_wants_full_corpus_summary.csv",
]

ATTRIBUTION_COLUMNS = {
    "manager",
    "managers_touched",
    "top_managers",
    "managers_seen",
    "benchmark_manager",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a static CDN-ready readout using existing CSV outputs."
    )
    parser.add_argument(
        "run_dir",
        type=Path,
        help="Existing pipeline run directory, for example outputs/option2_20260513_030517.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output folder for the static site. Default: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the output folder if it already exists.",
    )
    return parser.parse_args()


def copy_template(out_dir: Path) -> None:
    for item in TEMPLATE_DIR.iterdir():
        target = out_dir / item.name
        if item.name == "data":
            continue
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def copy_data(run_dir: Path, out_dir: Path) -> list[dict[str, object]]:
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, object]] = []
    missing: list[str] = []
    for name in DATA_FILES:
        source = run_dir / name
        if not source.exists():
            missing.append(name)
            continue
        target = data_dir / name
        if source.suffix.lower() == ".csv":
            copy_redacted_csv(source, target)
        else:
            shutil.copy2(source, target)
        copied.append({"name": name, "bytes": target.stat().st_size})
    if missing:
        raise FileNotFoundError(
            "The run directory is missing required static readout files: "
            + ", ".join(missing)
        )
    return copied


def copy_redacted_csv(source: Path, target: Path) -> None:
    """Copy a CSV while dropping person-attribution columns from the static package."""
    with source.open("r", encoding="utf-8", newline="") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames is None:
            target.write_text("", encoding="utf-8")
            return
        fieldnames = [name for name in reader.fieldnames if not is_attribution_column(name)]
        with target.open("w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                writer.writerow(row)


def is_attribution_column(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered in ATTRIBUTION_COLUMNS


def write_manifest(run_dir: Path, out_dir: Path, files: list[dict[str, object]]) -> None:
    manifest = {
        "packaged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_name": run_dir.name,
        "source_run_dir": str(run_dir.resolve()),
        "note": "Static package copied from existing CSV/JSON outputs. No AI or pipeline regeneration ran during export. Person-attribution columns are removed from packaged CSV files.",
        "files": files,
    }
    (out_dir / "data" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    out_dir = args.out_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    if not TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Static template directory does not exist: {TEMPLATE_DIR}")
    if out_dir.exists():
        if not args.force:
            raise FileExistsError(f"Output directory already exists. Use --force to replace it: {out_dir}")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    copy_template(out_dir)
    files = copy_data(run_dir, out_dir)
    write_manifest(run_dir, out_dir, files)
    print(
        json.dumps(
            {
                "status": "ok",
                "out_dir": str(out_dir),
                "index": str(out_dir / "index.html"),
                "data_files": len(files),
                "note": "Upload this folder to the internal CDN, or preview it with: python3 -m http.server --directory "
                + str(out_dir)
                + " 38482",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
