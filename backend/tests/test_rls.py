"""LIVE RLS tests for StepSync, run by hand (they need your Supabase). From the backend folder,
with the server running (uvicorn app.main:app --reload):

    python tests/test_rls.py                 all 9 tables x select/insert/update/delete,
                                             then a REAL video upload (input/RezeDance.mp4)
    python tests/test_rls.py --video input/ForestVideo.mp4
    python tests/test_rls.py --skip-video          tables only
    python tests/test_rls.py --skip-tables         video only

It goes: this script -> your FastAPI server -> Supabase -> RLS. Real logins only, nothing is
bypassed, and the server refuses to start with a key that skips RLS. Tests never change a policy.
PASS = RLS did what it should. FAIL = a policy is too loose or too tight.

Env: STEPSYNC_EMAIL / STEPSYNC_PASSWORD        user A
     STEPSYNC_EMAIL_B / STEPSYNC_PASSWORD_B    user B, a second account
     STEPSYNC_API  server address, default http://127.0.0.1:8000
Temporary rows are named rls_matrix_xxxx / rls_video_xxxx and are deleted at the end.
"""
import os
import sys
import time
import uuid

import httpx


class Resp:
    def __init__(self, r):
        self.status = r.status_code
        try:
            self.body = r.json()
        except Exception:
            self.body = {}
        self.rows = self.body.get("rows", []) if isinstance(self.body, dict) else []
        self.count = self.body.get("count", 0) if isinstance(self.body, dict) else 0

    def __str__(self):
        return f"HTTP {self.status}, {self.count} rows"


class Who:
    """One kind of client: a user token, or no token at all for anon."""

    def __init__(self, tc, name, token=None):
        self.tc, self.name = tc, name
        self.h = {"Authorization": f"Bearer {token}"} if token else {}

    def select(self, table, **f):
        return Resp(self.tc.get(f"/tables/{table}", params=f, headers=self.h))

    def insert(self, table, row):
        return Resp(self.tc.post(f"/tables/{table}", json=row, headers=self.h))

    def update(self, table, values, **f):
        return Resp(self.tc.patch(f"/tables/{table}", params=f, json=values, headers=self.h))

    def delete(self, table, **f):
        return Resp(self.tc.delete(f"/tables/{table}", params=f, headers=self.h))


def get_tokens(tc):
    """Real logins through the server, for user A and user B."""
    out = []
    for suffix in ("", "_B"):
        who = "user B" if suffix else "user A"
        for var in ("STEPSYNC_EMAIL", "STEPSYNC_PASSWORD"):
            if not os.environ.get(var + suffix):
                raise SystemExit(f"Set {var}{suffix} first ({who} login).")
        r = tc.post("/auth/login", json={"email": os.environ["STEPSYNC_EMAIL" + suffix],
                                         "password": os.environ["STEPSYNC_PASSWORD" + suffix]})
        if r.status_code != 200:
            raise SystemExit(f"Login failed for {who}: {r.text}")
        out.append((r.json()["access_token"], r.json()["user_id"]))
    if out[0][1] == out[1][1]:
        raise SystemExit("User A and user B are the same account. Make a second user.")
    return out[0], out[1]


