# StepSync frontend

The results screen also includes an AI dance coach. Configure `GEMINI_API_KEY`
in the **Python backend's environment**, following [backend setup](../backend/README.md).
The browser never receives the key. After Analyze, the existing scores and
mistakes appear immediately and initial coaching loads automatically beneath
them. Ask follow-up questions in the chat using the same saved analysis session.
Coaching failures leave numerical results visible. Evidence coverage and partial
score scope remain explicit; unsupported timestamps are not judged. A mirror
retry starts a separate session and coaching history. The MVP uses Gemini to
select supported evidence and practice drills; factual wording comes from saved
measurements rather than unrestricted generated claims.

Expo (React Native) app, TypeScript, file-based routing with Expo Router.

## Test in your browser

From the project root, start the backend in one PowerShell terminal:

```powershell
.\run-local.ps1
```

In a second terminal:

```powershell
cd frontend
npm install # first setup only
npm run web
```

Open http://localhost:8081/practice (or the port Expo prints). Choose a reference
video and a practice video, then click **Analyze**. Upload progress changes to
**Analyzing...** while the server extracts poses. Keep the page open; processing
can take several minutes. Results open automatically. Start with short MP4 clips
(4-10 seconds), one clearly visible dancer per video, similar camera views, and
both dancers' full bodies in frame. Backend duration limit is 60 seconds.

If a backend is already running, restart it to load the latest code. To keep an
older server running on port 8000, use `.\run-local.ps1 -Port 8001` and set
`$env:EXPO_PUBLIC_API_URL = "http://127.0.0.1:8001"` before starting Expo.

The browser connects to `http://127.0.0.1:8000` by default. Override with
`EXPO_PUBLIC_API_URL` in `.env` and restart Expo if using a different backend.
No Supabase credentials are required; without them the existing login gate is skipped.
If Node is not on PATH in this workspace, run this from the project root first:

```powershell
$env:PATH = "$PWD\.local-tools\node-runtime\node-v22.16.0-win-x64;$env:PATH"
```

Every result displays assessment coverage. Analysis-wide eligibility does not
mean every frame was assessed. Partial scores apply only to listed supported
segments; unassessed movements have no correctness result. Tap a detected
mistake to seek to its timestamp. If side matching is ambiguous, **Retry: same
sides** matches left-to-left and **Retry: mirrored sides** matches left-to-right.
Choose the intended convention; retries upload and analyze both videos again.
The backend may still decline to score unreliable footage. Failed requests show
the backend explanation or a connection/timeout message. Selected files and
results live in memory; refreshing the browser requires picking the files again.
Only compact summaries are loaded; frame pages and full diagnostics are not
fetched by the results screen.

## Run on a phone

```bash
npm install
npx expo start
```

Scan the QR code with Expo Go (Android) or the Camera app (iOS).

## Layout

- `src/app/` screens. `(tabs)/practice.tsx` picks or records the two videos, `record.tsx` is the camera,
  `results.tsx` shows feedback.
- `src/api/types.ts` the response shape the backend has to return.
- `src/api/client.ts` uploads to `POST /analyze` with progress. Browser defaults to the local backend. Native previews without an API URL use `mock.ts` sample data.
- `src/state/session.tsx` the picked videos and the latest result.

## Connecting the real backend

Copy `.env.example` to `.env` and set `EXPO_PUBLIC_API_URL` to your laptop's LAN IP
(for example `http://192.168.1.42:8000`), then restart `expo start`.
Run FastAPI with `--host 0.0.0.0` so the phone can reach it.

Recording uses expo-camera and only works in the phone app, not the browser.

## Supabase login

Add to `.env` (Dashboard > Project Settings > API), then `npx expo start -c`:

```
EXPO_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

Without these the login screen is skipped so the app still runs.
Use the publishable (anon) key only, never the secret/service_role key.
