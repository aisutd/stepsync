# Feature extraction and storage (Lucy)

Reads the pose CSV from `pose_extraction.py` (Kaitlyn), calculates joint angles
for every frame, and saves and loads them by video ID. It uses only the Python
standard library.

## Run

From `stepsync/backend`:

```powershell
python -m features output/reze_pose_data.csv --video-id reze --csv --frame 0 --frame 150
python -m pytest tests/test_features.py -q
```

The first command writes `output/features/reze_features.json`, plus a `.csv`
copy, and prints the angles for the chosen frames. Compare those against the
skeleton preview video as a manual check.

## Features (all in degrees)

| Feature | Angle at | Between |
|---|---|---|
| `left/right_elbow_angle` | elbow | shoulder, wrist |
| `left/right_knee_angle` | knee | hip, ankle |
| `left/right_shoulder_angle` | shoulder | elbow, hip |
| `left/right_hip_angle` | hip | shoulder, knee |

180° means the limb is straight. Angles use MediaPipe's 3D **world**
coordinates (`world_x/y/z`, in meters), so they don't depend on video size and
they include depth.

## Missing values

A value is `null`, never 0, and carries a `missing_reason`:

| Reason | Meaning |
|---|---|
| `no_pose_detected` | The frame is `NO_POSE` |
| `unreliable:<joint>` | That joint has `landmark_reliable = 0` (Kaitlyn's visibility/presence ≥ 0.5 rule) |
| `no_coordinates:<joint>` | The joint is absent or its world coordinates are blank |
| `degenerate_geometry` | Two joints are at the same point, so the angle is undefined |

Each row also keeps Kaitlyn's `frame_status`, so a frame marked
`LOW_CONFIDENCE` can be filtered out later if needed. Even frames marked `OK`
can have a few unreliable joints, since that status only needs 75% of the core joints.

## Saved format

`output/features/<video_id>_features.json`:

```json
{
  "schema_version": 1, "feature_set_version": 1, "video_id": "reze",
  "source_pose_file": "reze_pose_data.csv", "coordinate_space": "mediapipe_world_meters",
  "feature_definitions": [{"name": "left_elbow_angle", "units": "degrees",
                           "joints": ["left_shoulder", "left_elbow", "left_wrist"]}],
  "rows": [{"frame_index": 0, "timestamp_ms": 0, "frame_status": "OK",
            "feature": "left_elbow_angle", "value": 161.9, "units": "degrees",
            "status": "ok", "missing_reason": null}]
}
```

## Proposed database table (to confirm with Satwik and Aronno)

`to_db_rows()` returns exactly these fields:

```sql
create table pose_features (
  video_id       uuid not null references reference_videos(id) on delete cascade,
  frame_index    integer not null,
  timestamp_ms   integer not null,
  frame_status   text not null,          -- OK / LOW_CONFIDENCE / NO_POSE
  feature        text not null,
  value          double precision,       -- null when missing
  units          text not null,
  status         text not null check (status in ('ok', 'missing')),
  missing_reason text,
  primary key (video_id, frame_index, feature)
);
```

A 60-second clip (Rodrigo's limit) at 30 fps gives 1,800 frames × 8 features =
14,400 rows. If that's too many, another option is to upload the JSON file to
private storage and keep a single row that points to it. Row-level security can
use the owner on `reference_videos`.

## Open questions

- **Satwik and Aronno:** video ID type (uuid?), table vs. JSON-in-storage, and where `owner_id` lives.
- **Kaitlyn:** will the CSV stay one row per landmark? Will the world coordinates always be present when `pose_present = 1`?
- **Rodrigo:** the pipeline should call `read_pose_csv` → `compute_features(video_id, frames)` → `save_features` after pose extraction.
