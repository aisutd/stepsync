# StepSync

## Description

StepSync is an AI-powered dance coaching platform that analyzes reference and practice videos, breaks choreography into learnable steps, and gives personalized feedback. Pose estimation, landmark alignment, Dynamic Time Warping, and similarity metrics identify differences in timing, posture, positioning, and execution.

## Pose Coordinates

The pose CSV keeps the original `x_norm`, `y_norm`, `z_relative`, and `world_*` fields. It also includes `hip_relative_x_norm`, `hip_relative_y_norm`, and `hip_relative_z_norm`: MediaPipe world coordinates translated so the midpoint between the hips is the origin, then divided by the distance from that hip midpoint to the shoulder midpoint. The normalized coordinates are unitless torso lengths; `torso_scale_m` records the scale used. These fields are blank when the hip/shoulder anchors are unreliable or world coordinates are unavailable.

Hip centering removes image placement differences and torso scaling reduces overall body-size differences. It does not make 2D camera viewpoints or individual limb proportions identical. Compare joint angles or normalized bone directions alongside these coordinates, confidence values, and a consistent left/right mirroring convention for more robust pose matching. Camera viewpoint changes may still require calibration or a compatible camera setup.

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
