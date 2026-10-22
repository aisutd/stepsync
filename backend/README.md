# Local YouTube intake and pose processing

From the project root, start the backend with:

```powershell
.\run-local.ps1
```

Use `powershell -ExecutionPolicy Bypass -File .\run-local.ps1` if script execution
is blocked, or `.\run-local.ps1 -Port 8001` to use another port.
The launcher uses `backend/venv`, adds project-local FFmpeg and Deno to PATH
when present, and defaults storage to `.local-tools/data`.

To allow a five-minute video, set limits before starting (restart a running server):

```powershell
$env:STEPSYNC_MAX_DURATION_SECONDS = "300"
$env:STEPSYNC_POSE_PROCESSING_TIMEOUT_SECONDS = "1200"
.\run-local.ps1
```

The 100 MB size limit still applies. Larger values can be set with
`STEPSYNC_MAX_UPLOAD_BYTES`. Longer videos take more time and disk space.

Run from `stepsync/backend` in PowerShell, using the existing Python 3.12 venv:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs. Expand `POST /reference-videos`, click
**Try it out**, replace the JSON request body with:

```json
{"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}
```

Then click **Execute**. This is the short public "Me at the zoo" video; use it
for a manual smoke test after installing FFmpeg. Watch and youtu.be URLs and
Shorts are accepted; unrelated URL parameters are dropped. Playlist parameters
are rejected, even on a watch URL. Confirm HTTP 200, nonzero metadata,
`source_url`, a sanitized title-based `filename`, and an absolute `saved_path`. Also try an invalid URL and a public
video longer than 60 seconds (expect `invalid_url` and `video_too_long`).
No token is needed in this local phase. A valid clip returns HTTP 200 with
metadata, `status: completed`, `pose_processing: completed`, and
`persisted: true`. The validated MP4 is saved under the configured data directory.
The response includes `saved_path`, `pose_preview_path`, and `pose_data_path`.
If extraction fails, HTTP 200 instead contains `status: failed`,
`pose_processing: failed`, `pose_error_code`, and `pose_error`; the saved source
remains available for retry. Check these fields as well as the HTTP status.
Invalid Windows filename characters
are replaced, reserved device names are escaped, and long names are shortened.
Repeated titles use numbered suffixes such as `Title (1).mp4` without overwriting.
Temporary downloads are deleted before the response returns.
There is no saved video ID, status polling, background job, or database state.
Use on localhost only until authentication and private storage are integrated.

Run tests from `backend`:

```powershell
python -m pytest tests -q
```

Tests mock yt-dlp and generate tiny MP4 clips with OpenCV in temporary
directories; they never download YouTube videos or require system FFmpeg. The local OpenCV build must provide an MP4 writer/reader.

## Configurable provisional defaults

Set environment variables before starting the server; restart after changing.
There is no dotenv loader or additional settings framework.

| Variable | Default | Meaning |
| --- | --- | --- |
| `STEPSYNC_ALLOWED_EXTENSIONS` | `.mp4,.mov` | Case-insensitive extension allowlist |
| `STEPSYNC_MAX_UPLOAD_BYTES` | `100000000` | Decimal 100 MB per file |
| `STEPSYNC_MAX_DURATION_SECONDS` | `60` | Maximum duration |
| `STEPSYNC_TARGET_FPS` | `30` | Sampling target; slower sources are not duplicated |
| `STEPSYNC_MAX_FRAME_WIDTH` | `1280` | Prepared-frame width ceiling |
| `STEPSYNC_MAX_FRAME_HEIGHT` | `720` | Prepared-frame height ceiling |
| `STEPSYNC_DATA_DIRECTORY` | Per-user application data directory | Root for saved sources and pose outputs |
| `STEPSYNC_POSE_MODEL_PATH` | `backend/models/pose_landmarker_full.task` | MediaPipe model |
| `STEPSYNC_POSE_PROCESSING_TIMEOUT_SECONDS` | `600` | Maximum seconds for one pose extraction |

When using `run-local.ps1`, the default data root is `.local-tools/data`.
Direct Uvicorn starts default to `%LOCALAPPDATA%/StepSync` on Windows,
`~/Library/Application Support/StepSync` on macOS, and
`$XDG_DATA_HOME/StepSync` (or `~/.local/share/StepSync`) on Linux.
Sources are stored in `videos`; each video's artifacts are stored under
`pose-results/<saved-video-name>/`.

