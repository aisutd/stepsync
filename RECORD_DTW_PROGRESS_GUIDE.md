# StepSync recording, DTW feedback and next-step unlocking

## Practice workflow
1. Choose an imported dance from **Explore** (or import one from YouTube). For saved dances, the app retrieves the tutorial step boundaries.
2. On **Practice**, use **Record practice**. The native Expo app records with `expo-camera`; on the web, `record.web.tsx` uses browser camera APIs. Alternatively select a previously recorded MP4/MOV.
3. Choose **Score step N with DTW**. The app sends the selected tutorial interval (`step_start_ms`, `step_end_ms`) alongside the recording. The backend extracts pose sequences and runs a constrained dynamic time warping comparison.
4. The **Results** screen displays a combined overall score (80% movement, 20% timing), the timing score, low-scoring movement/timing intervals as clickable marks on the mistake timeline, and feedback for each interval. The timeline timestamps refer to the **practice recording**.
5. **Next Step** is enabled only when `overallScore > 80`. An 80/100 does **not** pass. When a step passes and the user taps Next Step, the app advances to the next tutorial step and clears the previous practice recording and score. Finish marks the final step completed.

## Limitations
- Only imported dances with step boundaries have an ordered **Next Step** sequence. A local reference without step boundaries can be recorded and DTW-scored as a whole video, but has no automatic next-step index.
- Progress is held in the active app session's React Context; it is not persisted across app restarts or across devices yet.
- Browser recording works in compatible browsers with camera permission on localhost/HTTPS. The browser selects WebM or MP4. Some OpenCV builds may not decode the resulting WebM; use a saved MP4 if the backend rejects it.
- Real backend DTW requires a signed-in user and configured Supabase. The app's Expo frontend `.env` is separate from the FastAPI backend environment. Set `EXPO_PUBLIC_API_URL` to the actual backend port (e.g. `http://localhost:8001` for browser testing).
- DTW results are **heuristic**, not ground-truth dance grading. The feedback highlights statistical angle/timing discrepancies, not a certified diagnosis of movement errors. Record only the selected step to receive a fair step score.

## Quick start (Mac)
Backend (Terminal A):
```
cd ~/Downloads/stepsync-dtw-progress/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```
Frontend (Terminal B):
```
cd ~/Downloads/stepsync-dtw-progress/frontend
cp ~/Downloads/stepsync-redesign-merged/frontend/.env .env
# Edit EXPO_PUBLIC_API_URL in .env to point to http://localhost:8001
npm install
npx expo start --web -c
```
For phone testing, use the Mac's LAN IP in `EXPO_PUBLIC_API_URL` and run uvicorn with `--host 0.0.0.0`; both devices must be on the same network.

## Verification
The standalone DTW algorithm tests (identical poses, altered tempo, wrist discrepancy) and selected-step bounds checks passed in this environment. Backend syntax and changed TypeScript/TSX syntax parsed successfully. This is **not** a complete end-to-end camera/API/Supabase test: verify on your Mac, including all browsers and the native Expo camera.
