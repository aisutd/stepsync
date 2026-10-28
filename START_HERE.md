# StepSync — redesigned UI + JWT/RLS, YouTube, skeleton MP4, DTW

This is a merged project with **the Oct 27 redesigned team frontend** and **the earlier JWT-scoped FastAPI backend**. No database schema migrations are installed. Do NOT run the destructive migrations from the team release on your existing Supabase database.

## What's connected
- Email/password Supabase auth with persisted sessions; uses your existing `EXPO_PUBLIC_SUPABASE_ANON_KEY` OR `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
- All backend DB and Storage requests use the logged-in user's JWT. No secret/service-role key is required.
- New YouTube modal sends requests to `/dances/import-youtube`, saves annotated `_skeleton.mp4` in the private `dance-videos` bucket, plus a dance, steps, keyframes in existing tables.
- The new Explore tab lists visible dances from Supabase; tap a dance to use its signed skeleton MP4 as a reference.
- Practice > Analyze sends both videos with JWT to `/analyze-dtw`. Pose extraction + DTW generate movement/timing feedback. Uses experimental, uncalibrated scores.

## Install safely
1. **Keep your old `~/Downloads/stepsync-complete` folder as backup.** Extract this archive as a NEW folder `stepsync-redesign-merged`; do not overwrite your current project.
2. In `stepsync-redesign-merged/frontend/`, copy the THREE variables from your OLD `frontend/.env` into a new `.env` (see `.env.example`). **Never copy a `sb_secret_...` key into frontend or backend.** The frontend .env is intentionally omitted from this archive.
3. Terminal A:
```
cd ~/Downloads/stepsync-redesign-merged/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PATH="/opt/homebrew/bin:$PATH"
export SUPABASE_URL="$(sed -n 's/^EXPO_PUBLIC_SUPABASE_URL=//p' ../frontend/.env | tr -d '\r\"')"
export SUPABASE_ANON_KEY="$(sed -n 's/^EXPO_PUBLIC_SUPABASE_ANON_KEY=//p' ../frontend/.env | tr -d '\r\"')"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
4. Terminal B:
```
cd ~/Downloads/stepsync-redesign-merged/frontend
npm ci
npx expo start --web -c
```
5. Log in with an existing test account. Home -> Upload YouTube (short public video, <=60 sec) -> import. Explore -> select saved dance -> Practice -> select/record second practice MP4 -> Analyze. You can also choose both MP4 files directly in Practice.
6. Test Python and TypeScript:
```
cd ~/Downloads/stepsync-redesign-merged/backend && source venv/bin/activate && python -m pytest -q tests/test_dtw_compare.py tests/test_keyframe_identifier.py
cd ~/Downloads/stepsync-redesign-merged/frontend && npx tsc --noEmit
```

## Limitations / important
- Requires existing nine database tables and private `dance-videos` bucket plus ownership Storage policies (already in your current Supabase). `pose_frames` from the Oct 27 team's new schema is not used. No SQL migrations applied.
- Source MP4 is not saved; annotated skeleton MP4 is saved. Signed playback URLs expire after one hour; re-open a dance to refresh.
- Some new team's Home progress and routine cards are static UI demo data; Explore is wired to your real library. Recording on the web depends on the existing frontend's browser/native support; the Practice upload works on web.
- The new team's `segmentation.py` and its `supabase_store.py` service-role pipeline are **not** used. Existing RLS-compatible keyframe grouping is retained.
- The existing backend test expecting every frame as a keyframe may fail; selected keyframes are an intentional behavior change.
- DTW scoring is not yet saved to `step_attempts` and is not scientifically calibrated.
- Full live Supabase/YouTube upload has NOT been executed in this environment. Test from your Mac before considering it fully functional.