Example: `$env:STEPSYNC_TARGET_FPS = "15"`.
The same bounding box applies to portrait clips: a 1080x1920 frame becomes
405x720. Frames are never enlarged, stretched, cropped, or mirrored.

## Validation and metadata

The endpoint accepts JSON, validates a single YouTube video URL, and uses
`app.youtube` to fetch metadata without downloading media. Known excessive
duration and live/upcoming streams are rejected before download. Missing duration
is allowed through preflight; the existing OpenCV duration validation still runs.
yt-dlp prefers H.264 MP4 video plus M4A audio, with MP4 alternatives, and FFmpeg
merges/remuxes as needed. The resulting `input.mp4` goes directly to the existing
`validate_video` function. The source is persisted before the pose CLI is invoked.
The CLI runs with the server's Python environment, so MediaPipe and OpenCV
must be installed there. It produces `skeleton_preview.mp4` and `pose_data.csv`.

The configured byte limit applies to individual streams, download progress,
temporary stream storage, and the final MP4. Checks are best effort: buffers and
FFmpeg merge output can temporarily exceed it; this is not a disk quota. A whole
request-owned temporary directory removes temporary MP4, audio, partial, and
merge files after both success and failure. After validation, only the final MP4
is copied to the configured video directory. Failed saves remove partial destination copies and return
`save_failed` (500); `persisted: true` is returned only after a successful save. Requests are synchronous; no background queue or
whole-request timeout was added.
Extension and MIME claims do not establish readability: OpenCV opens the file
and sequentially decodes the entire clip. MP4/MOV acceptance still depends on
installed codec support. Renaming another readable container can pass the
extension check; this phase does not independently inspect container signatures.

Metadata reports **source** width/height, FPS, reported frame count, rotation,
and approximate duration (`frame_count / fps`). Count mismatch, no frames, or
unusable timestamps fail validation. Metadata must be positive and finite.
OpenCV may treat some decoder errors as EOF, conceal damaged frames, or supply
inaccurate metadata; validation is best effort, not a complete integrity check.
In particular, average-FPS duration is approximate for variable-frame-rate clips.

Errors use `{"error": {"code": "...", "message": "..."}}`:

| HTTP | Examples |
| --- | --- |
| 415 | `unsupported_format` |
| 413 | `upload_too_large` |
| 422 | `empty_file`, `unreadable_video`, `corrupt_video`, `video_too_long`, `invalid_metadata`, `invalid_timestamps`, `invalid_request` |
| 500 | `processing_failed` (technical details stay in server logs) |
| 502 | `download_failed`, `ffmpeg_failed` |
| 503 | `ffmpeg_unavailable` |

URL errors include `invalid_url`, `unsupported_url`, and `unsupported_video`
(422). Unavailable/private/login/age-restricted videos use `video_unavailable`
(422); other yt-dlp failures use `download_failed` (502). Error classification
uses yt-dlp messages on a best-effort basis; raw errors are logged only.

## Pose extraction and optional frame preparation

`app.pose_processing.run_pose_extraction` invokes `pose_extraction.py` in a child
process. Completion requires both nonempty output files. Failure or timeout removes
partial pose outputs and retains the source. The request waits for processing;
there is no background queue or polling API.

The pose CLI decodes the persisted source itself, preserving its frame rate and
resolution. It does not use the optional sampler below: `STEPSYNC_TARGET_FPS`
and prepared-frame dimensions do not change pose inference inputs.

`app.video.prepared_frames(path, metadata, settings)` yields `PreparedFrame`:

- `source_frame_index`: zero-based original decoded frame index.
- `timestamp_seconds`: OpenCV `CAP_PROP_POS_MSEC`, relative to the first frame.
- `image_rgb`: upright RGB `uint8` NumPy array, shape `(height, width, 3)`.

OpenCV initially decodes BGR. Preparation applies reported 90/180/270-degree
rotation once, resizes with preserved aspect ratio, then converts to RGB.
Rotation metadata support depends on the OpenCV backend; zero may mean absent
or unsupported metadata. Test real phone clips before claiming universal support.

