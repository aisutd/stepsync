"""Immutable local results, compact views, and bounded frame retrieval.

Legacy comparison.json files are indexed lazily without rerunning analysis.
Expiry blocks retrieval; it never silently deletes a user's local artifacts.
"""

from datetime import datetime, timedelta, timezone
from itertools import islice
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from fastapi import HTTPException


SESSION_PATTERN = r"^[0-9a-f]{32}$"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


def utc_now():
    return datetime.now(timezone.utc)


def _read(path):
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, ValueError) as error:
        raise HTTPException(500, "Stored analysis data could not be read.") from error


def _atomic_write(path, write):
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                prefix=".analysis-", suffix=".tmp", delete=False) as target:
            temporary = Path(target.name)
            write(target)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_write(path, data):
    _atomic_write(path, lambda target: json.dump(data, target, allow_nan=False, separators=(",", ":")))


def compact_summary(result, session_id, created, expires):
    # Allow-list the summary, especially alignment's otherwise very large trees.
    keys = ("status", "overallScore", "movementScore", "scoreAvailable", "globalScoreAvailable", "scoreScope",
            "coverage", "confidence", "steps", "comparisonSegments", "reason", "warnings", "sideIndependentEvidence")
    summary = {k: result[k] for k in keys if k in result}
    summary["sideIndependentEvidence"] = result.get("sideIndependentEvidence")
    rows = result.get("frameComparisons", [])
    assessed = sum(r["status"] == "compared" for r in rows)
    summary["assessment"] = {"totalFrames": len(rows), "assessedFrames": assessed,
                             "unassessedFrames": len(rows) - assessed}
    alignment = result.get("alignment", {})
    summary["alignment"] = {k: alignment[k] for k in ("method", "mirrored", "durationRatio", "meanCost",
        "supportedAnchorFraction", "motionCorrelation", "medianTimingOffsetSeconds") if k in alignment}
    selection = alignment.get("mirrorSelection")
    if selection:
        summary["alignment"]["mirrorSelection"] = {k: selection[k] for k in
            ("requestedMode", "decision", "ambiguous", "objectiveMargin", "selectedMapping", "reason") if k in selection}
        evidence = selection.get("selectionEvidence")
        if evidence:
            summary["alignment"]["mirrorSelection"]["selectionEvidence"] = {k: evidence[k] for k in
                ("method", "reasons", "informativeWindows", "windowConsistency", "medianSameAdvantageDegrees",
                 "commonReliableSamples", "bilateralMotionCorrelation", "thresholds", "candidateEvidence") if k in evidence}
    base = f"/analyses/{session_id}"
    return {**summary, "sessionId": session_id, "createdAt": created.isoformat(), "expiresAt": expires.isoformat(),
            "links": {"summary": base, "frames": base + "/frames", "diagnostics": base + "/diagnostics",
                      "download": base + "/diagnostics?download=true"}}


def _save_views(result, directory, session_id, created, retention):
    expires = created + timedelta(seconds=retention)
    summary = compact_summary(result, session_id, created, expires)
    def write_frames(target):
        for row in result.get("frameComparisons", []):
            target.write(json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n")
    _atomic_write(directory / "frames.jsonl", write_frames)
    _json_write(directory / "summary.json", summary)
    # Published last so new sessions never expose partially written views.
    _json_write(directory / "analysis-manifest.json", {"version": 1,
        "createdAt": created.isoformat(), "expiresAt": expires.isoformat()})
    return summary


def persist_analysis(result, directory, session_id, retention):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _json_write(directory / "comparison.json", result)
    return _save_views(result, directory, session_id, utc_now(), retention)


def _artifact(directory, name):
    path = (directory / name).resolve()
    if path.parent != directory:
        raise HTTPException(404, "Analysis artifact is not available.")
    return path


def load_session(root, session_id, retention, *, persist_views=True):
    if not re.fullmatch(SESSION_PATTERN, session_id):
        raise HTTPException(422, "session_id must contain exactly 32 lowercase hexadecimal characters.")
    base = Path(root).resolve()
    directory = (base / session_id).resolve()
    if directory.parent != base or not directory.is_dir():
        raise HTTPException(404, "Analysis session was not found.")
    manifest = _artifact(directory, "analysis-manifest.json")
    full = _artifact(directory, "comparison.json")
    created = None
    expires = None
    if manifest.is_file():
        try:
            metadata = _read(manifest)
            created = datetime.fromisoformat(metadata["createdAt"])
            expires = datetime.fromisoformat(metadata["expiresAt"])
            if created.tzinfo is None or expires.tzinfo is None:
                raise ValueError("Missing timezone")
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(500, "Stored analysis metadata is invalid.") from error
        if utc_now() >= expires:
            raise HTTPException(410, "Analysis session has expired. Upload the videos again to create a new session.")
    if not full.is_file():
        raise HTTPException(404, "No completed analysis is available for this session.")
    if created is None:
        created = datetime.fromtimestamp(full.stat().st_mtime, timezone.utc)
        if utc_now() >= created + timedelta(seconds=retention):
            raise HTTPException(410, "Analysis session has expired. Upload the videos again to create a new session.")
    summary_path, frames_path = _artifact(directory, "summary.json"), _artifact(directory, "frames.jsonl")
    if not manifest.is_file() or not summary_path.is_file() or not frames_path.is_file():
        # Derive storage views from existing measurements, preserving comparison.json.
        fixed_retention = (expires - created).total_seconds() if expires is not None else retention
        if not persist_views:
            return directory, compact_summary(_read(full), session_id, created,
                                               created + timedelta(seconds=fixed_retention))
        _save_views(_read(full), directory, session_id, created, fixed_retention)
    return directory, _read(summary_path)


def get_frame_page(directory, summary, offset, limit):
    if offset < 0 or not 1 <= limit <= MAX_PAGE_SIZE:
        raise HTTPException(422, f"Use offset >= 0 and limit between 1 and {MAX_PAGE_SIZE}.")
    total = summary["assessment"]["totalFrames"]
    if offset > total:
        raise HTTPException(416, f"offset exceeds the {total} available frame records.")
    try:
        with _artifact(directory, "frames.jsonl").open(encoding="utf-8") as source:
            items = [json.loads(row) for row in islice(source, offset, offset + limit)]
    except (OSError, ValueError) as error:
        raise HTTPException(500, "Stored frame records could not be read.") from error
    if len(items) != min(limit, total - offset):
        raise HTTPException(500, "Stored frame records are incomplete.")
    has_more = offset + len(items) < total
    return {"sessionId": summary["sessionId"], "offset": offset, "limit": limit, "total": total,
            "returned": len(items), "hasMore": has_more, "nextOffset": offset + len(items) if has_more else None,
            "items": items}


def diagnostics_path(directory):
    return _artifact(directory, "comparison.json")
