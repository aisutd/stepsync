"""Optional real extraction regression for ANY supplied local video pair.

STEPSYNC_REAL_REFERENCE and STEPSYNC_REAL_PRACTICE enable it. No real video,
network access, or particular choreography is required by the normal suite.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pose_processing import run_pose_extraction


@pytest.mark.skipif(not (os.getenv("STEPSYNC_REAL_REFERENCE") and os.getenv("STEPSYNC_REAL_PRACTICE")),
                    reason="Optional real videos: set STEPSYNC_REAL_REFERENCE and STEPSYNC_REAL_PRACTICE.")
def test_real_upload_pair(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.UPLOAD_DIR", tmp_path / "uploads")
    client = TestClient(create_app(Settings(data_directory=tmp_path), pose_runner=run_pose_extraction))
    with Path(os.environ["STEPSYNC_REAL_REFERENCE"]).open("rb") as reference, \
            Path(os.environ["STEPSYNC_REAL_PRACTICE"]).open("rb") as practice:
        response = client.post("/analyze", files={"reference": ("reference.mp4", reference, "video/mp4"),
                                                 "practice": ("practice.mp4", practice, "video/mp4")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert "frameComparisons" not in result
    detailed = client.get(result["links"]["diagnostics"]).json()
    assert detailed["frameComparisons"]
    assert len(detailed["frameComparisons"]) == result["assessment"]["totalFrames"]
    print({k: result[k] for k in ("status", "movementScore", "coverage", "reason")})
    if result["scoreAvailable"]:
        assert detailed["frameComparisons"]
        assert 0 <= result["movementScore"] <= 100
    else:
        assert result["movementScore"] is None
        assert result["reason"]
        assert result["steps"] == []
        assert all(r["status"] == "unassessed" for r in detailed["frameComparisons"])
