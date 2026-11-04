# StepSync video metadata compatibility fix

The error `Video FPS, frame count, or dimensions are unavailable.` occurs when OpenCV cannot read a browser-created WebM or certain phone videos reliably. This build uses FFmpeg to normalize WebM uploads (or videos with invalid timestamp/metadata) to constant-frame-rate H.264 MP4 before comparing.

## Required on macOS

```sh
brew install ffmpeg
```

Confirm `ffmpeg -version`, then restart the backend and frontend. Existing videos with valid metadata remain unchanged.

## Run

```sh
cd ~/Downloads/stepsync-dtw-progress/backend
source venv/bin/activate
python -m uvicorn app.main:app --reload --port 8001
```

The existing Supabase environment variables still need to be exported. Frontend must point to port 8001. This is not a fix for corrupt recordings or browser camera permissions.
