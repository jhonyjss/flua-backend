"""The app's progress routes: payload validation against the content manifest, the call into
finish_app_session, and the summary. The rules inside the SQL function are checked against a real
Postgres (see the migration); here the database answers are faked at the HTTP boundary."""
import json
from datetime import date

import httpx
import pytest

from app.services import app_progress

TODAY = date(2026, 10, 15)
USER = "00000000-0000-0000-0000-000000000001"
SESSION = "5f0c2b1e-8d7a-4c3b-9e21-0a1b2c3d4e5f"
LESSON_1 = [f"fund-u1-l1-e{n}" for n in range(1, 9)]
LESSON_1_CONCEPTS = ["c-hello", "c-goodbye", "c-i-am", "c-my-name-is", "c-whats-your-name"]

STORED = {
    "xpAwarded": 20, "firstTryCorrect": 7, "mainTotal": 8, "passed": None,
    "unlockedActivityId": "fund-u1-l2", "newAchievementIds": ["first_lesson"], "streakIncremented": True,
}


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(app_progress, "sao_paulo_day", lambda now=None: TODAY)


def _db(*, profile=None, ledger=(), streak=None, achievements=(), due=(), done=(), rpc=None, calls=None):
    log = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if path.endswith("/rpc/finish_app_session"):
            log.append(("rpc", json.loads(request.content)))
            return rpc(request) if callable(rpc) else httpx.Response(200, json=rpc)
        log.append((path.rsplit("/", 1)[-1], params))
        if path.endswith("/profiles"):
            return httpx.Response(200, json=[] if profile is None else [profile])
        if path.endswith("/xp_ledger"):
            return httpx.Response(200, json=[{"amount": a} for a in ledger])
        if path.endswith("/user_streaks"):
            return httpx.Response(200, json=[] if streak is None else [streak])
        if path.endswith("/user_achievements"):
            return httpx.Response(200, json=[{"achievement_id": a, "unlocked_at": "2026-10-14T12:00:00Z"} for a in achievements])
        if path.endswith("/concept_reviews"):
            return httpx.Response(200, json=list(due))
        if path.endswith("/track_completions"):
            return httpx.Response(200, json=[{"activity_id": a} for a in done])
        return httpx.Response(200, json=[])

    return handler


PROFILE = {"id": USER, "full_name": "Jhony", "daily_goal_xp": 40, "motivation": None, "xp": 120}


def _lesson(**patch):
    body = {
        "client": "app",
        "contentVersion": "0.2.0",
        "activityId": "fund-u1-l1",
        "kind": "lesson",
        "completedAt": "2026-10-15T10:00:00-03:00",
        "origin": "normal",
        # e1 wrong first, then right: precision counts the first answer only (7 of 8).
        "attempts": [{"exerciseId": "fund-u1-l1-e1", "conceptId": "c-hello", "correct": False}]
        + [{"exerciseId": e, "conceptId": "c-x", "correct": True} for e in LESSON_1],
    }
    return {**body, **patch}


def _put(client, auth_headers, body, session=SESSION):
    return client.put(f"/api/users/me/sessions/{session}/result", json=body, headers=auth_headers)


# ── Summary ───────────────────────────────────────────────────────────────────


