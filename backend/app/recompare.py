"""Replay any saved pose CSV pair without downloading or extracting video again."""

import argparse
import json
from pathlib import Path

from features import read_pose_csv

from .comparison import ComparisonConfig, compare, samples_from_frames


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
