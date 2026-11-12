"""Screenshot-sized visual feedback for the worst DTW intervals.

Draws actual MediaPipe keypoints on the corresponding reference and practice frames.
Red circles show landmarks with the largest camera-normalized pose discrepancies.
Only paired times supplied by the scoring path are used (no LLM guesses).
"""
import base64
import csv
import logging
import math
from pathlib import Path
import cv2

logger = logging.getLogger(__name__)
JOINTS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
EDGES = ((11,12),(11,13),(13,15),(12,14),(14,16),(11,23),(12,24),
         (23,24),(23,25),(25,27),(24,26),(26,28))


def _nearest_pose(path: Path, time_s: float):
    samples = {}
    with path.open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            try:
                timestamp = float(row['timestamp_ms']) / 1000
                landmark = int(row['landmark_id'])
                if landmark not in JOINTS or row.get('pose_present', '1').lower() in ('0', 'false'):
                    continue
                if min(float(row.get('visibility') or 0), float(row.get('presence') or 0)) < 0.5:
                    continue
                x, y = float(row['x_norm']), float(row['y_norm'])
                if math.isfinite(x) and math.isfinite(y):
                    samples.setdefault(timestamp, {})[landmark] = (x, y)
            except (KeyError, TypeError, ValueError):
                continue
    if not samples:
        return {}
    t = min(samples, key=lambda t: abs(t-time_s))
    return samples[t] if abs(t-time_s) <= 0.35 else {}


def _frame(path: Path, at_seconds: float):
    capture = cv2.VideoCapture(str(path))
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0, at_seconds)*1000)
        good, image = capture.read()
        if not good or image is None:
            return None
        height, width = image.shape[:2]
        if width > 520:
            image = cv2.resize(image, (520, round(height * 520 / width)))
        return image
    finally:
        capture.release()


def _draw(frame, points, highlight):
    height, width = frame.shape[:2]
    def px(j):
        x, y = points[j]
        return (max(0,min(width-1,round(x*width))),max(0,min(height-1,round(y*height))))
    for a,b in EDGES:
        if a in points and b in points:
            cv2.line(frame, px(a), px(b), (77,214,147), 2, cv2.LINE_AA)
    for joint in JOINTS:
        if joint not in points: continue
        alert = joint in highlight
        cv2.circle(frame, px(joint), 7 if alert else 4, (45,66,244) if alert else (255,255,255), -1, cv2.LINE_AA)
        if alert:
            cv2.circle(frame, px(joint), 11, (45,66,244), 2, cv2.LINE_AA)
    return frame


def _data_uri(image):
    success, jpg=cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 78])
    if not success:return None
    return 'data:image/jpeg;base64,'+base64.b64encode(jpg.tobytes()).decode('ascii')


def annotated_issue_frames(reference_video: Path, practice_video: Path,
                           reference_csv: Path, practice_csv: Path, issues: list[dict], limit: int = 4):
    """Return at most four image pairs, worst score first. Best-effort diagnostics."""
    output = []
    for issue in sorted((x for x in issues if x.get('score',100) <= 80), key=lambda x:x['score'])[:limit]:
        ref_at = issue.get('worstReferenceTime', (issue['referenceStart'] + issue['referenceEnd']) / 2)
        usr_at = issue.get('worstPracticeTime', (issue['start']+issue['end']) / 2)
        try:
            ref_pts=_nearest_pose(reference_csv, ref_at)
            usr_pts=_nearest_pose(practice_csv, usr_at)
            a=_frame(reference_video, ref_at)
            b=_frame(practice_video, usr_at)
            if a is None or b is None or not ref_pts or not usr_pts: continue
            # rank differences relative to each dancer's hip center and torso size
            def normalized(points):
                required=(11,12,23,24)
                if not all(j in points for j in required):return {}
                hip=tuple((points[23][k]+points[24][k])/2 for k in range(2))
                shoulder=tuple((points[11][k]+points[12][k])/2 for k in range(2))
                scale=math.dist(hip,shoulder)
                return {j: ((p[0]-hip[0])/scale,(p[1]-hip[1])/scale) for j,p in points.items()} if scale>0.025 else {}
            r,u=normalized(ref_pts),normalized(usr_pts)
            diffs=sorted(((math.dist(r[j],u[j]),j) for j in r.keys() & u.keys()),reverse=True)
            highlight={j for diff,j in diffs[:4] if diff>0.15}
            a=_draw(a,ref_pts,highlight)
            b=_draw(b,usr_pts,highlight)
            output.append({'id':issue['id'],'practiceTime':round(usr_at,2),
                           'referenceTime':round(ref_at,2),'joints':sorted(highlight),
                           'referenceImage':_data_uri(a),'practiceImage':_data_uri(b)})
        except Exception:
            logger.exception('Could not render visual feedback for interval %s',issue.get('id'))
    return output