def test_summary_is_the_account_progress_on_the_sao_paulo_day(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(
        profile=PROFILE,
        ledger=[20, 5],
        streak={"current_streak": 3, "longest_streak": 5, "last_practice_date": "2026-10-14"},
        achievements=["first_lesson", "streak_3"],
        due=[{"concept_id": "c-hello"}, {"concept_id": "c-i-am"}],
        done=["fund-u1-l1", "fund-u1-l2"],
        calls=calls,
    ))
    res = client.get("/api/users/me/summary", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {
        "profile": {"fullName": "Jhony", "dailyGoalXp": 40, "motivation": "daily"},
        "xp": {"total": 120, "today": 25},
        "streak": {"current": 3, "longest": 5, "lastPracticeDay": "2026-10-14"},
        "achievements": [
            {"id": "first_lesson", "unlockedAt": "2026-10-14T12:00:00Z"},
            {"id": "streak_3", "unlockedAt": "2026-10-14T12:00:00Z"},
        ],
        "reviewsDue": 2,
        "tracks": {"fundamentals": {"completedActivityIds": ["fund-u1-l1", "fund-u1-l2"], "currentActivityId": "fund-u1-l3"}},
        "serverDay": "2026-10-15",
    }
    queried = dict(calls)
    assert queried["xp_ledger"]["local_day"] == "eq.2026-10-15"
    assert queried["concept_reviews"]["due_day"] == "lte.2026-10-15"


def test_summary_shows_zero_streak_after_a_missed_day_and_keeps_the_record(client, auth_headers, mock_transport):
    mock_transport(_db(profile=PROFILE, streak={"current_streak": 4, "longest_streak": 9, "last_practice_date": "2026-10-13"}))
    streak = client.get("/api/users/me/summary", headers=auth_headers).json()["streak"]
    assert streak == {"current": 0, "longest": 9, "lastPracticeDay": "2026-10-13"}


def test_summary_of_a_new_account_starts_at_the_first_lesson(client, auth_headers, mock_transport):
    mock_transport(_db(profile={"id": USER, "full_name": None, "xp": None}))
    body = client.get("/api/users/me/summary", headers=auth_headers).json()
    assert body["xp"] == {"total": 0, "today": 0}
    assert body["streak"] == {"current": 0, "longest": 0, "lastPracticeDay": None}
    assert body["tracks"]["fundamentals"] == {"completedActivityIds": [], "currentActivityId": "fund-u1-l1"}


def test_summary_needs_a_session(client):
    assert client.get("/api/users/me/summary").status_code == 401


# ── Finishing a session ───────────────────────────────────────────────────────


def test_lesson_goes_to_the_core_with_precision_order_and_concepts(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(profile=PROFILE, done=["fund-u1-l1"], rpc={"replayed": False, "result": STORED}, calls=calls))
    res = _put(client, auth_headers, _lesson())
    assert res.status_code == 200
    body = res.json()
    assert body["replayed"] is False
    assert body["result"] == STORED
    assert body["summary"]["tracks"]["fundamentals"]["currentActivityId"] == "fund-u1-l2"
    sent = next(payload for kind, payload in calls if kind == "rpc")
    assert sent["p_user_id"] == USER
    assert sent["p_session_id"] == SESSION
    assert sent["p_kind"] == "lesson"
    assert sent["p_first_try_correct"] == 7
    assert sent["p_main_total"] == 8
    assert sent["p_concepts"] == LESSON_1_CONCEPTS
    assert sent["p_order"][:3] == ["fund-u1-l1", "fund-u1-l2", "fund-u1-l3"]
    assert len(sent["p_order"]) == 30
    assert sent["p_kinds"].count("checkpoint") == 6


def test_a_resend_reports_replayed(client, auth_headers, mock_transport):
    mock_transport(_db(profile=PROFILE, rpc={"replayed": True, "result": STORED}))
    assert _put(client, auth_headers, _lesson()).json()["replayed"] is True


def test_voice_lesson_counts_one_attempt_per_concept(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(profile=PROFILE, rpc={"replayed": False, "result": STORED}, calls=calls))
    attempts = [
        {"exerciseId": f"voice:{c}", "conceptId": c, "correct": c != "c-goodbye"} for c in LESSON_1_CONCEPTS
    ]
    assert _put(client, auth_headers, _lesson(kind="voice_lesson", attempts=attempts)).status_code == 200
    sent = next(payload for kind, payload in calls if kind == "rpc")
    assert sent["p_first_try_correct"] == 4
    assert sent["p_main_total"] == 5


def test_voice_lesson_missing_a_concept_is_refused_before_the_core(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(profile=PROFILE, calls=calls))
    attempts = [{"exerciseId": f"voice:{c}", "conceptId": c, "correct": True} for c in LESSON_1_CONCEPTS[1:]]
    res = _put(client, auth_headers, _lesson(kind="voice_lesson", attempts=attempts))
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_attempts"
    assert "rpc" not in [kind for kind, _ in calls]


def test_unknown_content_version_is_refused_for_good(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(profile=PROFILE, calls=calls))
    res = _put(client, auth_headers, _lesson(contentVersion="0.1.0"))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "content_version"
    assert calls == []


def test_activity_of_another_kind_or_skipped_exercises_is_refused(client, auth_headers, mock_transport):
    mock_transport(_db(profile=PROFILE))
    assert _put(client, auth_headers, _lesson(activityId="fund-u1-cp")).status_code == 422
    assert _put(client, auth_headers, _lesson(attempts=_lesson()["attempts"][:5])).status_code == 422
    assert _put(client, auth_headers, _lesson(activityId="fund-u9-l1")).status_code == 422


def test_review_needs_attempts(client, auth_headers, mock_transport):
    mock_transport(_db(profile=PROFILE))
    assert _put(client, auth_headers, _lesson(activityId="review", kind="review", attempts=[])).status_code == 422


def test_locked_activity_from_the_core_becomes_409(client, auth_headers, mock_transport):
    def locked(request):
        return httpx.Response(400, json={"code": "P0001", "message": "activity_locked"})

    mock_transport(_db(profile=PROFILE, rpc=locked))
    res = _put(client, auth_headers, _lesson(activityId="fund-u1-l2", attempts=[
        {"exerciseId": f"fund-u1-l2-e{n}", "conceptId": "c-x", "correct": True} for n in range(1, 9)
    ]))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "activity_locked"


def test_session_id_must_look_like_an_id(client, auth_headers, mock_transport):
    mock_transport(_db(profile=PROFILE))
    assert _put(client, auth_headers, _lesson(), session="x").status_code == 422


def test_finishing_needs_a_session(client):
    assert client.put(f"/api/users/me/sessions/{SESSION}/result", json=_lesson()).status_code == 401


# ── Due concepts ──────────────────────────────────────────────────────────────


def test_due_concepts_most_overdue_first(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(due=[
        {"concept_id": "c-hello", "due_day": "2026-10-12", "stage": 0},
        {"concept_id": "c-i-am", "due_day": "2026-10-15", "stage": 2},
    ], calls=calls))
    res = client.get("/api/users/me/concepts/due?limit=3", headers=auth_headers)
    assert res.json() == [
        {"conceptId": "c-hello", "dueDay": "2026-10-12", "stage": 0},
        {"conceptId": "c-i-am", "dueDay": "2026-10-15", "stage": 2},
    ]
    queried = dict(calls)["concept_reviews"]
    assert queried["due_day"] == "lte.2026-10-15"
    assert queried["order"] == "due_day.asc"
    assert queried["limit"] == "3"


# ── Profile: goal and motivation ──────────────────────────────────────────────


def test_profile_takes_the_daily_goal_and_motivation(client, auth_headers, mock_transport):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            sent.append(json.loads(request.content))
            return httpx.Response(204)
        return httpx.Response(200, json=[{**PROFILE, "daily_goal_xp": 60, "motivation": "travel"}])

    mock_transport(handler)
    res = client.patch("/api/users/me/profile", json={"dailyGoalXp": 60, "motivation": "travel"}, headers=auth_headers)
    assert sent == [{"daily_goal_xp": 60, "motivation": "travel"}]
    assert res.json()["dailyGoalXp"] == 60
    assert res.json()["motivation"] == "travel"
    assert client.patch("/api/users/me/profile", json={"dailyGoalXp": 30}, headers=auth_headers).status_code == 422