def run_matrix(tc):
    results = []

    def expect(table, op, who, what, resp, kind):
        """kind ok = it worked. kind blocked = RLS stopped it (error, or it touched nothing)."""
        if kind == "ok":
            good = resp.status < 300 and resp.count >= 1
        else:
            good = resp.status in (401, 403) or (resp.status < 300 and resp.count == 0)
        results.append((table, op, who.name, what, "PASS" if good else "FAIL", str(resp)))

    def skip(table, op, who, what, why):
        results.append((table, op, who.name, what, "SKIP", why))

    def make(who, table, row):
        r = who.insert(table, row)
        if r.status >= 300 or not r.rows:
            raise SystemExit(f"setup failed, could not create {table}: {r.status} {r.body}")
        return r.rows[0]

    (tok_a, a_id), (tok_b, b_id) = get_tokens(tc)
    A, B, ANON = Who(tc, "A", tok_a), Who(tc, "B", tok_b), Who(tc, "anon")
    tag = uuid.uuid4().hex[:6]
    dA = dB = None
    try:
        # ---------- setup: A owns a private dance, B owns a different one ----------
        dA = make(A, "dances", {"owner_id": a_id, "title": f"rls_matrix_{tag}"})["id"]
        sA = make(A, "steps", {"dance_id": dA, "step_order": 1, "name": "s1",
                               "start_ms": 0, "end_ms": 1000})["id"]
        kA = make(A, "keyframes", {"step_id": sA, "frame_order": 1, "timestamp_ms": 0,
                                   "pose_data": {"landmarks": []}})["id"]
        dB = make(B, "dances", {"owner_id": b_id, "title": f"rls_matrix_{tag}_B"})["id"]
        sB = make(B, "steps", {"dance_id": dB, "step_order": 1, "name": "b1",
                               "start_ms": 0, "end_ms": 1000})["id"]
        orig = A.select("profiles", id=a_id).rows[0].get("first_name")

        # ---------- profiles ----------
        t = "profiles"
        expect(t, "select", A, "A reads own profile", A.select(t, id=a_id), "ok")
        expect(t, "select", A, "A cannot read B's profile", A.select(t, id=b_id), "blocked")
        expect(t, "select", B, "B cannot read A's profile", B.select(t, id=a_id), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        fake = {"id": str(uuid.uuid4()), "username": f"fake_{tag}"}
        expect(t, "insert", A, "A cannot insert a profile (trigger does that)", A.insert(t, fake), "blocked")
        expect(t, "insert", ANON, "anon cannot insert a profile", ANON.insert(t, fake), "blocked")
        expect(t, "update", A, "A updates own profile", A.update(t, {"first_name": f"rls_{tag}"}, id=a_id), "ok")
        expect(t, "update", B, "B cannot update A's profile", B.update(t, {"first_name": "hacked"}, id=a_id), "blocked")
        expect(t, "update", ANON, "anon cannot update a profile", ANON.update(t, {"first_name": "hacked"}, id=a_id), "blocked")
        same = A.select(t, id=a_id).rows[0].get("first_name") == f"rls_{tag}"
        results.append((t, "update", "B", "B's edit really changed nothing", "PASS" if same else "FAIL", "profile unchanged" if same else "profile was changed"))
        A.update(t, {"first_name": orig}, id=a_id)

        # ---------- dances (A's dance is private) ----------
        t = "dances"
        expect(t, "select", A, "A reads own dance", A.select(t, id=dA), "ok")
        expect(t, "select", B, "B cannot read A's private dance", B.select(t, id=dA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        extra = make(A, t, {"owner_id": a_id, "title": f"rls_matrix_{tag}_x"})["id"]
        expect(t, "insert", A, "A inserts own dance", A.select(t, id=extra), "ok")
        expect(t, "insert", A, "A cannot insert a dance owned by B", A.insert(t, {"owner_id": b_id, "title": "spoof"}), "blocked")
        expect(t, "insert", B, "B cannot insert a dance owned by A", B.insert(t, {"owner_id": a_id, "title": "spoof"}), "blocked")
        expect(t, "insert", ANON, "anon cannot insert a dance", ANON.insert(t, {"owner_id": a_id, "title": "x"}), "blocked")
        expect(t, "update", A, "A renames own dance", A.update(t, {"title": f"rls_matrix_{tag}"}, id=dA), "ok")
        expect(t, "update", B, "B cannot rename A's dance", B.update(t, {"title": "hacked"}, id=dA), "blocked")
        expect(t, "update", A, "A cannot hand own dance to B (owner_id)", A.update(t, {"owner_id": b_id}, id=extra), "blocked")
        expect(t, "update", ANON, "anon cannot update a dance", ANON.update(t, {"title": "hacked"}, id=dA), "blocked")
        expect(t, "delete", B, "B cannot delete A's dance", B.delete(t, id=dA), "blocked")
        expect(t, "delete", ANON, "anon cannot delete a dance", ANON.delete(t, id=dA), "blocked")
        expect(t, "delete", A, "A deletes own extra dance", A.delete(t, id=extra), "ok")
        expect(t, "delete", A, "A's dance survived B's and anon's delete tries", A.select(t, id=dA, title=f"rls_matrix_{tag}"), "ok")

        # ---------- steps ----------
        t = "steps"
        expect(t, "select", A, "A reads own step", A.select(t, id=sA), "ok")
        expect(t, "select", B, "B cannot read step of A's private dance", B.select(t, id=sA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        s2 = make(A, t, {"dance_id": dA, "step_order": 2, "start_ms": 0, "end_ms": 5})["id"]
        expect(t, "insert", A, "A adds a step to own dance", A.select(t, id=s2), "ok")
        expect(t, "insert", B, "B cannot add a step to A's dance", B.insert(t, {"dance_id": dA, "step_order": 3, "start_ms": 0, "end_ms": 5}), "blocked")
        expect(t, "insert", B, "B adds a step to B's own dance", B.insert(t, {"dance_id": dB, "step_order": 2, "start_ms": 0, "end_ms": 5}), "ok")
        expect(t, "insert", ANON, "anon cannot add a step", ANON.insert(t, {"dance_id": dA, "step_order": 4, "start_ms": 0, "end_ms": 5}), "blocked")
        expect(t, "update", A, "A renames own step", A.update(t, {"name": "renamed"}, id=sA), "ok")
        expect(t, "update", B, "B cannot rename A's step", B.update(t, {"name": "hacked"}, id=sA), "blocked")
        expect(t, "update", A, "A cannot move own step into B's dance", A.update(t, {"dance_id": dB}, id=s2), "blocked")
        expect(t, "update", ANON, "anon cannot update a step", ANON.update(t, {"name": "hacked"}, id=sA), "blocked")
        expect(t, "delete", B, "B cannot delete A's step", B.delete(t, id=s2), "blocked")
        expect(t, "delete", ANON, "anon cannot delete a step", ANON.delete(t, id=s2), "blocked")
        expect(t, "delete", A, "A deletes own extra step", A.delete(t, id=s2), "ok")

        # ---------- keyframes ----------
        t = "keyframes"
        expect(t, "select", A, "A reads own keyframe", A.select(t, id=kA), "ok")
        expect(t, "select", B, "B cannot read keyframe of A's private dance", B.select(t, id=kA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        k2 = make(A, t, {"step_id": sA, "frame_order": 2, "timestamp_ms": 33})["id"]
        expect(t, "insert", A, "A adds a keyframe to own step", A.select(t, id=k2), "ok")
        expect(t, "insert", B, "B cannot add a keyframe to A's step", B.insert(t, {"step_id": sA, "frame_order": 3, "timestamp_ms": 66}), "blocked")
        expect(t, "insert", ANON, "anon cannot add a keyframe", ANON.insert(t, {"step_id": sA, "frame_order": 4, "timestamp_ms": 99}), "blocked")
        expect(t, "update", A, "A edits own keyframe", A.update(t, {"timestamp_ms": 40}, id=k2), "ok")
        expect(t, "update", B, "B cannot edit A's keyframe", B.update(t, {"timestamp_ms": 1}, id=kA), "blocked")
        expect(t, "update", A, "A cannot move own keyframe into B's step", A.update(t, {"step_id": sB}, id=k2), "blocked")
        expect(t, "update", ANON, "anon cannot update a keyframe", ANON.update(t, {"timestamp_ms": 1}, id=kA), "blocked")
        expect(t, "delete", B, "B cannot delete A's keyframe", B.delete(t, id=kA), "blocked")
        expect(t, "delete", ANON, "anon cannot delete a keyframe", ANON.delete(t, id=kA), "blocked")
        expect(t, "delete", A, "A deletes own extra keyframe", A.delete(t, id=k2), "ok")

        # ---------- practice_sessions ----------
        t = "practice_sessions"
        psA = make(A, t, {"user_id": a_id, "dance_id": dA})["id"]
        expect(t, "insert", A, "A starts a session on own dance", A.select(t, id=psA), "ok")
        expect(t, "insert", B, "B cannot start a session on A's private dance", B.insert(t, {"user_id": b_id, "dance_id": dA}), "blocked")
        expect(t, "insert", B, "B cannot start a session as A", B.insert(t, {"user_id": a_id, "dance_id": dB}), "blocked")
        expect(t, "insert", ANON, "anon cannot start a session", ANON.insert(t, {"user_id": a_id, "dance_id": dA}), "blocked")
        expect(t, "select", A, "A reads own session", A.select(t, id=psA), "ok")
        expect(t, "select", B, "B cannot read A's session", B.select(t, id=psA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        expect(t, "update", A, "A updates own session", A.update(t, {"mode": "test"}, id=psA), "ok")
        expect(t, "update", B, "B cannot update A's session", B.update(t, {"mode": "learn"}, id=psA), "blocked")
        expect(t, "update", ANON, "anon cannot update a session", ANON.update(t, {"mode": "learn"}, id=psA), "blocked")
        expect(t, "update", A, "A cannot move own session onto B's private dance", A.update(t, {"dance_id": dB}, id=psA), "blocked")
        A.update(t, {"dance_id": dA}, id=psA)
        expect(t, "delete", B, "B cannot delete A's session", B.delete(t, id=psA), "blocked")
        expect(t, "delete", ANON, "anon cannot delete a session", ANON.delete(t, id=psA), "blocked")

        # ---------- step_attempts ----------
        t = "step_attempts"
        atA = make(A, t, {"session_id": psA, "step_id": sA, "attempt_number": 1})["id"]
        expect(t, "insert", A, "A logs an attempt on own session", A.select(t, id=atA), "ok")
        expect(t, "insert", B, "B cannot log an attempt on A's session", B.insert(t, {"session_id": psA, "step_id": sA, "attempt_number": 2}), "blocked")
        expect(t, "insert", ANON, "anon cannot log an attempt", ANON.insert(t, {"session_id": psA, "step_id": sA, "attempt_number": 3}), "blocked")
        expect(t, "insert", A, "A cannot log an attempt on B's private step", A.insert(t, {"session_id": psA, "step_id": sB, "attempt_number": 1}), "blocked")
        A.delete(t, session_id=psA, step_id=sB)
        expect(t, "select", A, "A reads own attempt", A.select(t, id=atA), "ok")
        expect(t, "select", B, "B cannot read A's attempt", B.select(t, id=atA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        expect(t, "update", A, "A updates own attempt", A.update(t, {"score": 50}, id=atA), "ok")
        expect(t, "update", B, "B cannot update A's attempt", B.update(t, {"score": 100}, id=atA), "blocked")
        expect(t, "update", ANON, "anon cannot update an attempt", ANON.update(t, {"score": 100}, id=atA), "blocked")
        expect(t, "delete", B, "B cannot delete A's attempt", B.delete(t, id=atA), "blocked")
        expect(t, "delete", ANON, "anon cannot delete an attempt", ANON.delete(t, id=atA), "blocked")

        # ---------- saved_dances ----------
        t = "saved_dances"
        expect(t, "insert", A, "A saves own dance", A.insert(t, {"user_id": a_id, "dance_id": dA}), "ok")
        expect(t, "insert", A, "A cannot save as B", A.insert(t, {"user_id": b_id, "dance_id": dA}), "blocked")
        expect(t, "insert", B, "B cannot save A's private dance", B.insert(t, {"user_id": b_id, "dance_id": dA}), "blocked")
        B.delete(t, user_id=b_id, dance_id=dA)
        expect(t, "insert", ANON, "anon cannot save a dance", ANON.insert(t, {"user_id": a_id, "dance_id": dA}), "blocked")
        expect(t, "select", A, "A reads own saved row", A.select(t, user_id=a_id, dance_id=dA), "ok")
        expect(t, "select", B, "B cannot read A's saved row", B.select(t, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        expect(t, "update", A, "nobody can update saved rows (no policy)", A.update(t, {"created_at": "2000-01-01T00:00:00Z"}, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "delete", B, "B cannot delete A's saved row", B.delete(t, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "delete", ANON, "anon cannot delete a saved row", ANON.delete(t, user_id=a_id, dance_id=dA), "blocked")

        # ---------- user_dance_progress ----------
        t = "user_dance_progress"
        expect(t, "insert", A, "A starts progress on own dance", A.insert(t, {"user_id": a_id, "dance_id": dA}), "ok")
        expect(t, "insert", A, "A cannot create progress as B", A.insert(t, {"user_id": b_id, "dance_id": dA}), "blocked")
        expect(t, "insert", B, "B cannot track progress on A's private dance", B.insert(t, {"user_id": b_id, "dance_id": dA}), "blocked")
        B.delete(t, user_id=b_id, dance_id=dA)
        expect(t, "insert", ANON, "anon cannot create progress", ANON.insert(t, {"user_id": a_id, "dance_id": dA}), "blocked")
        expect(t, "select", A, "A reads own progress", A.select(t, user_id=a_id, dance_id=dA), "ok")
        expect(t, "select", B, "B cannot read A's progress", B.select(t, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")
        expect(t, "update", A, "A updates own progress", A.update(t, {"steps_completed": 1}, user_id=a_id, dance_id=dA), "ok")
        expect(t, "update", B, "B cannot update A's progress", B.update(t, {"steps_completed": 9}, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "update", ANON, "anon cannot update progress", ANON.update(t, {"steps_completed": 9}, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "update", A, "A cannot point own progress at B's private step", A.update(t, {"current_step_id": sB}, user_id=a_id, dance_id=dA), "blocked")
        A.update(t, {"current_step_id": None}, user_id=a_id, dance_id=dA)
        expect(t, "delete", B, "B cannot delete A's progress", B.delete(t, user_id=a_id, dance_id=dA), "blocked")
        expect(t, "delete", ANON, "anon cannot delete progress", ANON.delete(t, user_id=a_id, dance_id=dA), "blocked")

        # ---------- dance_jobs (server only table, no write policies) ----------
        t = "dance_jobs"
        expect(t, "insert", A, "A cannot insert a job", A.insert(t, {"dance_id": dA}), "blocked")
        expect(t, "insert", B, "B cannot insert a job", B.insert(t, {"dance_id": dA}), "blocked")
        expect(t, "insert", ANON, "anon cannot insert a job", ANON.insert(t, {"dance_id": dA}), "blocked")
        jobs = A.select(t, dance_id=dA)
        if jobs.count >= 1:
            expect(t, "select", A, "A reads own dance's job", jobs, "ok")
            expect(t, "select", B, "B cannot read A's job", B.select(t, dance_id=dA), "blocked")
            expect(t, "update", A, "nobody can update jobs (no policy)", A.update(t, {"status": "done"}, dance_id=dA), "blocked")
            expect(t, "delete", A, "nobody can delete jobs (no policy)", A.delete(t, dance_id=dA), "blocked")
        else:
            for who, w in ((A, "A reads own dance's job"), (B, "B cannot read A's job")):
                skip(t, "select", who, w, "no job rows exist, the server creates those")
            expect(t, "update", A, "nobody can update jobs (no policy)", A.update(t, {"status": "done"}, dance_id=dA), "blocked")
            expect(t, "delete", A, "nobody can delete jobs (no policy)", A.delete(t, dance_id=dA), "blocked")
        expect(t, "select", ANON, "anon reads nothing", ANON.select(t), "blocked")

        # ---------- A makes the dance PUBLIC: others can read, still not write ----------
        A.update("dances", {"is_public": True}, id=dA)
        expect("dances", "select", B, "PUBLIC: B reads A's dance", B.select("dances", id=dA), "ok")
        expect("dances", "update", B, "PUBLIC: B still cannot rename it", B.update("dances", {"title": "hacked"}, id=dA), "blocked")
        expect("dances", "delete", B, "PUBLIC: B still cannot delete it", B.delete("dances", id=dA), "blocked")
        expect("steps", "select", B, "PUBLIC: B reads its steps", B.select("steps", id=sA), "ok")
        expect("steps", "insert", B, "PUBLIC: B still cannot add a step", B.insert("steps", {"dance_id": dA, "step_order": 9, "start_ms": 0, "end_ms": 5}), "blocked")
        expect("steps", "update", B, "PUBLIC: B still cannot edit a step", B.update("steps", {"name": "hacked"}, id=sA), "blocked")
        expect("keyframes", "select", B, "PUBLIC: B reads its keyframes", B.select("keyframes", id=kA), "ok")
        expect("keyframes", "insert", B, "PUBLIC: B still cannot add a keyframe", B.insert("keyframes", {"step_id": sA, "frame_order": 9, "timestamp_ms": 9}), "blocked")
        expect("dance_jobs", "select", B, "PUBLIC: B still cannot read jobs", B.select("dance_jobs", dance_id=dA), "blocked")
        psB = make(B, "practice_sessions", {"user_id": b_id, "dance_id": dA})["id"]
        expect("practice_sessions", "insert", B, "PUBLIC: B starts a session", B.select("practice_sessions", id=psB), "ok")
        expect("practice_sessions", "select", A, "PUBLIC: A cannot read B's session", A.select("practice_sessions", id=psB), "blocked")
        expect("practice_sessions", "update", A, "PUBLIC: A cannot update B's session", A.update("practice_sessions", {"mode": "test"}, id=psB), "blocked")
        expect("practice_sessions", "delete", A, "PUBLIC: A cannot delete B's session", A.delete("practice_sessions", id=psB), "blocked")
        make(B, "step_attempts", {"session_id": psB, "step_id": sA, "attempt_number": 1})
        expect("step_attempts", "select", A, "PUBLIC: A cannot read B's attempts", A.select("step_attempts", session_id=psB), "blocked")
        expect("saved_dances", "insert", B, "PUBLIC: B saves the dance", B.insert("saved_dances", {"user_id": b_id, "dance_id": dA}), "ok")
        expect("saved_dances", "select", A, "PUBLIC: A cannot read B's saved row", A.select("saved_dances", user_id=b_id), "blocked")
        expect("user_dance_progress", "insert", B, "PUBLIC: B tracks progress", B.insert("user_dance_progress", {"user_id": b_id, "dance_id": dA}), "ok")
        expect("user_dance_progress", "select", A, "PUBLIC: A cannot read B's progress", A.select("user_dance_progress", user_id=b_id), "blocked")

        # ---------- private again ----------
        A.update("dances", {"is_public": False}, id=dA)
        expect("dances", "select", B, "PRIVATE AGAIN: B loses the dance", B.select("dances", id=dA), "blocked")
        expect("steps", "select", B, "PRIVATE AGAIN: B loses the steps", B.select("steps", id=sA), "blocked")
        expect("keyframes", "select", B, "PRIVATE AGAIN: B loses the keyframes", B.select("keyframes", id=kA), "blocked")

        # ---------- deletes by the owner, and cascade ----------
        expect("practice_sessions", "delete", A, "A deletes own session", A.delete("practice_sessions", id=psA), "ok")
        expect("saved_dances", "delete", A, "A deletes own saved row", A.delete("saved_dances", user_id=a_id, dance_id=dA), "ok")
        expect("user_dance_progress", "delete", A, "A deletes own progress", A.delete("user_dance_progress", user_id=a_id, dance_id=dA), "ok")
        expect("dances", "delete", A, "A deletes own dance", A.delete("dances", id=dA), "ok")
        expect("steps", "delete", A, "cascade: A's steps went with the dance", A.select("steps", dance_id=dA), "blocked")
        expect("keyframes", "delete", A, "cascade: A's keyframes went too", A.select("keyframes", step_id=sA), "blocked")
        dA = None

        # ---------- profile delete last, in case a bad policy lets it through ----------
        t = "profiles"
        expect(t, "delete", A, "A cannot delete own profile (no policy)", A.delete(t, id=a_id), "blocked")
        expect(t, "delete", B, "B cannot delete A's profile", B.delete(t, id=a_id), "blocked")
        expect(t, "delete", ANON, "anon cannot delete a profile", ANON.delete(t, id=a_id), "blocked")
    finally:
        for who, did in ((A, dA), (B, dB)):
            if did:
                try:
                    who.delete("dances", id=did)
                except Exception:
                    pass
    return results


def print_table(results):
    order = ["profiles", "dances", "steps", "keyframes", "practice_sessions", "step_attempts",
             "saved_dances", "user_dance_progress", "dance_jobs"]
    for table in order:
        rows = [r for r in results if r[0] == table]
        print(f"\n== {table}  ({sum(1 for r in rows if r[4] == 'PASS')}/{len(rows)} pass)")
        for _, op, who, what, status, got in rows:
            print(f"  {status:4}  {op:6}  {who:4}  {what}" + ("" if status == "PASS" else f"   [{got}]"))
    total = {s: sum(1 for r in results if r[4] == s) for s in ("PASS", "FAIL", "SKIP")}
    print(f"\n{total['PASS']} passed, {total['FAIL']} failed, {total['SKIP']} skipped")
    return total["FAIL"]


def connect():
    base = os.environ.get("STEPSYNC_API", "http://127.0.0.1:8000")
    tc = httpx.Client(base_url=base, timeout=60)
    try:
        tc.get("/docs")
    except httpx.HTTPError:
        raise SystemExit(f"Cannot reach the server at {base}. Start it first in another Terminal "
                         f"window:  uvicorn app.main:app --reload")
    print(f"Testing the real server at {base}, logging in as two real users plus anon.")
    return tc



def run_video(video):
    if not os.path.exists(video):
        raise SystemExit(f"Video not found: {video}")
    tc = connect()
    (tok_a, a_id), (tok_b, b_id) = get_tokens(tc)
    A, B, ANON = Who(tc, "A", tok_a), Who(tc, "B", tok_b), Who(tc, "anon")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    def read(who, dance_id):
        return tc.get(f"/dances/{dance_id}", headers=who.h)

    def count(r):
        return r.count

    dance_id = None
    try:
        # ---- A uploads a real video, the server extracts poses and saves it
        print(f"Uploading {video} as user A, this runs the pose extraction, give it a minute...")
        with open(video, "rb") as f:
            r = tc.post("/dances/import", data={"title": f"rls_video_{uuid.uuid4().hex[:6]}"},
                        files={"file": (os.path.basename(video), f, "video/mp4")},
                        headers=A.h, timeout=900)
        check("A uploads the video and it is saved", r.status_code == 200, f"HTTP {r.status_code} {r.text[:150] if r.status_code != 200 else ''}")
        if r.status_code != 200:
            return results
        info = r.json()
        dance_id = info["dance_id"]
        n = info["frames"]
        check("every frame became a keyframe",
              n > 0 and info["keyframes"] == n
              and info["ok_frames"] + info["low_confidence_frames"] + info["no_pose_frames"] == n,
              f"{n} frames: {info['ok_frames']} OK, {info['low_confidence_frames']} low confidence, {info['no_pose_frames']} no pose")

        # ---- A reads it all back out of Supabase
        ra = read(A, dance_id)
        check("A reads the dance back", ra.status_code == 200)
        body = ra.json() if ra.status_code == 200 else {"steps": [], "keyframe_count": 0}
        kfs = body["steps"][0]["keyframes"] if body["steps"] else []
        check("A gets back every keyframe, none lost to the 1000 row read limit",
              body["keyframe_count"] == n and len(kfs) == n, f"{len(kfs)} of {n}")
        check("keyframes come back in order with rising timestamps",
              [k["frame_order"] for k in kfs] == list(range(1, n + 1))
              and all(kfs[i]["timestamp_ms"] < kfs[i + 1]["timestamp_ms"] for i in range(len(kfs) - 1)))
        check("each keyframe holds all 33 body landmarks",
              all(len(k["pose_data"]["landmarks"]) == 33 for k in kfs))
        step_id = body["steps"][0]["id"] if body["steps"] else None
        first_kf = kfs[0]["id"] if kfs else None

        # ---- B (another account) and anon, while the dance is private
        check("B cannot read A's private dance", read(B, dance_id).status_code == 404)
        check("anon cannot read A's private dance", read(ANON, dance_id).status_code == 404)
        check("B sees none of its steps or keyframes",
              B.select("steps", dance_id=dance_id).count == 0 and B.select("keyframes", step_id=step_id).count == 0)
        check("anon sees none of its steps or keyframes",
              ANON.select("steps", dance_id=dance_id).count == 0 and ANON.select("keyframes", step_id=step_id).count == 0)
        check("B cannot change a keyframe", B.update("keyframes", {"tolerance": 9}, id=first_kf).count == 0)
        check("B cannot delete the dance", B.delete("dances", id=dance_id).count == 0)
        check("B cannot add a keyframe to it",
              B.insert("keyframes", {"step_id": step_id, "frame_order": n + 1, "timestamp_ms": 1}).status in (401, 403))
        check("anon cannot upload a video", tc.post("/dances/import", data={"title": "x"},
              files={"file": ("x.mp4", b"x", "video/mp4")}).status_code == 401)
        check("A's data survived all of that", read(A, dance_id).json()["keyframe_count"] == n)

        # ---- A makes it public: B can read, still cannot write
        A.update("dances", {"is_public": True}, id=dance_id)
        rb = read(B, dance_id)
        check("PUBLIC: B reads the whole dance, every keyframe", rb.status_code == 200 and rb.json()["keyframe_count"] == n)
        check("PUBLIC: anon still reads nothing", read(ANON, dance_id).status_code == 404)
        check("PUBLIC: B still cannot change a keyframe", B.update("keyframes", {"tolerance": 9}, id=first_kf).count == 0)
        check("PUBLIC: B still cannot delete the dance", B.delete("dances", id=dance_id).count == 0)
        check("PUBLIC: B still cannot add a keyframe",
              B.insert("keyframes", {"step_id": step_id, "frame_order": n + 1, "timestamp_ms": 1}).status in (401, 403))

        # ---- private again
        A.update("dances", {"is_public": False}, id=dance_id)
        check("PRIVATE AGAIN: B loses it", read(B, dance_id).status_code == 404)

        # ---- A deletes it, everything under it goes
        check("A deletes the dance", A.delete("dances", id=dance_id).count == 1)
        check("cascade: dance, steps and keyframes are gone",
              read(A, dance_id).status_code == 404 and A.select("steps", dance_id=dance_id).count == 0
              and A.select("keyframes", step_id=step_id).count == 0)
        dance_id = None
    finally:
        if dance_id:
            A.delete("dances", id=dance_id)
    return results



def print_video(results):
    print("\n== real video")
    for name, ok, detail in results:
        print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return len(failed)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--video", default="input/RezeDance.mp4")
    p.add_argument("--skip-video", action="store_true")
    p.add_argument("--skip-tables", action="store_true")
    a = p.parse_args()
    bad = 0
    if not a.skip_tables:
        bad += print_table(run_matrix(connect()))
    if not a.skip_video:
        bad += print_video(run_video(a.video))
    sys.exit(1 if bad else 0)
