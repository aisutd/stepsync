# StepSync frontend

Expo (React Native) app, TypeScript, file-based routing with Expo Router.

## Run it

```bash
npm install
npx expo start
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
