import httpx

from app.services.learning import (
    apply_xp,
    compute_level,
    compute_streak_transition,
    normalize_topic_ids,
    streak_achievements,
)
from app.services.study import compute_vocabulary_summary


# ── Pure helpers ──────────────────────────────────────────────────────

def test_compute_level_and_apply_xp():
    assert compute_level(0) == 1
    assert compute_level(199) == 1
    assert compute_level(200) == 2
    assert apply_xp(180, 1, 50) == {"newXp": 230, "newLevel": 2, "leveledUp": True}
    assert apply_xp(10, 1, 20) == {"newXp": 30, "newLevel": 1, "leveledUp": False}


def test_normalize_topic_ids_handles_str_and_list():
    assert normalize_topic_ids('["a","b"]') == ["a", "b"]
    assert normalize_topic_ids(["a", 1, "b"]) == ["a", "b"]
    assert normalize_topic_ids(None) == []
    assert normalize_topic_ids("not json") == []


def test_streak_continues_on_consecutive_day():
    row = {"current_streak": 4, "longest_streak": 4, "last_practice_date": "2026-06-11",
           "streak_start_date": "2026-06-08", "weekly_activity": ["2026-06-11"], "total_practice_days": 4}
    t = compute_streak_transition(row, "2026-06-12")
    assert t["isNewDay"] is True
    assert t["current_streak"] == 5
    assert t["longest_streak"] == 5
    assert "2026-06-12" in t["weekly_activity"]


def test_streak_breaks_after_gap():
    row = {"current_streak": 9, "longest_streak": 9, "last_practice_date": "2026-06-01",
           "streak_start_date": "2026-05-24", "weekly_activity": [], "total_practice_days": 9}
    t = compute_streak_transition(row, "2026-06-12")
    assert t["current_streak"] == 1
    assert t["longest_streak"] == 9  # longest preserved
    assert t["streak_start_date"] == "2026-06-12"


def test_streak_same_day_is_noop():
    row = {"current_streak": 3, "longest_streak": 3, "last_practice_date": "2026-06-12",
           "streak_start_date": "2026-06-10", "weekly_activity": ["2026-06-12"], "total_practice_days": 3}
    t = compute_streak_transition(row, "2026-06-12")
    assert t["isNewDay"] is False
    assert t["current_streak"] == 3


def test_weekly_activity_capped_at_7():
    row = {"current_streak": 1, "longest_streak": 1, "last_practice_date": "2026-06-10",
           "weekly_activity": [f"2026-06-{d:02d}" for d in range(1, 11)], "total_practice_days": 1}
    t = compute_streak_transition(row, "2026-06-12")
    assert len(t["weekly_activity"]) == 7
    assert "2026-06-12" in t["weekly_activity"]


def test_streak_achievements_thresholds():
    assert streak_achievements(7, []) == ["streak_3", "streak_7"]
    assert streak_achievements(7, ["streak_3"]) == ["streak_7"]
    assert streak_achievements(2, []) == []


def test_vocabulary_summary():
    words = [
        {"mastery_level": 0, "last_reviewed_at": None},
        {"mastery_level": 3, "last_reviewed_at": "2020-01-01T00:00:00Z"},
        {"mastery_level": 5, "last_reviewed_at": "2020-01-01T00:00:00Z"},
    ]
    summary = compute_vocabulary_summary(words)
    assert summary["total"] == 3
    assert summary["learning"] == 1
    assert summary["mastered"] == 1
    assert summary["dueForReview"] == 2  # level 0 (never) + level 3 (old)


# ── Endpoint smoke tests (Supabase mocked) ────────────────────────────

