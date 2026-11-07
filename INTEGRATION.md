StepSync scoring integration
============================

The application keeps one POST /analyze endpoint. It accepts either uploaded
reference/practice videos or practice plus reference_video from a saved dance.
step_start_ms and step_end_ms restrict reference measurements to the selected
step. The saved input CSV contains that range, including original timestamps,
so /analyses/{session_id}/recompare uses exactly the same measurements.

Rodrigo's comparison, temporal alignment, side selection, partial comparison,
feature extraction, and coaching algorithms were copied from the sibling
rodrigo-video-comparison working tree. The analysis input adapter handles saved
references and step ranges. The team's Supabase, dance editing, segmentation,
YouTube import, pose extractor, recording, and step picker remain in place.

The results screen includes Gemini coaching, coverage-aware results, technical
details, and side-selection retries. A completed, globally eligible movement
score over 80 passes a step; unavailable and partial scores cannot unlock it.
There is no fabricated legacy timing score. Satwik's dtw_compare.py is retained
for review and its standalone regression tests, but no application code imports it.

Local setup (PowerShell)
-----------------------

    python -m venv backend/venv
    backend/venv/Scripts/python.exe -m pip install -r backend/requirements.txt
    cd frontend
    npm install
    npm run typecheck
    cd ../backend
    venv/Scripts/python.exe -m pytest tests -q

Set GEMINI_API_KEY in backend/.env for live coaching. GEMINI_MODEL is optional;
the existing coaching module defaults to gemini-flash-latest. Existing Supabase
settings remain supported. STEPSYNC_ANALYSIS_RETENTION_SECONDS defaults to seven
days. Credentials are not copied from the original checkout. Browser clients
default to http://127.0.0.1:8000; native clients need EXPO_PUBLIC_API_URL.

The tests isolate dotenv loading and provider credentials. Live Supabase,
YouTube downloads, camera/device behavior, and Gemini provider access need a
manual smoke test with the relevant services and hardware.
