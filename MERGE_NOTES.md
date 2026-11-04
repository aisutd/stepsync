# StepSync multi-branch integration notes

## Changes
- Preserved Satwik frontend redesign, Supabase RLS routes (`/auth`, `/tables`, `/dances`), YouTube import, and authenticated `/analyze-dtw` and `/dances/{dance_id}/analyze-dtw`.
- Added Rodrigo coverage-aware `/analyze` real pose comparison, `/analyses/{id}` persistence, frame pagination, diagnostics retrieval, and `/analyses/{id}/coaching` API. `/analyze` is no longer a placeholder.
- Added movement diagnostics/feature extraction and coaching modules.
- Added a second button on Practice: **Detailed movement analysis + AI coach** for *local reference video* and practice video. The original **Analyze with DTW** button remains (including saved YouTube reference flow).
- Added an evidence-aware Results display and coaching chat only for detailed comparisons.
- Preserved original main-mentee step-segmentation and older UI code under `team-reference/main-mentee/`. These are **not wired into the redesigned application** due to incompatible database, state, and API assumptions. Existing Supabase import features remain. No old service-role backend module was activated.

## Mac setup
- Copy extracted backend/frontend files over your **Satwik-integration working directory**, not Satwik or main directly. Back up first.
- In `backend`, activate your venv, then `python -m pip install -r requirements.txt`. `google-genai` is newly required for optional Gemini support.
- Export `SUPABASE_URL` and `SUPABASE_ANON_KEY` as before. For Gemini coaching (optional), set `GEMINI_API_KEY` in the backend environment, never in Expo. Without it, detailed numerical scores continue working, but chat is unavailable.
- Run `python -m pytest -q tests/test_dtw_compare.py tests/test_comparison.py tests/test_comparison_diagnostics.py tests/test_coaching.py tests/test_features.py tests/test_side_selection.py tests/test_temporal.py`.
- Run `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`. Verify `/docs` has `/analyze`, `/analyses/{session_id}/coaching`, `/analyze-dtw`, and Supabase routes.
- In `frontend`, run `npm install`, `npm run typecheck`, `npx expo start --web -c`. Ensure `frontend/.env` is restored locally as it was not included in the uploaded archive.

## Verification scope
- Syntax compilation succeeded for the merged backend and 51 standalone Python tests passed (DTW/comparison/diagnostics/features/temporal).
- Full API/coaching test collection was blocked in the sandbox because `yt_dlp`, `supabase`, and `mediapipe` were not installed; internet access was unavailable for installing them.
- Frontend TypeScript compilation and live video, YouTube, Supabase, Gemini workflows require local testing on your Mac.
- Do not merge to GitHub Satwik until full test suite and flows pass.

## Security caution
- `/analyze` is a local-development video upload endpoint and currently does not require login. Do not expose the local FastAPI server publicly without adding authentication, rate limits, video retention and privacy protections.
- Supabase routes use caller JWTs and anon/publishable keys; do not use a service-role key.
