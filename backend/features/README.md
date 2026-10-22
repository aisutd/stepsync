# Pose feature extraction and Supabase storage (Lucy)

Run from `stepsync/backend` in PowerShell, using the existing Python 3.12 venv:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m features output/reze_pose_data.csv --video-id reze --csv --frame 0 --frame 150
```

This reads Kaitlyn's pose CSV, calculates the features for every frame, and
writes `output/features/reze_features.json` plus a `.csv` copy. `--frame` prints
that frame's values for a manual check: open the skeleton preview video at the
same frame and confirm that a straight limb reads near 180° and a right angle
near 90°. In frame 0 of the Reze clip, the raised left arm reads about 172° at
the shoulder and the straight legs read 159–167°. Add `--supabase` to also save
the rows to Supabase (see **Configurable settings**). The feature code uses only
the Python standard library; no extra package is needed for Supabase.

Run tests from `backend`:

```powershell
python -m pytest tests/test_features.py tests/test_velocity.py -q
```

Tests use small synthetic pose CSVs written to temporary directories, plus
Kaitlyn's real outputs in `output/`. Supabase calls are replaced with an
in-memory fake, so tests never need network access or Supabase keys.

## Configurable settings

Set environment variables before running with `--supabase`. Never commit them.
There is no dotenv loader.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SUPABASE_URL` | none | Project URL, e.g. `https://<project>.supabase.co` |
| `SUPABASE_KEY` | none | A key allowed to write `pose_features` (service role, or anon with a matching row-level-security policy) |

Example: `$env:SUPABASE_URL = "https://<project>.supabase.co"`.
Before the first save, run `features/schema_postgres.sql` once in the Supabase
SQL editor. It creates the `pose_features` table and the `pose_features_wide`
view. Without both variables, `--supabase` stops with an error naming them.

## Features

Angles use MediaPipe's 3D **world** coordinates (`world_x/y/z`, in meters), so
they don't depend on video size and they include depth. 180° means the limb is
straight.

| Feature | Units | Meaning |
| --- | --- | --- |
| `left/right_elbow_angle` | degrees | Angle at the elbow, between shoulder and wrist |
| `left/right_knee_angle` | degrees | Angle at the knee, between hip and ankle |
| `left/right_shoulder_angle` | degrees | Angle at the shoulder, between elbow and hip |
| `left/right_hip_angle` | degrees | Angle at the hip, between shoulder and knee |
| `left/right_<joint>_velocity` | degrees/s | How fast each angle above changes. Positive = opening (straightening), negative = closing |
| `left/right_wrist_speed`, `left/right_ankle_speed` | m/s | How fast the keypoint moves. World coordinates are hip-centred, so this is speed relative to the body |

Velocities and speeds compare each frame with the one before it, using the
actual `timestamp_ms` difference rather than an assumed frame rate.

## Missing values and saved format

A value is `null`, never 0, and carries a `missing_reason`:

| Reason | Meaning |
| --- | --- |
| `no_pose_detected` | The frame is `NO_POSE` |
| `unreliable:<joint>` | That joint has `landmark_reliable = 0` (Kaitlyn's visibility/presence ≥ 0.5 rule) |
| `no_coordinates:<joint>` | The joint is absent or its world coordinates are blank |
| `degenerate_geometry` | Two joints are at the same point, so the angle is undefined |
| `first_frame` | Velocity only: there is no earlier frame to compare with |
| `angle_missing_in_this_or_previous_frame`, `unavailable:<joint>` | Velocity only: one of the two frames lacks the value |
| `non_increasing_timestamp` | Velocity only: the timestamp did not increase |

Each row also keeps Kaitlyn's `frame_status`, so a frame marked
`LOW_CONFIDENCE` can be filtered out later if needed. Even frames marked `OK`
can have a few unreliable joints, since that status only needs 75% of the core
joints.

`output/features/<video_id>_features.json`:

```json
{
  "schema_version": 1, "feature_set_version": 2, "video_id": "reze",
  "source_pose_file": "reze_pose_data.csv", "coordinate_space": "mediapipe_world_meters",
  "feature_definitions": [{"name": "left_elbow_angle", "units": "degrees",
                           "joints": ["left_shoulder", "left_elbow", "left_wrist"]}],
  "rows": [{"frame_index": 0, "timestamp_ms": 0, "frame_status": "OK",
            "feature": "left_elbow_angle", "value": 162.2, "units": "degrees",
            "status": "ok", "missing_reason": null}]
}
```

`load_features(directory, video_id)` reads the file back and rejects a file
that belongs to a different video or has rows with missing fields.

## Supabase table

`pose_features` holds one row per frame per feature, with the same fields as a
JSON row plus `video_id`. The primary key is `(video_id, frame_index, feature)`.
Saving a video first deletes that video's existing rows, then inserts the new
ones in batches of 1,000, so re-running replaces rather than duplicates.
`load_features_supabase(video_id)` returns the rows ordered by frame, then
feature. `select * from pose_features_wide where video_id = 'reze'` shows one
row per frame with one column per feature.

A 60-second clip (Rodrigo's limit) at 30 fps gives 1,800 frames × 20 features =
36,000 rows. If that's too many, another option is to upload the JSON file to
private storage and keep a single row that points to it. Row-level security can
use the owner on `reference_videos`.

## Lucy's proposed handoff (not a final team contract)

- `read_pose_csv(path)` returns a list of `PoseFrame` (frame index, timestamp,
  status, landmarks by name) from Kaitlyn's CSV.
- `compute_features(video_id, frames)` returns the features document above.
- `save_features(doc, directory)` and `load_features(directory, video_id)`
  write and read the JSON file.
- `save_features_supabase(doc)` and `load_features_supabase(video_id)` write
  and read the Supabase table.

After pose extraction, the pipeline should call `read_pose_csv` →
`compute_features` → `save_features_supabase`.

Waiting on Satwik/Aronno: video ID type and the videos table. `video_id` is
text for now and should become a uuid referencing that table. Also table vs.
JSON-in-storage, and where `owner_id` lives. Waiting on Kaitlyn: whether the CSV
stays one row per landmark, and whether world coordinates are always present
when `pose_present = 1`. Waiting on Rodrigo: calling the steps above from the
pipeline. No teammate functionality is implemented.
