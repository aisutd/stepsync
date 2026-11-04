# Local feature extraction — Lucy

Reused from Lucy (`limlucy07/stepsync`, branch `Lucy`), PR
https://github.com/aisutd/stepsync/pull/2 at commit
`f10e327cf24dcf8db40bafe600b9dfcfac7d891b`.

`angles.py`, `velocity.py`, `store.py`, and `__init__.py` preserve her logic.
`pose_csv.py` adds numeric visibility/presence confidence to each landmark;
it retains her raw 3D world-coordinate calculations and missing-value handling.
Her standard-library local JSON/CSV storage is included; Supabase is excluded.

Eight joint angles use world coordinates in meters, returning degrees.
Angular velocities are degrees/second; wrist/ankle speeds are meters/second.
Lucy uses a four-source-frame difference and actual timestamp differences.
Missing measurements remain null, never zero.

StepSync's separate `app/comparison.py` attaches confidence, masks velocities
across unreliable intervals, normalizes comparison speeds by torso length,
samples by source time, aligns, scores, and groups feedback. Saved feature
documents retain Lucy's original units and values. Kaitlyn's smoothing and
pose extraction are unchanged; angles continue using Lucy's raw world data
because mixing normalized and raw coordinates would change her feature meaning.
