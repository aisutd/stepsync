"""StepSync API.

Run from the backend folder:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}
MAX_BYTES = 300 * 1024 * 1024  # 300 MB per video

app = FastAPI(title="StepSync API")

# Lets the Expo web build (a different origin) call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze")
def analyze(
    reference: UploadFile = File(...),
    practice: UploadFile = File(...),
) -> dict:
    session_id = uuid.uuid4().hex
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True)

    try:
        reference_path = save_video(reference, session_dir, "reference")
        practice_path = save_video(practice, session_dir, "practice")
    except HTTPException:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise

    # TODO: replace with the real pipeline (pose estimation, DTW, scoring).
    # The response shape must match AnalysisResult in frontend/src/api/types.ts.
    return placeholder_result(session_id, reference_path, practice_path)


def save_video(upload: UploadFile, folder: Path, stem: str) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    is_video = (upload.content_type or "").startswith("video/") or suffix in VIDEO_SUFFIXES
    if not is_video:
        raise HTTPException(415, f"{stem} must be a video file, got {upload.content_type}.")

    path = folder / f"{stem}{suffix if suffix in VIDEO_SUFFIXES else '.mp4'}"
    written = 0
    with path.open("wb") as out:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_BYTES:
                raise HTTPException(413, f"{stem} video is larger than 300 MB.")
            out.write(chunk)
    if written == 0:
        raise HTTPException(400, f"{stem} video is empty.")
    return path


def placeholder_result(session_id: str, reference: Path, practice: Path) -> dict:
    ref_mb = reference.stat().st_size / 1_000_000
    prac_mb = practice.stat().st_size / 1_000_000
    note = (
        f"Upload received: reference {ref_mb:.1f} MB, practice {prac_mb:.1f} MB "
        f"(session {session_id[:8]}). Real analysis isn't wired up yet."
    )
    return {
        "sessionId": session_id,
        "overallScore": 0,
        "steps": [
            {"id": "1", "label": "Upload", "start": 0, "end": 0, "score": 0, "feedback": note},
        ],
    }
