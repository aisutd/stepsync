"""Replay any saved pose CSV pair without downloading or extracting video again."""

import argparse
import json
import shutil
from dataclasses import replace
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from typing import Literal
from features import read_pose_csv

from .comparison import ComparisonConfig, compare, samples_from_frames
from .session_store import persist_analysis


class RecompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mirrorMode: Literal["same", "mirrored"]


def recompare_session(source, directory, session_id, mirror_mode, retention, config=None):
    """Copy saved measurements into an independent session; never touch videos."""
    config = replace(config or ComparisonConfig(), mirror_mode=mirror_mode)
    paths = [source / name / "pose_data.csv" for name in ("reference", "practice")]
    if any(not path.is_file() or not path.resolve().is_relative_to(source.resolve()) for path in paths):
        raise HTTPException(409, detail={"code": "pose_data_missing", "message":
            "Saved pose CSVs are unavailable. Select the original videos and upload them again."})
    try:
        sequences = [samples_from_frames(read_pose_csv(path), config, sample=False) for path in paths]
        result = {"sessionId": session_id, **compare(*sequences, config)}
    except (ValueError, KeyError, OSError) as error:
        raise HTTPException(422, "Saved pose CSVs could not be compared. Upload the original videos again.") from error
    directory.mkdir(parents=True, exist_ok=False)
    for name, path in zip(("reference", "practice"), paths):
        target = directory / name / "pose_data.csv"
        target.parent.mkdir()
        shutil.copyfile(path, target)
    return persist_analysis(result, directory, session_id, retention)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--practice-csv", type=Path, required=True)
    parser.add_argument("--mirror-mode", choices=("auto", "same", "mirrored"), default="auto")
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; existing files are never overwritten.")
    args = parser.parse_args()
    config = ComparisonConfig(mirror_mode=args.mirror_mode)
    sequences = [samples_from_frames(read_pose_csv(path), config, sample=False)
                 for path in (args.reference_csv, args.practice_csv)]
    result = compare(*sequences, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(result, destination, indent=2, allow_nan=False)
    print(json.dumps({"output": str(args.output), **{k: result[k] for k in
        ("status", "scoreAvailable", "scoreScope", "movementScore", "reason", "coverage")}}))


if __name__ == "__main__":
    main()
