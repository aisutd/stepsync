"""Supabase routes for the StepSync API: login, table access and video import.

Every request builds a short lived Supabase client from the caller's token (see
supabase_client.py), so Supabase row level security decides what each user can do.
Nothing in here uses a key that skips RLS.

  POST   /auth/login            email + password -> access token
  GET    /tables/{table}        select   (filters go in the query string)
  POST   /tables/{table}        insert
  PATCH  /tables/{table}        update   (needs a filter)
  DELETE /tables/{table}        delete   (needs a filter)
  POST   /dances/import         upload a video, extract poses, save it as a dance
  GET    /dances/{id}           a dance with its steps and every keyframe
"""

import csv
import logging
import os
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import (APIRouter, Body, Depends, FastAPI, File, Form, Header, HTTPException,
                     Request, UploadFile)
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError
from pydantic import BaseModel

from .config import Settings
from .pose_processing import PoseArtifacts
from .keyframe_identifier import identify_keyframes, group_keyframes
from .supabase_client import (TABLES, check_config, client_for_token, delete_rows,
                              get_anon_client, insert_rows, select_rows, sign_in,
                              update_rows, user_id_from_token)
from .video import VideoError, read_metadata
from .youtube import download_video, validate_url

logger = logging.getLogger(__name__)
RESERVED = {"select", "limit", "order"}  # query params that are not filters
KEYFRAME_BATCH = 100
# Real videos report a frame count a few frames higher than they decode (the repo's own
# RezeDance.mp4 says 619 and decodes 616), so we only reject files that lost over 5% of frames.
FRAME_TOLERANCE = 0.95

# ---------- the pose CSV (33 rows per frame) -> rows for the database ----------
LM_FIELDS = ["landmark_id", "landmark_name", "x_norm", "y_norm", "z_relative", "visibility",
             "presence", "landmark_reliable", "world_x", "world_y", "world_z",
             "hip_relative_x_norm", "hip_relative_y_norm", "hip_relative_z_norm",
             "smooth_x_norm", "smooth_y_norm", "smooth_z_relative",
             "smooth_hip_relative_x_norm", "smooth_hip_relative_y_norm",
             "smooth_hip_relative_z_norm"]


def _num(value):
    return float(value) if value not in ("", None) else None


