# StepSync

## Description

StepSync is an AI-powered dance coaching platform that analyzes reference and practice videos, breaks choreography into learnable steps, and gives personalized feedback. Pose estimation, landmark alignment, Dynamic Time Warping, and similarity metrics identify differences in timing, posture, positioning, and execution.

## Planned Technologies

- Python, TypeScript, and SQL
- React Native and MediaPipe
- FastAPI, OpenCV, NumPy, SciPy, PyTorch, and Supabase
- Pose estimation, TensorFlow Lite, and Gemini

## Local backend

Rodrigo's local YouTube intake/preprocessing phase is documented in
[backend/README.md](backend/README.md), including setup, Swagger URL requests, tests,
configurable limits, and the proposed pose handoff. Docker remains a placeholder.

## Docker Setup

Make sure Docker Desktop is installed and running.

```bash
docker compose up -d
docker compose down
docker compose ps
```

This is a generic starter configuration. The team can add project-specific dependencies and startup commands later.
