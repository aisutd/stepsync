# StepSync — team frontend + FastAPI + Supabase (merged)

This is the complete original `main-mentee` ZIP overlaid with `stepsync-supabase-merge.zip`, plus authentication UI and a Supabase dance library. The original `index`, `record`, and `results` screens are retained. No SQL policies are modified.

## Before running

Use **Python 3.11** and **Node 20.6+**. You need a Supabase project with the nine tables and RLS policies already created. Never put a service role key in the frontend or backend. Use the publishable key.

### Terminal 1 — FastAPI

```bash
cd ~/Downloads/stepsync-complete/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export SUPABASE_URL='https://YOUR-PROJECT.supabase.co'
export SUPABASE_ANON_KEY='sb_publishable_YOUR_KEY'
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs . Keep the terminal running.

### Terminal 2 — Expo web

```bash
cd ~/Downloads/stepsync-complete/frontend
cp .env.example .env
```

Edit `.env` (without leading `#`) to contain:

```dotenv
EXPO_PUBLIC_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=sb_publishable_YOUR_KEY
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

Then:

```bash
npm install
npx expo start --web --clear
```

For a physical phone replace `127.0.0.1` with your Mac's Wi-Fi IP in `.env`, restart Expo, and use Expo Go only if your Expo version is supported by the installed client.

## Visual tests

1. Log in as User A; verify the email is shown on Home. Supabase SDK persists access/refresh tokens in AsyncStorage on native or browser storage on web.
2. Go to **My dances / Supabase library**, import a short MP4, and wait for pose extraction. Open the dance details; it should show steps and keyframe count. In Supabase Table Editor, verify rows in `dances`, `steps`, `keyframes`.
3. Start practice from a dance's detail page. It creates a `practice_sessions` row. It does **not** score or save an attempt yet.
4. Sign out and log in as User B. A's private dance should disappear. Public dances should be visible if RLS allows them. For a controlled test, set `is_public=true` on A's test dance through an authorized owner operation or the dashboard, then refresh B's library.
5. On Home, select reference and practice videos and press Analyze. `/analyze` currently saves the videos **locally on FastAPI** and returns placeholder feedback, not real comparison scores and not Supabase practice attempts. This is inherited from the original team code.
6. The original camera recording screen works only on supported native devices, not web.

## Authentication and RLS

`frontend/src/api/supabase.ts`: Supabase SDK sign-in and persisted session. On native, AsyncStorage under `sb-*`; on web, the SDK uses browser localStorage. `frontend/src/api/client.ts` retrieves access JWT for every API request and sends `Authorization: Bearer <token>`. `backend/app/supabase_routes.py` passes it to `backend/app/supabase_client.py`, which creates a user-scoped Supabase client. The backend does not persist the JWT. Supabase checks the JWT and applies RLS. `/analyze` is a legacy local placeholder endpoint and should not be considered a secured, persisted comparison workflow.

## Tests

```bash
cd ~/Downloads/stepsync-complete/backend
source venv/bin/activate
python -m pytest -q
```

For live tests, export `STEPSYNC_EMAIL`, `STEPSYNC_PASSWORD`, `STEPSYNC_EMAIL_B`, and `STEPSYNC_PASSWORD_B` in your shell, then run `python tests/test_rls.py`. This script creates and deletes test data. Run it only in a test project or when you are comfortable with those effects. Existing policy gaps may cause FAIL results; the optional SQL was **not** applied.

From frontend run `npm run typecheck`; `npm run test:rls` uses live test credentials in `.env` and is not required for the visual workflow.

## Known limitations

- The original `/analyze` handler returns `overallScore: 0` with placeholder feedback; no real DTW/scoring yet.
- Dance import stores dance metadata and pose keyframes in Supabase; it does not upload the original MP4 to Supabase Storage. The backend processes the video in a temporary directory.
- No RLS policies have been modified.
- Tests against your live Supabase must be run on your machine; the ZIP cannot verify your database configuration.
