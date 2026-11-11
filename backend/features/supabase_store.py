"""Save and load feature rows in Supabase (the `pose_features` table).

Run features/schema_postgres.sql in the Supabase SQL editor once to create the
table. Then set two environment variables (never commit them):

    SUPABASE_URL  e.g. https://<project>.supabase.co
    SUPABASE_KEY  a key allowed to write the table (service role, or anon with
                  a row-level-security policy that permits it)

Uses Supabase's REST API through the standard library, so no extra package is
needed.
"""

import json
import os
import urllib.parse
import urllib.request

from .store import DB_FIELDS, to_db_rows

TABLE = "pose_features"
BATCH_SIZE = 1000  # Supabase returns at most 1000 rows per request by default.


def _settings(url=None, key=None):
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY to use Supabase.")
    return url.rstrip("/"), key


def _request(method, url, key, body=None, extra_headers=None):
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json", **(extra_headers or {})}
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode()
        return json.loads(text) if text else None


def _video_filter(video_id):
    return "video_id=eq." + urllib.parse.quote(video_id, safe="")


def save_features_supabase(doc, url=None, key=None):
    """Replace this video's rows in Supabase. Returns the number of rows written."""
    base, key = _settings(url, key)
    endpoint = f"{base}/rest/v1/{TABLE}"
    _request("DELETE", f"{endpoint}?{_video_filter(doc['video_id'])}", key)
    rows = [{k: row.get(k) for k in DB_FIELDS} for row in to_db_rows(doc)]
    for start in range(0, len(rows), BATCH_SIZE):
        _request("POST", endpoint, key, rows[start:start + BATCH_SIZE],
                 {"Prefer": "return=minimal"})
    return len(rows)


def load_features_supabase(video_id, url=None, key=None):
    """Rows for one video, ordered by frame then feature, as dicts."""
    base, key = _settings(url, key)
    rows, offset = [], 0
    while True:
        page = _request(
            "GET", f"{base}/rest/v1/{TABLE}?select=*&{_video_filter(video_id)}"
                   f"&order=frame_index,feature&limit={BATCH_SIZE}&offset={offset}", key)
        rows.extend(page)
        if len(page) < BATCH_SIZE:
            return rows
        offset += BATCH_SIZE