def load_frames(csv_path) -> List[Dict[str, Any]]:
    """One dict per video frame. Columns that an older CSV lacks come back as None."""
    frames: Dict[int, Dict[str, Any]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            index = int(row["frame_index"])
            frame = frames.setdefault(index, {
                "frame_index": index,
                "timestamp_ms": int(row["timestamp_ms"]),
                "frame_status": row["frame_status"],
                "pose_present": row["pose_present"] == "1",
                "torso_scale_m": _num(row.get("torso_scale_m")),
                "landmarks": [],
            })
            landmark = {}
            for key in LM_FIELDS:
                value = row.get(key)
                if key == "landmark_name":
                    landmark[key] = value
                elif key in ("landmark_id", "landmark_reliable"):
                    landmark[key] = int(value) if value not in ("", None) else None
                else:
                    landmark[key] = _num(value)
            frame["landmarks"].append(landmark)
    return [frames[i] for i in sorted(frames)]


def frames_to_rows(frames):
    """Returns (duration_ms, selected pose keyframe rows)."""
    if not frames:
        raise ValueError("no frames found in the video")
    last_ms = frames[-1]["timestamp_ms"]
    gap = max(1, round(last_ms / (len(frames) - 1))) if len(frames) > 1 else 33
    duration_ms = last_ms + gap
    selected = identify_keyframes(frames)
    keyframes = [{
        "frame_order": order,
        "timestamp_ms": frames[i]["timestamp_ms"],
        "pose_data": {k: frames[i][k] for k in ("frame_status", "pose_present", "torso_scale_m", "landmarks")},
    } for order, i in enumerate(selected, 1)]
    return duration_ms, keyframes


# ---------- request helpers ----------
class Login(BaseModel):
    email: str
    password: str


class YouTubeImport(BaseModel):
    url: str
    title: Optional[str] = None


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def db(authorization: Optional[str] = Header(default=None)):
    """One short lived Supabase client per request, acting as whoever the token says.
    No token means anon, which RLS lets see nothing."""
    token = bearer_token(authorization)
    try:
        return client_for_token(token) if token else get_anon_client()
    except RuntimeError as error:  # Supabase env vars missing, or a key that skips RLS
        raise HTTPException(503, str(error))


def check_table(table: str) -> str:
    if table not in TABLES:
        raise HTTPException(404, f"unknown table {table}")
    return table


def filters_from(request: Request) -> Dict[str, str]:
    return {k: v for k, v in request.query_params.items() if k not in RESERVED}


def supabase_error(request: Request, error: APIError):
    code = str(getattr(error, "code", "") or "")
    if code == "42501":
        status = 403          # RLS refused it
    elif code.startswith("PGRST30"):
        status = 401          # bad or expired token
    elif code in ("23505", "23503"):
        status = 409          # duplicate, or a broken link between tables
    else:
        status = 400
    return JSONResponse(status_code=status,
                        content={"detail": getattr(error, "message", str(error)), "code": code})


def build_router(settings: Settings, pose_runner: Callable[..., PoseArtifacts]) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    def login(body: Login):
        try:
            _, user_id, token = sign_in(body.email, body.password)
        except RuntimeError as error:
            raise HTTPException(503, str(error))
        except Exception:
            raise HTTPException(401, "invalid login")
        return {"user_id": user_id, "access_token": token}

    @router.get("/tables/{table}")
    def read(table: str, request: Request, client=Depends(db)):
        check_table(table)
        limit = request.query_params.get("limit")
        rows = select_rows(client, table, filters_from(request),
                           request.query_params.get("select", "*"),
                           int(limit) if limit else None, request.query_params.get("order"))
        return {"count": len(rows), "rows": rows}

    @router.post("/tables/{table}", status_code=201)
    def create(table: str, body: Union[Dict[str, Any], List[Dict[str, Any]]] = Body(...),
               client=Depends(db)):
        check_table(table)
        rows = insert_rows(client, table, body)
        return {"count": len(rows), "rows": rows}

    @router.patch("/tables/{table}")
    def update(table: str, request: Request, body: Dict[str, Any] = Body(...), client=Depends(db)):
        check_table(table)
        filters = filters_from(request)
        if not filters:
            raise HTTPException(400, "update needs at least one filter in the query string")
        rows = update_rows(client, table, body, filters)
        return {"count": len(rows), "rows": rows}

    @router.delete("/tables/{table}")
    def remove(table: str, request: Request, client=Depends(db)):
        check_table(table)
        filters = filters_from(request)
        if not filters:
            raise HTTPException(400, "delete needs at least one filter in the query string")
        rows = delete_rows(client, table, filters)
        return {"count": len(rows), "rows": rows}

    def _process_and_save(video: Path, work: Path, title: str, token: str, client):
        """Shared authenticated pose/keyframe importer for MP4 and YouTube."""
        metadata = read_metadata(video)
        if metadata.duration_seconds > settings.max_duration_seconds:
            raise VideoError("video_too_long", f"Video duration is approximately "
                             f"{metadata.duration_seconds:.2f} seconds; the limit is "
                             f"{settings.max_duration_seconds:g} seconds.")
        artifacts = pose_runner(video, work / "pose", settings.pose_model_path,
                                settings.pose_processing_timeout_seconds)
        try:
            frames = load_frames(artifacts.data_path)
            duration_ms, keyframes = frames_to_rows(frames)
        except (KeyError, ValueError):
            raise VideoError("pose_data_invalid", "The pose data was not in the expected format.", 500)
        if len(frames) < metadata.frame_count * FRAME_TOLERANCE:
            raise VideoError("corrupt_video", "The video looks truncated: far fewer frames could "
                             "be read than the file says it has.")
        duration_ms = round(metadata.duration_seconds * 1000) or duration_ms

        # Only store a preview when pose detection and keyframe selection succeeded.
        # The extractor draws the body skeleton onto skeleton_preview.mp4.
        if not any(frame.get("pose_present") for frame in frames):
            raise VideoError("no_pose_detected", "No body was detected, so no skeleton video was saved.", 422)
        selected = identify_keyframes(frames)
        if not selected:
            raise VideoError("no_keyframes", "No usable pose keyframes were found, so no video was saved.", 422)
        groups = group_keyframes(frames, selected, duration_ms)
        preview = artifacts.preview_path
        if not preview.is_file() or preview.stat().st_size == 0:
            raise VideoError("missing_preview", "The pose overlay video was not generated.", 500)

        # Save the annotated skeleton preview, NOT the original downloaded MP4.
        # Use the user-scoped client so Storage RLS applies:
        # Supabase Storage RLS will reject uploads outside the user's directory.
        owner_id = user_id_from_token(token)
        bucket = "dance-videos"
        object_path = f"{owner_id}/{uuid.uuid4().hex}_skeleton.mp4"
        storage = client.storage.from_(bucket)
        try:
            with preview.open("rb") as stream:
                storage.upload(path=object_path, file=stream,
                               file_options={"content-type": "video/mp4", "upsert": "false"})
        except Exception as exc:
            logger.exception("Storage upload failed for %s", object_path)
            raise HTTPException(502, "Could not save the video to Supabase Storage. "
                                         "Check the dance-videos bucket and storage RLS policies.") from exc

        # The source_url now points to the skeleton-overlay MP4 (not original).
        # A stable *authenticated* object URL. It is not public: playback must
        # send a user JWT, or request a short-lived signed URL from the route below.
        supabase_base = os.environ["SUPABASE_URL"].rstrip("/")
        video_url = f"{supabase_base}/storage/v1/object/authenticated/{bucket}/{object_path}"
        try:
            dance = insert_rows(client, "dances", {
                "owner_id": owner_id, "title": title,
                "duration_ms": duration_ms, "status": "ready",
                "video_path": object_path,
                "source_url": video_url,
            })[0]
        except Exception:
            storage.remove([object_path])
            raise
        try:
            by_timestamp = {row["timestamp_ms"]: row for row in keyframes}
            for number, (start_ms, end_ms, indices) in enumerate(groups, 1):
                step = insert_rows(client, "steps", {"dance_id": dance["id"],
                                                     "step_order": number,
                                                     "name": f"Practice section {number}",
                                                     "start_ms": start_ms,
                                                     "end_ms": end_ms})[0]
                rows = [{**by_timestamp[frames[i]["timestamp_ms"]], "step_id": step["id"]}
                        for i in indices]
                for i in range(0, len(rows), KEYFRAME_BATCH):
                    insert_rows(client, "keyframes", rows[i:i + KEYFRAME_BATCH])
        except Exception:
            # Best effort cleanup if creating practice steps/keyframes fails.
            try:
                delete_rows(client, "dances", {"id": dance["id"]})
            finally:
                storage.remove([object_path])
            raise
        status = [f["frame_status"] for f in frames]
        return {"dance_id": dance["id"], "frames": len(frames), "keyframes": len(selected),
                "ok_frames": status.count("OK"),
                "low_confidence_frames": status.count("LOW_CONFIDENCE"),
                "no_pose_frames": status.count("NO_POSE")}

    @router.post("/dances/import")
    def import_dance(title: str = Form(...), file: UploadFile = File(...),
                     authorization: Optional[str] = Header(default=None)):
        """Extract pose landmarks, select meaningful frames and save practice sections under RLS."""
        token = bearer_token(authorization)
        if not token:
            raise HTTPException(401, "log in first")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in settings.allowed_extensions:
            raise VideoError("unsupported_format",
                             f"Use one of: {', '.join(settings.allowed_extensions)}.", 415)
        client = db(authorization)
        select_rows(client, "profiles", limit=1)  # cheap check that the token works, before slow work

        with TemporaryDirectory(prefix="stepsync-import-") as directory:
            work = Path(directory)
            video = work / f"input{suffix}"
            written = 0
            with video.open("wb") as out:
                while chunk := file.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > settings.max_upload_bytes:
                        raise VideoError("upload_too_large",
                                         f"File exceeds the {settings.max_upload_bytes}-byte limit.", 413)
                    out.write(chunk)
            if written == 0:
                raise VideoError("empty_file", "The uploaded video is empty.")
            return _process_and_save(video, work, title, token, client)

    @router.post("/dances/import-youtube")
    def import_youtube(body: YouTubeImport, authorization: Optional[str] = Header(default=None)):
        """Download an allowed YouTube URL and import it under the caller's JWT/RLS."""
        token = bearer_token(authorization)
        if not token:
            raise HTTPException(401, "log in first")
        client = db(authorization)
        select_rows(client, "profiles", limit=1)
        url = validate_url(body.url)
        with TemporaryDirectory(prefix="stepsync-youtube-import-") as directory:
            work = Path(directory)
            downloaded = download_video(url, work, settings)
            if downloaded.path.stat().st_size > settings.max_upload_bytes:
                raise VideoError("upload_too_large", "YouTube video exceeds upload limit.", 413)
            title = (body.title or downloaded.title).strip() or "YouTube dance"
            return _process_and_save(downloaded.path, work, title, token, client)


    @router.get("/dances/{dance_id}/video-url")
    def get_playback_url(dance_id: str, client=Depends(db)):
        """Create a short-lived playable skeleton-overlay MP4 URL after RLS verifies access.

        The permanent source_url field is an authenticated storage address and
        may not play inside a plain <video> tag. Use this signed URL instead.
        """
        dances = select_rows(client, "dances", {"id": dance_id})
        if not dances:
            raise HTTPException(404, "dance not found")
        object_path = dances[0].get("video_path")
        if not object_path:
            raise HTTPException(404, "this dance has no stored video")
        try:
            result = client.storage.from_("dance-videos").create_signed_url(object_path, 3600)
        except Exception as exc:
            logger.exception("Failed to sign video URL for %s", dance_id)
            raise HTTPException(502, "Could not create video playback URL") from exc
        return {"url": result.get("signedURL") or result.get("signedUrl"),
                "expires_in": 3600}

    @router.get("/dances/{dance_id}")
    def get_dance(dance_id: str, client=Depends(db)):
        """A dance with its steps and every keyframe, read as the logged in user."""
        dances = select_rows(client, "dances", {"id": dance_id})
        if not dances:
            raise HTTPException(404, "dance not found")  # missing OR hidden by RLS, same answer
        steps = select_rows(client, "steps", {"dance_id": dance_id}, order_by="step_order")
        for step in steps:
            step["keyframes"] = select_rows(client, "keyframes", {"step_id": step["id"]},
                                            order_by="frame_order")
        return {"dance": dances[0], "steps": steps,
                "keyframe_count": sum(len(s["keyframes"]) for s in steps)}

    return router


def register_supabase(app: FastAPI, settings: Settings,
                      pose_runner: Callable[..., PoseArtifacts]) -> None:
    """Called once from create_app. The rest of the app does not need Supabase to run."""
    if os.getenv("SUPABASE_ANON_KEY"):
        check_config()  # refuse to start with a key that skips RLS
    else:
        logger.warning("SUPABASE_URL and SUPABASE_ANON_KEY are not set: Supabase routes answer 503.")
    app.add_exception_handler(APIError, supabase_error)
    app.include_router(build_router(settings, pose_runner))