Sampling keeps the first decoded frame in each `1 / target_fps` time bucket,
retaining its actual decoder timestamp rather than assigning a synthetic time.
No interpolation/duplication is performed. Timestamp monotonicity is required;
there is no silent `index / fps` fallback. OpenCV timestamp precision and
variable-frame-rate behavior depend on its backend and need real-clip testing.
OpenCV preprocessing itself is unchanged; the new intake uses system FFmpeg/ffprobe.

`app.handoff.PoseExtractor` remains a legacy prepared-frame interface. The API
uses the persisted-file CLI runner instead. Successful requests return
`completed`; pose failures return `failed` with error fields while retaining the
saved source. Validation, download, and save failures use HTTP errors.
Authentication, database state, feature comparison, and background jobs remain
future work.

## Windows system dependencies and limitations

The launcher can use local builds under `.local-tools/ffmpeg` and
`.local-tools/deno`. For a separate installation, download FFmpeg via https://ffmpeg.org/download.html
(**Windows builds from gyan.dev**, then a release essentials ZIP). Extract it to
a stable directory such as `C:\Tools\ffmpeg`. Locate the extracted `bin` folder
containing both `ffmpeg.exe` and `ffprobe.exe`; add that exact folder to your user
Path in **Edit environment variables for your account** ? **Path** ? **New**.
Close and reopen PowerShell and restart the backend. Verify:

```powershell
Get-Command ffmpeg, ffprobe
ffmpeg -version
ffprobe -version
```

Both commands must resolve and print version information. Installing a Python
package named ffmpeg does not install these system executables.

Current yt-dlp recommends a JavaScript runtime for full YouTube support. The
`yt-dlp[default]` requirement includes its EJS package. If YouTube extraction
reports JavaScript challenge failures, install Deno separately using its official
Windows instructions at https://docs.deno.com/runtime/getting_started/installation/
and verify `deno --version` in the reopened terminal. No runtime is installed by
this backend and no browser cookies or login automation are used. See the current
yt-dlp dependency guidance: https://github.com/yt-dlp/yt-dlp#dependencies.

Only one public normal video at a time; no playlists, channels, searching,
batches, live/upcoming streams, login, or cookie extraction. Network/region
restrictions, anti-bot checks, and changes at YouTube can prevent downloads;
keep yt-dlp current with `python -m pip install -U "yt-dlp[default]"`.
MP4 codec availability still depends on yt-dlp formats and local OpenCV support;
remuxing does not transcode unsupported codecs. The response includes video
metadata, the canonical `source_url`, `saved_path`, and pose artifact paths.
Saved sources and pose outputs remain in the configured data directory until
you delete them.

To manually verify persistence, submit the short public video above twice in
Swagger and confirm both returned `saved_path` files exist with different
filenames, and each response has existing preview and CSV paths. Existing
duration and size limits still apply.

## If localhost connects but documentation hangs

A stale Windows Uvicorn reload process can retain the listening socket after its
server worker has exited. A new process may report startup while requests still
reach the old listener. During diagnosis, this happened on port 8000 while the
same application responded on a clean port; stopping the old StepSync process
trees and starting one server restored responses. The configured data directory
is independent of the listening port.

Stop the previous backend with Ctrl+C and wait for shutdown before starting
another copy. Start from `backend` using the explicit virtualenv Python:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
curl.exe --max-time 10 http://127.0.0.1:8000/openapi.json
```

If it hangs again, inspect `Get-NetTCPConnection -LocalPort 8000 -State Listen`
and identify that PID's command line before stopping it. Stop only the confirmed
StepSync Uvicorn process tree, not all Python processes. Running without
`--reload --reload-dir app` is also supported; restart manually after edits.


# Phone app upload (Aronno)

`POST /analyze` takes two multipart video fields, `reference` and `practice`, from the
Expo app, saves them to `backend/uploads/<session id>/`, and returns a placeholder
result. Swap `placeholder_result` in `app/main.py` for the real pipeline; the response
has to match `AnalysisResult` in `frontend/src/api/types.ts`.

On macOS, run it so a phone on the same Wi-Fi can reach it:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
