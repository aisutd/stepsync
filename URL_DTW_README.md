# StepSync: DTW with imported YouTube references

Apply this ZIP at the root of your existing `~/Downloads/stepsync-redesign-merged` folder. It updates five source files; it does not replace the entire project or your `.env`.

```bash
cd ~/Downloads/stepsync-redesign-merged
unzip -o ~/Downloads/stepsync-youtube-dtw-addon.zip
cd backend
source venv/bin/activate
python -m compileall -q app
python -m pytest -q tests/test_dtw_compare.py
```

Restart FastAPI and Expo as usual. Upload a YouTube video with the in-app YouTube import, or select an imported dance from Explore. On Practice, pick your own recording and tap Analyze. `POST /dances/{dance_id}/analyze-dtw` checks your JWT and dance RLS, downloads the already-saved skeleton MP4 through your authenticated Supabase Storage client, extracts both sequences with Kaitlyn's extractor, and runs the existing DTW matcher. For an ordinary local reference video it keeps using the existing two-file `/analyze-dtw` endpoint.

**Notes:**
- Reference YouTube video needs to have completed import and have a valid `video_path` in `dances` and an accessible file in the `dance-videos` bucket. This does not run on a raw unimported YouTube URL.
- `dance-videos` SELECT policy must permit the signed-in user to read the selected object.
- Current imports only persist the skeleton MP4 and sparse keyframes, so DTW re-extracts pose landmarks from that MP4. Full sampled pose CSV storage would improve speed/accuracy in a future iteration.
- Recordings must meet the backend duration and upload limits, and the downloaded reference must also fit those limits.
- This patch does not save the DTW result to the database; it shows results in the current results UI.
- The scores are heuristic and should be validated on paired dance videos.
- No production account or storage tests were performed while building this patch.