def supabase_handler(tables: dict[str, list[dict]], captured: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if captured is not None and request.method in ("POST", "PATCH"):
            captured.append({"method": request.method, "path": path,
                             "body": request.content.decode() if request.content else ""})
        for table, rows in tables.items():
            if path.endswith(f"/rest/v1/{table}"):
                if request.method == "POST":
                    return httpx.Response(201, json=[{"id": 99, **(rows[0] if rows else {})}])
                if request.method == "PATCH":
                    return httpx.Response(204)
                return httpx.Response(200, json=rows)
        return httpx.Response(200, json=[])

    return handler


def test_completed_topic_ids_endpoint(client, auth_headers, mock_transport):
    rows = [{"id": 1, "lesson_id": "beginner-01", "status": "in_progress",
             "completed_topic_ids": ["t1", "t2"]}]
    mock_transport(supabase_handler({"lesson_progress": rows}))
    res = client.get("/api/users/me/lessons/beginner-01/topics", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"topicIds": ["t1", "t2"]}


def test_in_progress_lessons_endpoint(client, auth_headers, mock_transport):
    rows = [
        {"lesson_id": "a", "completed_topic_ids": ["t1"]},
        {"lesson_id": "b", "completed_topic_ids": []},
    ]
    mock_transport(supabase_handler({"lesson_progress": rows}))
    res = client.get("/api/users/me/in-progress-lessons", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"lessons": {"a": 1}}


def test_save_topic_inserts_when_missing(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(supabase_handler({"lesson_progress": []}, captured))
    res = client.post(
        "/api/users/me/lessons/beginner-01/topics",
        json={"topicId": "t9"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert any(c["method"] == "POST" for c in captured)


def test_complete_lesson_endpoint(client, auth_headers, mock_transport):
    captured: list = []
    existing = [{"id": 5, "lesson_id": "beginner-01", "status": "in_progress",
                 "completed_topic_ids": ["t1"], "time_spent_seconds": 100, "best_rating": 3}]
    mock_transport(supabase_handler({"lesson_progress": existing}, captured))
    res = client.post(
        "/api/users/me/lessons/beginner-01/complete",
        json={"topicsCompleted": 5, "timeSpentSeconds": 60, "rating": 5, "sessionId": "s1"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"success": True}
    patch = next(c for c in captured if c["method"] == "PATCH")
    body = patch["body"].replace(" ", "")
    assert '"status":"completed"' in body
    assert '"score":100' in body


def test_award_xp_endpoint(client, auth_headers, mock_transport):
    mock_transport(supabase_handler({"profiles": [{"id": "u", "xp": 180, "level": 1}]}))
    res = client.post("/api/users/me/xp", json={"amount": 50}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"newXp": 230, "newLevel": 2, "leveledUp": True}


def test_record_practice_endpoint(client, auth_headers, mock_transport):
    streak_row = [{"user_id": "u", "current_streak": 2, "longest_streak": 2,
                   "last_practice_date": None, "weekly_activity": [], "total_practice_days": 0}]
    mock_transport(supabase_handler({"user_streaks": streak_row, "user_achievements": []}))
    res = client.post(
        "/api/users/me/practice",
        json={"timeSeconds": 120, "lessonCompleted": True},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["isNewDay"] is True
    assert body["streak"] == 1


def test_vocabulary_summary_endpoint(client, auth_headers, mock_transport):
    words = [{"mastery_level": 5, "last_reviewed_at": "2020-01-01T00:00:00Z"},
             {"mastery_level": 2, "last_reviewed_at": None}]
    mock_transport(supabase_handler({"user_vocabulary": words}))
    res = client.get("/api/users/me/vocabulary/summary", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"total": 2, "learning": 1, "mastered": 1, "dueForReview": 1}


def test_speaking_classes_content_endpoint(client, auth_headers, mock_transport):
    mock_transport(supabase_handler({"speaking_classes": [{"id": 1, "is_published": True}]}))
    res = client.get("/api/content/speaking-classes?level=beginner", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == [{"id": 1, "is_published": True}]


def test_learning_endpoints_require_auth(client):
    assert client.get("/api/users/me/achievements").status_code == 401
    assert client.post("/api/users/me/xp", json={"amount": 10}).status_code == 401
