"""Authenticated real DTW video comparison, leaving legacy /analyze untouched."""
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from typing import Optional
from .dtw_compare import compare_csv
from .supabase_routes import bearer_token, db
from .supabase_client import select_rows
from .video import read_metadata

MAX_BYTES=100_000_000
def _save_upload(file, directory, stem):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.mp4','.mov'):
        raise HTTPException(415,'Only MP4 and MOV videos are supported.')
    target=directory/(stem+suffix)
    count=0
    with target.open('wb') as out:
        while True:
            chunk=file.file.read(1024*1024)
            if not chunk: break
            count+=len(chunk)
            if count>MAX_BYTES: raise HTTPException(413,'Video exceeds 100 MB.')
            out.write(chunk)
    if not count: raise HTTPException(400,'Empty video file.')
    return target



def install_dtw_routes(app, settings, pose_runner):
    router=APIRouter()

    @router.post('/analyze-dtw')
    def analyze_dtw(reference: UploadFile = File(...), practice: UploadFile = File(...),
                    authorization: Optional[str] = Header(default=None)):
        if not bearer_token(authorization):
            raise HTTPException(401,'Log in first.')
        client=db(authorization)
        select_rows(client,'profiles',limit=1)
        with TemporaryDirectory(prefix='stepsync-dtw-') as d:
            folder=Path(d)
            ref=_save_upload(reference,folder,'reference')
            usr=_save_upload(practice,folder,'practice')
            for file in (ref,usr):
                if file.stat().st_size>settings.max_upload_bytes: raise HTTPException(413,'Video exceeds upload limit.')
                duration=read_metadata(file).duration_seconds
                if duration>settings.max_duration_seconds:
                    raise HTTPException(400,f'Video exceeds {settings.max_duration_seconds:g}-second limit.')
            try:
                ref_pose=pose_runner(ref,folder/'reference_pose',settings.pose_model_path,settings.pose_processing_timeout_seconds)
                usr_pose=pose_runner(usr,folder/'practice_pose',settings.pose_model_path,settings.pose_processing_timeout_seconds)
                return compare_csv(ref_pose.data_path,usr_pose.data_path)
            except ValueError as error:
                raise HTTPException(422,str(error)) from error
    @router.post('/dances/{dance_id}/analyze-dtw')
    def analyze_saved_dance(dance_id: str, practice: UploadFile = File(...),
                           authorization: Optional[str] = Header(default=None)):
        """Compare an uploaded practice with a YouTube/imported reference already in Storage.

        Always resolve the storage path from an RLS-authorized dance row, never
        from a URL or an object path supplied by the caller.
        """
        if not bearer_token(authorization):
            raise HTTPException(401, 'Log in first.')
        client = db(authorization)
        dances = select_rows(client, 'dances', {'id': dance_id})
        if not dances:
            raise HTTPException(404, 'Dance not found or not accessible.')
        object_path = dances[0].get('video_path')
        if not object_path:
            raise HTTPException(422, 'This dance has no saved reference video.')
        if not isinstance(object_path, str) or object_path.startswith('/') or '..' in object_path.split('/'):
            raise HTTPException(422, 'Invalid stored reference path.')
        with TemporaryDirectory(prefix='stepsync-saved-dtw-') as d:
            folder = Path(d)
            ref = folder / 'reference.mp4'
            try:
                # Uses the user's JWT, so Storage SELECT policy must allow it.
                payload = client.storage.from_('dance-videos').download(object_path)
            except Exception as exc:
                raise HTTPException(403, 'Cannot read this dance video from private Storage.') from exc
            if not isinstance(payload, (bytes, bytearray)) or not payload:
                raise HTTPException(502, 'Storage returned an empty or invalid reference video.')
            if len(payload) > min(MAX_BYTES, settings.max_upload_bytes):
                raise HTTPException(413, 'Reference video exceeds the upload limit.')
            ref.write_bytes(payload)
            usr = _save_upload(practice, folder, 'practice')
            for file in (ref, usr):
                if file.stat().st_size > settings.max_upload_bytes:
                    raise HTTPException(413, 'Video exceeds upload limit.')
                if read_metadata(file).duration_seconds > settings.max_duration_seconds:
                    raise HTTPException(400, f'Video exceeds {settings.max_duration_seconds:g}-second limit.')
            try:
                ref_pose = pose_runner(ref, folder / 'reference_pose', settings.pose_model_path,
                                       settings.pose_processing_timeout_seconds)
                usr_pose = pose_runner(usr, folder / 'practice_pose', settings.pose_model_path,
                                       settings.pose_processing_timeout_seconds)
                return compare_csv(ref_pose.data_path, usr_pose.data_path)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error

    app.include_router(router)
