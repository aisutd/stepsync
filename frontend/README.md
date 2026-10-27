# StepSync frontend

Expo (React Native) app, TypeScript, file-based routing with Expo Router.

## Run it

```bash
npm install
npm start        # add -- -c to clear the cache: npm start -- -c
```

Scan the QR code with Expo Go (Android) or the Camera app (iOS).

## Layout

- `src/app/` screens. `index.tsx` picks or records the two videos, `record.tsx` is the camera,
  `results.tsx` shows feedback.
- `src/api/types.ts` the response shape the backend has to return.
- `src/api/client.ts` uploads to `POST /analyze` with progress. Falls back to `mock.ts` until an API URL is set.
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

## Backend address

`npm start` first runs `scripts/update-api-ip.js`, which sets `EXPO_PUBLIC_API_URL` in `.env`
to this computer's current local IP (port 8000), so a new Wi-Fi address doesn't break uploads.
It leaves the line alone when it's commented out (mock mode) or is an https tunnel URL.
Wrong network picked? `API_IP=192.168.1.20 npm start`. Run it alone with `npm run update-ip`.
