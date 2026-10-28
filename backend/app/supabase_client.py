"""ONE file for everything Supabase in the StepSync backend. FastAPI (app/supabase_routes.py) imports from here.

How it works: every request carries a token (JWT). Supabase reads it, works out WHO is asking,
and RLS decides which rows that person can touch. The client itself has no power, RLS defines
what each client can do.

Use the publishable/anon key here. Never the service_role key, it skips RLS.

Pattern: FastAPI gets the user's token from the request, calls client_for_token(token) to make a
short lived client for that one request, runs one of the four functions, and throws it away.
Making a client costs about 0.06 seconds and no network call, so this is cheap.
"""
import base64
import json
import os
from typing import Any, Dict, List, Optional

from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions

TABLES = ("profiles", "dances", "steps", "keyframes", "user_dance_progress",
          "dance_jobs", "saved_dances", "practice_sessions", "step_attempts")


# ---------- clients ----------

def check_config():
    """Fail loudly if the key could skip RLS. Called when the server starts."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY (the publishable key).")
    if key.startswith("sb_secret_"):
        raise RuntimeError("That is a secret key. It skips RLS. Use the publishable key.")
    parts = key.split(".")
    if len(parts) == 3:  # old style JWT keys: look inside for the role
        try:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        except Exception:
            payload = {}
        if payload.get("role") == "service_role":
            raise RuntimeError("That is the service_role key. It skips RLS. Use the anon key.")


def _config():
    check_config()
    return os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"]


def get_anon_client() -> Client:
    """Not signed in. Supabase treats this as the anon role, which should see nothing."""
    url, key = _config()
    return create_client(url, key)


def client_for_token(access_token: str) -> Client:
    """Short lived client that acts as ONE user. Make a new one per request."""
    url, key = _config()
    return create_client(url, key, options=SyncClientOptions(
        headers={"Authorization": f"Bearer {access_token}"}))


def user_id_from_token(access_token: str) -> str:
    """Read the user id (sub) out of the token. Not a trust decision: RLS checks that any
    owner_id we write equals the real auth.uid(), so a made up id is simply refused."""
    payload = access_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["sub"]


def sign_in(email: str, password: str):
    """Log in once. Returns (client, user_id, access_token)."""
    client = get_anon_client()
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    return client, res.user.id, res.session.access_token


def sign_up(email: str, password: str, username: str, first_name: str = "", last_name: str = ""):
    return get_anon_client().auth.sign_up({
        "email": email, "password": password,
        "options": {"data": {"username": username, "first_name": first_name,
                             "last_name": last_name}},
    })


# ---------- the four functions ----------
# Every one returns the list of rows it touched. RLS silently hides rows you may not see, so an
# update or delete on someone else's row just returns an empty list. An insert RLS refuses
# raises an error (code 42501).

def _with_filters(query, filters: Optional[Dict[str, Any]]):
    for column, value in (filters or {}).items():
        query = query.eq(column, value)
    return query


PAGE = 1000  # ask for this many rows per request. The server may cap it lower, so we never
             # assume a short page is the last one, we read until a page comes back empty.


def select_rows(client: Client, table: str, filters: Optional[Dict[str, Any]] = None,
                columns: str = "*", limit: Optional[int] = None,
                order_by: Optional[str] = None) -> List[Dict[str, Any]]:
    """All matching rows, read page by page. Pass order_by on big tables so pages line up."""
    out: List[Dict[str, Any]] = []
    while limit is None or len(out) < limit:
        want = PAGE if limit is None else min(PAGE, limit - len(out))
        query = _with_filters(client.table(table).select(columns), filters)
        if order_by:
            query = query.order(order_by)
        batch = query.range(len(out), len(out) + want - 1).execute().data or []
        if not batch:
            break
        out.extend(batch)
    return out[:limit] if limit else out


def insert_rows(client: Client, table: str, rows: Any) -> List[Dict[str, Any]]:
    return client.table(table).insert(rows).execute().data or []


def update_rows(client: Client, table: str, values: Dict[str, Any],
                filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not filters:
        raise ValueError("update needs at least one filter")
    return _with_filters(client.table(table).update(values), filters).execute().data or []


def delete_rows(client: Client, table: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not filters:
        raise ValueError("delete needs at least one filter")
    return _with_filters(client.table(table).delete(), filters).execute().data or []
