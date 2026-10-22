"""Pose CSV in, saved features out.

    python -m features output/reze_pose_data.csv --video-id reze
    python -m features output/reze_pose_data.csv --video-id reze --frame 100
    python -m features output/reze_pose_data.csv --video-id reze --supabase
"""

import argparse
from pathlib import Path

from .angles import compute_features
from .pose_csv import read_pose_csv
from .store import save_features, save_features_csv


def main():
    parser = argparse.ArgumentParser(prog="python -m features",
                                     description="Compute joint angles from a pose CSV.")
    parser.add_argument("pose_csv", help="CSV written by pose_extraction.py")
    parser.add_argument("--video-id", required=True, help="ID the features are saved under")
    parser.add_argument("--output-dir", default="output/features")
    parser.add_argument("--csv", action="store_true", help="Also write a CSV copy")
    parser.add_argument("--supabase", action="store_true",
                        help="Also write the rows to Supabase (needs SUPABASE_URL and SUPABASE_KEY)")
    parser.add_argument("--frame", type=int, action="append",
                        help="Print this frame's angles for a manual check (repeatable)")
    args = parser.parse_args()

    frames = read_pose_csv(args.pose_csv)
    doc = compute_features(args.video_id, frames, source_file=Path(args.pose_csv).name)
    path = save_features(doc, args.output_dir)

    ok = sum(1 for r in doc["rows"] if r["status"] == "ok")
    print(f"Frames: {len(frames)}  feature values: {len(doc['rows'])}  "
          f"ok: {ok}  missing: {len(doc['rows']) - ok}")
    print(f"Saved: {path}")
    if args.csv:
        print(f"CSV:   {save_features_csv(doc, path.with_suffix('.csv'))}")
    if args.supabase:
        from .supabase_store import save_features_supabase
        print(f"Supabase: {save_features_supabase(doc)} rows in pose_features")

    for frame_index in args.frame or []:
        rows = [r for r in doc["rows"] if r["frame_index"] == frame_index]
        if not rows:
            print(f"\nFrame {frame_index}: not in file")
            continue
        print(f"\nFrame {frame_index} @ {rows[0]['timestamp_ms']} ms ({rows[0]['frame_status']})")
        for r in rows:
            shown = f"{r['value']:7.1f} {r['units']}" if r["status"] == "ok" else f"   --   {r['missing_reason']}"
            print(f"  {r['feature']:<22}{shown}")


if __name__ == "__main__":
    main()
