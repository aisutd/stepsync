# Local YouTube intake and pose processing

## Automatic side mapping

Normal `/analyze` uploads and extracts each video once. Auto runs two constrained
DTW hypotheses on those same in-memory features: same sides and mirrored sides.
It does not combine hypotheses frame by frame or choose using the largest score
or assessed coverage. Manual modes retain their original scoring and assessment
behavior. Mirroring swaps feature sides and reflects the camera-space shoulder
axis; measurements and feedback still name the practice dancer's side.

The new `app/side_selection.py` checks asymmetric bilateral joint motion on
common native practice timestamps. Both hypotheses must have accepted pose/view
observations and supported, low-cost bracketing time-map anchors there. Confidence
and configured body-part weights weight the evidence. Native high-FPS duplicates
do not add votes. Symmetric observations cannot determine left/right convention.
Independent windows use a duration-normalized clock to handle reasonable speed
differences; displayed timestamps remain original practice-video seconds.

Selection requires at least three informative windows and two dynamic joint
families, a median bilateral residual advantage of at least 5 degrees, consistent
support in at least 75% of informative windows, bilateral motion correlation at
least 0.35 and an advantage of at least 0.2 over the other mapping. The selected
candidate must also pass existing pose/anchor support, alignment-cost and motion
checks. `ComparisonConfig` exposes `mirror_window_seconds` (1),
`mirror_min_windows` (3), and `mirror_margin_degrees` (5). These are conservative
MVP heuristics, not calibrated anatomical-correspondence probabilities.

Once selected, exactly that candidate's original time map and measurements go
through the existing scoring and feedback pipeline. Auto's score, coverage and
frame records then equal the equivalent explicit mode. A reliable global mapping
can support more frames than independently proving a mapping in every local span;
unreliable observations and unsupported time-map sections remain unassessed.
Ambiguous cases preserve conservative local-only comparison and optional manual
retry. `alignment.mirrorSelection.selectedMapping` is null in those cases;
`alignment.mirrored` indicates only the candidate used for those local records,
not a claimed globally established mapping. No local same/mirrored splicing occurs.

Compact responses include the selected mapping, explanation and bounded selection
audit. Full diagnostics additionally include the per-window evidence. The results
screen identifies automatically/manual selected mappings and keeps assessment
coverage visible. Gemini receives the persisted selected mapping and its actual
measurements; it never chooses a different mapping or generates new observations.

Saved-CSV regression (no re-extraction): the previously investigated video pair
still has contradictory side evidence. Under the new selector there are 102 common
reliable samples and 9 informative windows; the median residual advantage is only
1.18 degrees toward mirrored with 33.33% consistent window support. Bilateral
correlations are 0.2175 same / -0.0871 mirrored. Auto therefore remains partial at
36/780 assessed, while explicit same remains 480/780 and explicit mirrored
236/780. Those larger manual coverages are not proof of physical side convention.
Synthetic tests cover decisive same/mirrored sequences, symmetry, mixed conventions,
confidence, gaps, execution errors, FPS/speed changes, single extraction per video,
and exact equality with the selected manual result. No clip-specific tuning is used.

## Compact summaries and saved analysis details

`POST /analyze` now returns a compact summary by default: session ID, status,
scoped scores, coverage, exact assessment counts, confidence, timeline segments,
mistake events in `steps`, warnings, a compact alignment overview, timestamps,
and retrieval `links`. It does **not** include `frameComparisons`, detailed
`diagnostics`, or per-anchor evidence trees. Missing bulk fields mean the data
is retrieved separately, not that analysis produced no frame records.

The existing results screen uses the summary without downloading details.
Scores, assessment coverage, and partial/global semantics are unchanged.
The comparison, DTW, confidence thresholds, and mirror selector are unchanged.

### Verify in Swagger

1. Restart the backend with `.\run-local.ps1` from the repository root and open
   http://127.0.0.1:8000/docs.
2. Expand **POST /analyze**, click **Try it out**, select both video files, keep
   `mirror_mode` at the intended convention (default `auto`), and **Execute**.
   Copy the returned `sessionId`. Confirm `assessment`, `coverage`, `scoreScope`,
   `steps`, and `links` exist; bulk frame/diagnostic trees should be absent.
3. Expand **GET /analyses/{session_id}**, paste that ID, and execute. This reads
   the same saved summary; no video is reprocessed.
4. Expand **GET /analyses/{session_id}/frames**. Set `offset=0`, `limit=10`, and
   execute. `items` contains original frame indices, practice/reference times,
   joint angles/differences, confidence, and rejection reasons, including
   unassessed records. Use the returned `nextOffset` for the next page. Continue
   until `hasMore=false` and `nextOffset=null`.
5. Expand **GET /analyses/{session_id}/diagnostics**. `download=false` explicitly
   retrieves the full saved comparison JSON. For large files, open the summary's
   `links.download` URL in a browser (prefix with http://127.0.0.1:8000), or set
   `download=true`; the response has an attachment filename. Swagger may still
   preview large JSON when explicitly requested; normal summaries stay small.

For example, the frame request is
`GET /analyses/<sessionId>/frames?offset=0&limit=10`. Defaults are `offset=0`
and `limit=50`, with a maximum page size of **100**. Offsets address stored
records, not the video's original frame indices. At `offset=total`, the API
returns an empty final page; beyond `total`, it returns **416**. Negative offsets,
non-integer parameters, limits outside 1–100, or an ID that is not exactly 32
lowercase hexadecimal characters return **422**. Unknown sessions or sessions
without a completed stored result return **404**. Expired sessions return **410**.

### Persistence and expiry

Each new `backend/uploads/<sessionId>/` directory contains:

- `comparison.json`: complete original result, including every frame and full
  diagnostics; served by the explicit diagnostics/download endpoint.
- `frames.jsonl`: the same detailed frame records, one per line, read a page at
  a time without parsing the entire comparison JSON.
- `summary.json`: compact frontend response with links and exact frame counts.
- `analysis-manifest.json`: creation and expiry times, published after all views
  are written. Result files are published atomically.

Retrieval survives backend restarts and never invokes video validation, pose
extraction, feature calculation, DTW, or scoring. Legacy directories containing
only `comparison.json` have storage views derived on first access; their original
measurements and full file are preserved, and comparison is not rerun. Only the
records originally saved can be retrieved; a legacy empty frame array is not
silently reconstructed from poses.

The default retrieval lifetime is **7 days**, configured independently with
`STEPSYNC_ANALYSIS_RETENTION_SECONDS` (default `604800`). New session expiry is
fixed when the result is saved. Legacy expiry is based on the original full
result's modification time. Reads/restarts do not extend expiry. Expiry denies
API retrieval but does not delete local artifacts; no automatic deletion or
background cleanup was introduced. Changing the setting affects newly saved
sessions, not existing manifests. To exercise expiry quickly, start a test server
with a small positive lifetime, create a new analysis, and request details after
the returned UTC `expiresAt` time.

The frontend client provides optional `getAnalysis`, `getAnalysisFrames`, and
`analysisDiagnosticsUrl` helpers. The results screen never eagerly fetches
frames or diagnostics.

### Response-size measurement

Using the existing saved-pose replay results, without re-extracting or recomputing:

| Replay | Previous full response | Compact summary |
| --- | ---: | ---: |
| Auto | 4,200,519 bytes | 3,541 bytes |
| Same | 3,600,744 bytes | 15,097 bytes |
| Mirrored | 4,043,171 bytes | 10,800 bytes |

These are actual compact UTF-8 HTTP response-body sizes, not compressed sizes.
All are below 100 KB; no grouped feedback events were dropped to meet that goal.
The downloaded full diagnostics were checked against the original complete data.
Measurements are saved in `.local-tools/response-size-check/measurements.json`.
Summary size still depends on the number of grouped feedback events and segments;
there is no hidden truncation or universal size guarantee for arbitrarily long
configured videos.

## Comparing a tutorial and practice video

`POST /analyze` now runs validation, Kaitlyn's existing MediaPipe extraction,
Lucy's joint angles/velocities, and constrained DTW comparison for two multipart
video files named `reference` and `practice`. It runs synchronously; start with
3–10 second clips of the same movement, with the entire dancer visible from
similar camera angles. Default validation limits include 60 seconds per clip.

From the repository root in PowerShell:

```powershell
.\backend\venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\run-local.ps1
```

The existing `backend/models/pose_landmarker_full.task` must be present. A custom
location can be set with `STEPSYNC_POSE_MODEL_PATH` before starting the server.
Open http://127.0.0.1:8000/docs, expand **POST /analyze**, click **Try it out**,
choose both files, and click **Execute**. Or use a second PowerShell terminal:

```powershell
curl.exe -sS -X POST http://127.0.0.1:8000/analyze `
  -F "reference=@C:/videos/tutorial.mp4" `
  -F "practice=@C:/videos/practice.mp4"
```

For a quick identical-video control, select any readable dance clip in both
fields. To exercise real learning feedback, record the same short sequence and
intentionally hold one knee more bent for at least half a second. Repeat with
slower pacing. Capture both clips upright; rotation metadata is currently
rejected because Kaitlyn's CLI consumes the original video directly.

The existing `/reference-videos` endpoint still downloads a YouTube reference.
Use its returned `saved_path` as the local reference file in `/analyze`; the
comparison endpoint does not accept arbitrary server paths or URLs.

For the existing frontend, set `EXPO_PUBLIC_API_URL` in `frontend/.env` to your
backend URL and restart Expo. On a phone, use your computer's LAN IP and start
Uvicorn with `--host 0.0.0.0` from `backend`:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The frontend's existing five-minute request timeout still applies.

### Results and saved evidence

Existing `sessionId`, `overallScore`, and `steps` fields retain the frontend
contract. Each step keeps `id`, `label`, practice-video `start`/`end` seconds,
`score`, and readable `feedback`. Added `evidence` includes `kind` (position or
timing), body part, reference timestamps, expected/observed degrees, difference,
severity, and confidence where applicable. Timing evidence has duration ratio
and offset instead of joint-angle measurements.

Additional result fields:

- `status`: `completed`, `partial`, `insufficient_data`, `uncertain_viewpoint`, or
  `uncertain_alignment`.
- `scoreAvailable`: whether a meaningful score could be computed. **When false,
  `overallScore: 0` is a legacy numeric placeholder, not a dance assessment.**
  `steps` is empty and `warnings` explains why. True also includes scoped partial
  scores; this flag alone never authorizes an analysis-wide score display.
- `movementScore`: the actual movement score, or **null** when comparison is
  unsupported. Prefer this field in new clients; `overallScore` remains numeric
  solely for existing frontend compatibility.
- `reason`: a clear explanation when a score is withheld, otherwise null.
- `frameComparisons` (full diagnostics; paged records are in `items`): one row for **every original practice frame**, even when
  comparison is wholly unassessed, including source frame indices, actual practice/reference times,
  and each configured joint's expected/observed angle, signed/absolute difference,
  confidence, and `matched`, `different`, or `unassessed` status. Unreliable joints
  have null differences and an explanation; occlusions are not invented poses.
- `diagnostics` (explicit detail endpoint): source angle availability and rejection reasons by joint,
  configured thresholds, paired-frame counts/reasons, and local evidence decisions.
- `comparisonSegments`: supported/unassessed timeline spans. Supported partial
  spans include an angle-only score and local motion/mirror evidence; unsupported
  spans have reasons and no score.
- `scoreScope` / `globalScoreAvailable`: a `partial` result scores **only**
  `supported_segments`; its movement/legacy numeric score is not a whole-video
  assessment. With no supported segment, the movement score remains null.
- `assessment`: exact `totalFrames`, `assessedFrames`, and `unassessedFrames`
  counts for original practice frames. These are display metadata derived from
  `frameComparisons`; they never change scoring or eligibility. An assessed frame
  can still have unsupported individual joints.
- `coverage`: reference/practice weighted feature availability and the fraction
  of practice samples with enough comparable angles after alignment (`compared`).
  `assessed` is the fraction actually authorized for measurement after all checks.
- `confidence`: a heuristic combining measurement reliability, overlap, and
  alignment quality; not a calibrated probability.
- `alignment`: chosen left/right mapping, duration ratio, DTW cost, weights,
  and timing offset when supported in the complete result; the compact summary
  includes only its small overview and mirror decision. Positive offset means
  practice movements occur later relative to their respective clip starts.

Each analysis saves uploads, two skeleton previews/pose CSVs, Lucy's original
feature JSON documents, and `comparison.json` in `backend/uploads/<sessionId>/`.
This directory is runtime data; do not commit its video files.

### What `globalScoreAvailable` means

The existing comparator initializes this flag to false and sets it true only
when it computes a score after passing all analysis-wide eligibility checks
(`status: completed`, `scoreScope: aligned_observations`). It means the alignment
is usable across the analysis span under the configured policy. It does **not**
mean 100% of frames/joints were assessed, every movement is correct, or the score
is a whole-video correctness grade. All scores measure supported observations.

With the current defaults, eligibility requires readable inputs with at least
three pose samples, at least 0.5 seconds per clip and a 0.5–2 duration ratio;
at least 50% source weighted-feature coverage; at least 50% supported anchors;
an established automatic or explicitly supplied mirror convention; mean
alignment cost at most 0.4; at least 50% comparable practice frames and 50%
locally bracket-supported practice frames; and motion correlation at least 0.2
when enough varying joint measurements exist to calculate it. Accepted paired
observations must also satisfy configured angle availability, 0.65 measurement
confidence and 0.85 viewpoint agreement. These thresholds remain unchanged by
the presentation update. See `ComparisonConfig` for configurable values.

For example, a completed result with 480/780 frames assessed legitimately has
`globalScoreAvailable: true`, but assessment coverage is only **61.54%**. The
other 300 frames are unassessed, not correct or incorrect. A partial result with
36/780 assessed has an available segment score, `globalScoreAvailable: false`,
and **4.62%** assessment coverage; its number cannot be shown as a global grade.

The results screen always displays assessment coverage, independently of this
flag. It shows completed scores as **Assessed movement similarity** and partial
scores separately as **Assessed segments only**, with an analysis-wide comparison
unavailable message. Unsupported results show no numeric grade. Feedback is
displayed only inside explicitly supported spans; absent feedback is never
presented as evidence that unassessed movements were correct. Older payloads
without trustworthy scope/coverage metadata show coverage unavailable and hide
numeric grades, rather than inferring full assessment from a legacy score.

Frontend presentation tests (Node 22.6+; Node 22.16 was used locally):

```powershell
Push-Location frontend
try { npm test; npm run typecheck } finally { Pop-Location }
```

### Algorithm and configuration

Lucy's modules are attributed in `features/README.md`. Their feature math is
preserved: raw 3D world-coordinate joint angles and four-source-frame velocities
with actual timestamp differences. The comparison adapter attaches numeric
confidence, rejects derivatives spanning unreliable data, and divides wrist/
ankle speeds by torso length to reduce differences in body size. Saved feature
documents remain in Lucy's original units. Kaitlyn's smoothing code is unchanged;
the comparator uses Lucy's raw-world-angle convention rather than mixing spaces.

Alignment lives in `app/temporal.py`, independent of any video filenames,
identities, or saved examples. It uses a common normalized-time grid of up to
600 cells (nominally 10 Hz) to separate source FPS and global speed from local
tempo. Grid cells select nearby real poses; gaps are masked. A 25% relative-time
band bounds drift, and step patterns `(1,1)`, `(1,2)`, `(2,1)` bound normalized
local tempo to 0.5–2 **during optimization**. There are no unbounded one-sided
runs followed by a blanket rejection. Limits and penalties are configurable.

Alignment costs combine confidence-weighted angle differences with a robust
median offset estimated at overlapping normalized instants. This tolerates
dancers' persistent angle offsets while seeking the same movement order. It
does not subtract those offsets from the final posture measurements. Bounded
per-joint losses prevent one incorrect limb from dominating the time map.
Weak clock and stretching penalties bridge detection gaps; missing poses
provide no matching evidence and never improve the final similarity score.
Unknown-cell traversal uses at least the median supported-cell cost, preventing
missing evidence from providing a cheaper shortcut than measured movement.
Alignment cost, anchor support, viewpoint compatibility, and motion-order
correlation can withhold a comparison with an explicit reason.

The resulting monotone time map is applied to every original practice frame.
Only timestamps are interpolated: joint values always come from actual source
observations. Distant reference observations are marked unassessed rather than
interpolating through decoder or pose gaps. Alignment sampling therefore does
not limit frame-by-frame analysis or change the original feedback timestamps.
Automatic left/right matching compares both mappings, withholding judgments
when a nontrivial mismatch leaves the mapping ambiguous.
Mirror hypotheses both swap joint names and reflect the horizontal camera-space
axis before the viewpoint check. Candidates are compared by their full,
duration-normalized objective, not conditional mean costs from different accepted
anchors. `alignment.mirrored` names the selected candidate; consult
`alignment.mirrorSelection.decision` before treating it as established. The
decision may be `undetermined`, with only locally distinguishable spans assessed.

The `/analyze` multipart request also accepts optional `mirror_mode`:
`auto` (default), `same`, or `mirrored`. Existing two-file requests are unchanged.
Use an explicit mode only when the intended left/right convention is known;
it does not bypass confidence, viewpoint, or alignment checks. Swagger exposes
this field. For example, add `-F "mirror_mode=same"` to the upload command.

Movement similarity is `100 * (1 - weighted mean normalized difference)` over
available aligned measurements, weighted by observed time rather than the number
of frames a camera happened to capture. Differences saturate at 90 degrees for angles,
180 degrees/second for angular velocities, and 2 torso lengths/second for speeds.
The local time-map slope normalizes velocity comparisons, so supported pacing
differences are reported as timing instead of an incorrect pose. Missing features reduce coverage
and confidence, not similarity directly. Scores from different coverage levels
are therefore not strictly interchangeable. Timing uses visual pose alignment,
not music or beat detection, and is withheld for static/ambiguous motion.
Timing feedback includes overall duration differences and sustained local early/
late segments after removing global speed. Angle feedback retains original
expected and observed degrees (for example, 160 versus 130 remains a 30-degree
error even if alignment tolerates that offset).

Edit `ComparisonConfig` in `app/comparison.py`, or supply it to
`create_app(comparison_config=...)` in a Python launcher. Default weights:
hips/knees 3 each, elbows/shoulders 2 each, wrist speeds 0.3 each, ankle speeds
0.6 each, angular velocities 0.25 each. Weights, confidence/coverage thresholds,
angle tolerance, minimum segment duration, DTW band, and mirror mode are
configurable. `mirror_mode` supports `auto`, `same`, and `mirrored`.
Only positively weighted features influence scores/feedback.

Reliable comparisons require at least 50% weighted feature availability,
confidence at least 0.65, and duration ratios within 0.5–2. Sustained angle errors
of at least 15 degrees for 0.3 seconds become segments; missing frames, changing
error direction, and shorter isolated differences split or suppress segments.

Source feature coverage, shared angle-weight availability, mean detection
confidence, and supported-anchor fraction have different denominators. In
particular, `frame_status=OK` in Kaitlyn's CSV does not establish that all three
landmarks of every angle meet the comparator's 0.65 threshold. Shared angle
coverage now independently requires 50% of configured angle weight; high
confidence cannot compensate for too few shared joints. Each accepted pair must
also pass the existing 0.85 shoulder-axis agreement threshold. These are
heuristics, not calibrated probabilities or camera calibration.

`alignment.anchorDiagnostics` and `alignment.anchorRejections` expose every
selected anchor's weights, cosine agreement, missing-feature reasons, and
per-joint counts. `alignment.mirrorSelection.candidates` exposes both hypotheses'
objective, conditional mean cost, support fraction, and rejection breakdown.
`diagnostics.reference/practice.byJoint` explains source feature exclusions;
`diagnostics.pairedObservations.byJoint` explains exclusions after pairing.
Reason counts can overlap; accepted/rejected totals are exclusive. Joint keys
name reference joints, with `practiceFeature` identifying the mapped counterpart.

If global evidence fails, partial scoring requires contiguous spans of at least
one second, reliable bracketing anchors, unchanged shared-angle/view thresholds,
alignment cost at most 0.4, and local motion correlation at least 0.2. An
ambiguous global mirror additionally requires at least three commonly supported
anchors, at least 50% common local evidence, and a local cost advantage of 0.015.
Short, static, contradictory, or mirror-ambiguous spans remain unassessed. Partial
scores apply only to approved spans, and whole-video timing feedback is withheld.
The results screen displays scope and assessment coverage for completed and
partial summaries. Full frame evidence remains available through the paginated
endpoint, and complete diagnostic JSON through the explicit download endpoint.

To replay any saved pose CSV pair without running MediaPipe again, from `backend`:

```powershell
.\venv\Scripts\python.exe -m app.recompare `
  --reference-csv "uploads/<session>/reference/pose_data.csv" `
  --practice-csv "uploads/<session>/practice/pose_data.csv" `
  --output "output/new-diagnostics.json"
```

The output must be a new filename; original saved results are not overwritten.
`--mirror-mode same` or `--mirror-mode mirrored` selects an explicit convention.

### Limitations and tests

This MVP measures selected joint bends and movement rates, not every dance
detail: orientation, translation, rhythm against music, foot contacts, and
choreography correctness are not fully modeled. A shoulder-axis viewpoint gate
withholds mismatched views on corresponding poses, but is a heuristic, not camera
calibration. MediaPipe can estimate incorrect 3D poses confidently. Similar
angles can occur in different movements. Automatic mirroring can confuse a
left/right choreography mistake with mirrored footage; use an explicit mode
when the intended convention is known. Short clips of one routine work best.
Thresholds and similarity scores have not been validated against expert ratings.
The current alignment assumes both clips cover the same choreography span;
long unrelated intros/outros, partial routines, extreme tempo changes, or
ambiguous repeated/static poses may require trimming or produce an explanation
instead of feedback. No algorithm can establish reliable correspondence for
arbitrary unrelated or unobservable movements.

Run the complete backend suite from the repository root:

```powershell
Push-Location backend
try { .\venv\Scripts\python.exe -m pytest tests -q } finally { Pop-Location }
```

Tests cover identical sequences, known knee/elbow errors, configurable weighting,
minor wrist versus major knee errors, frame rates/speed, missing/unreliable data,
viewpoint changes, mirrored sequences, grouped practice timestamps, feature
math/storage, and the real API pipeline with injected deterministic pose output.
Unit/API tests do not download YouTube videos or require remote services.

`tests/test_temporal.py` generates multiple previously unseen, multi-joint
choreographies with different FPS/durations, uneven local tempo, noisy dancer
variation, detection gaps, and deliberate knee errors. Tests check correspondence
against the generated ground truth, slope constraints, frame-level measurements,
timestamps, and abstention for reversed/motionless sequences. These are the core
regression tests, independent of real videos.

An optional real extraction/API test accepts any local video pair. From `backend`:

```powershell
$env:STEPSYNC_REAL_REFERENCE = "C:/videos/tutorial.mp4"
$env:STEPSYNC_REAL_PRACTICE = "C:/videos/practice.mp4"
.\venv\Scripts\python.exe -m pytest tests/test_real_comparison.py -q -s
```

It skips unless both variables are set. This verifies the real extraction/upload
workflow, not the correctness of unlabeled dance feedback. No example video is
required or used to configure the implementation.

Manual real-video smoke tests also ran through `/analyze` with real MediaPipe:
a four-second Reze excerpt and a slower version of the same excerpt, plus Reze
versus a four-second Forest excerpt. The matched control produced a high movement
score and timing feedback; Forest lacked reliable pose data and produced no
movement judgments. These controls do not validate feedback against a real
learner's deliberately labeled mistakes.

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
| `STEPSYNC_ANALYSIS_RETENTION_SECONDS` | `604800` | Retrieval lifetime for newly saved analyses; existing expiry stays fixed |

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
# Gemini dance coaching

## Obtain a Gemini API key

1. Open [Google AI Studio](https://aistudio.google.com/) and sign in with your
   Google account. Accept its terms if prompted.
2. Open the dashboard's **API Keys** page and choose **Create API key**.
3. Select a project, or create one if offered. If your existing Cloud project
   is missing, open **Projects**, select **Import projects**, and import it first.
4. Copy the newly created key and enter it at the masked PowerShell prompt below.
   Do not paste it into chat, frontend code, or a tracked file.

See Google's [current key setup instructions](https://ai.google.dev/gemini-api/docs/api-key)
if the UI or project permissions differ. The default StepSync model is
`gemini-flash-latest`, a Google alias whose underlying version can change.
Set backend `GEMINI_MODEL` to a compatible available model ID to choose a
specific version. Availability and quotas depend on your Google project; the
app handles provider errors without removing regular comparison results.

## Configure and test coaching

The results screen automatically requests an initial coaching summary once the
compact comparison has arrived. It uses `POST /analyses/{sessionId}/coaching`
with `{}`. Questions use the same route with
`{"message":"How can I practice the movement at 7 seconds?","requestId":"question_1"}`.
`GET /analyses/{sessionId}/coaching` retrieves saved conversation and availability.
The initial summary is cached. Repeating a question request ID is idempotent;
reusing it with different text returns 409. History is owned by the server, not
accepted from the client. Coaching lives in `coaching.json` alongside immutable
analysis artifacts and follows the existing session expiry (404 missing, 410
expired). No pose extraction, comparison, score, threshold or mirror decision changes.

Install backend dependencies, then set the key in the **backend terminal only**.
From the project root in PowerShell, this avoids putting the key in shell history:

```powershell
backend/venv/Scripts/python.exe -m pip install -r backend/requirements.txt
$geminiKeyInput = Read-Host "Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $geminiKeyInput).Password
$env:GEMINI_MODEL = 'gemini-flash-latest' # optional; override with an available compatible model
.\run-local.ps1 -Port 8001
```

Start the frontend in a separate terminal with
`$env:EXPO_PUBLIC_API_URL = 'http://127.0.0.1:8001'`, then `cd frontend` and
`npm.cmd run web`. Open `http://localhost:8081/practice`, upload the videos, and
click Analyze once. Numerical results appear first; coaching loads beneath the
detected mistakes, without another Analyze click. Ask a question there. A mirror
retry creates a new analysis ID and a separate coaching conversation.
Automatic side matching runs once as part of normal Analyze. If it is uncertain,
the results and coaching scope explain the limitation. Same/mirrored retries
are optional fallbacks; users are not required to run all three modes.

For a browser smoke test, ask **What should I improve first?**, then ask about
your arms and a timestamp within the video. Ask about a timestamp outside the
supported segments too: the coach should explain that it cannot judge it.
Scores, assessed-frame counts, and timestamped mistakes should remain visible
throughout. Stop and restart the existing backend and Expo servers after setup
so they load the new code and environment. If `npm` is unavailable in this
workspace, add the local Node runtime to PATH in the frontend terminal first:

```powershell
$env:PATH = "$PWD\.local-tools\node-runtime\node-v22.16.0-win-x64;$env:PATH"
```

Automated checks use mocked Gemini responses and never require paid API calls:

```powershell
# From backend/
venv/Scripts/python.exe -m pytest tests -q
# From frontend/
npm.cmd test
npm.cmd run typecheck
```

`backend/.env.example` documents variables but is **not automatically loaded**.
Never put the key in an `EXPO_PUBLIC_*` variable, frontend file, request body, or
tracked file. Local `.env` files are ignored. No key is returned to the browser.
Without a key, comparison still works and the coach shows setup guidance. Retry
coaching after configuring/restarting the backend; videos need not be reuploaded.

The official [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
uses structured output to select at most three evidence IDs and appropriate drills.
The backend validates those IDs, match/difference status, timing eligibility, and
drill type. It renders factual sentences from saved engine events and angle
measurements, and practice ideas from bounded templates. **This MVP deliberately
does not expose unrestricted model prose**: Gemini prioritizes and interprets
evidence, but cannot insert arbitrary factual observations, visual details,
numbers, or whole-dance grades. Broad dance-technique questions beyond these
evidence/drill options receive a limitation rather than an invented explanation.

Each model request contains coverage, scope, confidence, up to eight mistake
events, up to eight sampled native frames, and a bounded segment list (truncation
counts are included). Timestamp questions scan saved JSONL for nearby frames;
an unsupported timestamp or requested joint is answered as unknown without a
provider call. Rejected measurements are nulled in model context even if their
raw values exist in diagnostic files. Matched observations can be discussed as
individual supported checkpoints, never proof of an entire correct movement.
The evidence context is capped at 40 KB, with only the last six chat messages
sent for continuity. Video files, full diagnostics and API credentials are not
included. Measured coverage and partial/global scope are always displayed
separately from coaching.

There are at most 20 follow-up questions (1000 characters each) per session.
Provider calls have a 30-second timeout and no automatic retries. Errors return
502 for unsupported/invalid generated plans, 503 for missing credentials/provider
failures/quota, and 429 for the session question limit. Failures never invalidate
comparison results and do not persist an invented fallback answer. Successful
unsupported-evidence explanations are labeled as engine evidence, not Gemini.
Local persistence uses atomic writes and bounded process-local locks: this MVP
supports a single backend process; multiple worker processes need shared locking.

## Gemini request compatibility and troubleshooting

The SDK sends the structured plan using `response_json_schema`, populated from
`CoachingPlan.model_json_schema()`. Do not switch it to `response_schema`: that
legacy Google Schema/protobuf field can reject Pydantic's `extra='forbid'`
as `Unknown name "additional_properties" at generation_config.response_schema`
(HTTP 400). JSON Schema preserves `additionalProperties: false`, while Pydantic
continues validating every returned plan locally. The API key can be valid even
when this schema error occurs. Google's [structured-output reference](https://ai.google.dev/gemini-api/docs/structured-output)
describes the JSON Schema support.

The backend explicitly uses Gemini Developer API (`vertexai=False`), passes
`GEMINI_API_KEY` directly to the official SDK, and reads `GEMINI_MODEL` at each
generation call. Authentication uses the SDK's `x-goog-api-key` header. Another
`GOOGLE_API_KEY` or Vertex environment setting cannot override those explicit
choices. `run-local.ps1` inherits its terminal environment without replacing
either Gemini variable; it does not load a `.env` file. Setting variables in a
different terminal cannot change an already-running server's environment.

After changing code or environment, stop the existing backend with Ctrl+C and
restart it from the terminal where your working key is set:

```powershell
$env:GEMINI_MODEL = 'gemini-3.5-flash-lite'
# Keep your existing GEMINI_API_KEY; do not print it.
.\run-local.ps1 -Port 8001
```

On the existing results screen, click **Retry coaching**. Existing saved analyses
can be reused; neither videos nor comparison results need to be regenerated.
In Swagger, POST `{}` to `/analyses/{sessionId}/coaching` for an initial answer,
or send a follow-up with a distinct `requestId`. Successful initial coaching is
cached. HTTP 400 now identifies request-parameter/schema problems separately
from 401/403 authentication/access, 404 model availability, and 429 quota errors.
Only safe diagnostic categories are returned, never raw provider exceptions,
headers, URLs, credentials, or prompts.
