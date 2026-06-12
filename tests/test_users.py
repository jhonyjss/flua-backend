import json

import httpx

from app.schemas.users import UpdateProfileRequest
from app.services.user_data import build_profile_update, compute_dashboard_stats, map_subscription

USER_ID = "00000000-0000-0000-0000-000000000001"

PROFILE_ROW = {
    "id": USER_ID,
    "full_name": "Jhony Souza",
    "avatar_url": None,
    "created_at": "2025-03-01T00:00:00Z",
    "xp": 1490,
    "level": 3,
    "english_level": "beginner",
    "explanation_language": "pt",
    "target_language": "en",
    "learning_goals": ["travel", "work"],
}


def make_supabase_handler(tables: dict[str, list[dict]], captured: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for table, rows in tables.items():
            if path.endswith(f"/rest/v1/{table}"):
                if request.method == "PATCH" and captured is not None:
                    captured["patch"] = json.loads(request.content)
                    return httpx.Response(204)
                return httpx.Response(200, json=rows)
        raise AssertionError(f"unexpected table call: {path}")

    return handler


# ── Pure aggregation ──────────────────────────────────────────────────

def test_compute_dashboard_stats_aggregates():
    progress = [
        {"status": "completed"}, {"status": "completed"}, {"status": "in_progress"},
    ]
    sessions = [
        {"id": 1, "elapsed_seconds": 600, "goals_completed": 3, "rating": 5, "started_at": "2026-06-01"},
        {"id": 2, "elapsed_seconds": 300, "goals_completed": 2, "rating": 4, "started_at": "2026-06-02"},
    ]
    stats = compute_dashboard_stats(PROFILE_ROW, progress, sessions)
    assert stats.xp == 1490
    assert stats.lessonsCompleted == 2
    assert stats.lessonsInProgress == 1
    assert stats.totalTimeMinutes == 15
    assert stats.totalSessions == 2
    assert stats.totalGoalsCompleted == 5
    assert stats.averageRating == 4.5
    assert len(stats.recentSessions) == 2


def test_compute_dashboard_stats_empty():
    stats = compute_dashboard_stats(None, [], [])
    assert stats.xp == 0
    assert stats.level == 1
    assert stats.averageRating == 0
    assert stats.recentSessions == []


def test_build_profile_update_maps_camel_to_snake():
    values = build_profile_update(UpdateProfileRequest(
        fullName="  Ana  ", explanationLanguage="en", targetLanguage="es", learningGoals=["exams"],
    ))
    assert values == {
        "full_name": "Ana",
        "explanation_language": "en",
        "target_language": "es",
        "learning_goals": ["exams"],
    }


def test_build_profile_update_partial():
    assert build_profile_update(UpdateProfileRequest()) == {}
    assert build_profile_update(UpdateProfileRequest(fullName="")) == {"full_name": None}


def test_map_subscription_active_and_empty():
    sub = map_subscription({"status": "active", "plan_level": "starter", "cancel_at_period_end": False})
    assert sub.isSubscribed is True
    assert sub.planLevel == "starter"
    assert map_subscription(None).isSubscribed is False
    assert map_subscription({"status": "canceled"}).isSubscribed is False


# ── Endpoints ─────────────────────────────────────────────────────────

def test_profile_endpoint_maps_fields(client, auth_headers, mock_transport):
    mock_transport(make_supabase_handler({"profiles": [PROFILE_ROW]}))
    res = client.get("/api/users/me/profile", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["fullName"] == "Jhony Souza"
    assert data["learningGoals"] == ["travel", "work"]
    assert data["targetLanguage"] == "en"


def test_profile_endpoint_requires_auth(client):
    assert client.get("/api/users/me/profile").status_code == 401


def test_patch_profile_updates_and_returns(client, auth_headers, mock_transport):
    captured: dict = {}
    mock_transport(make_supabase_handler({"profiles": [PROFILE_ROW]}, captured))
    res = client.patch(
        "/api/users/me/profile",
        json={"fullName": "Novo Nome", "learningGoals": ["travel"]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert captured["patch"] == {"full_name": "Novo Nome", "learning_goals": ["travel"]}


def test_completed_lessons_endpoint(client, auth_headers, mock_transport):
    rows = [{"lesson_id": "beginner-01"}, {"lesson_id": "beginner-02"}, {"lesson_id": None}]
    mock_transport(make_supabase_handler({"lesson_progress": rows}))
    res = client.get("/api/users/me/completed-lessons", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"lessonIds": ["beginner-01", "beginner-02"]}


def test_streak_endpoint_defaults_when_missing(client, auth_headers, mock_transport):
    mock_transport(make_supabase_handler({"user_streaks": []}))
    res = client.get("/api/users/me/streak", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["current_streak"] == 0


def test_subscription_endpoint(client, auth_headers, mock_transport):
    rows = [{"status": "active", "plan_level": "starter", "plan_name": "Starter_monthly",
             "cancel_at_period_end": False, "current_period_end": "2026-07-08T00:00:00Z"}]
    mock_transport(make_supabase_handler({"stripe_subscriptions": rows}))
    res = client.get("/api/users/me/subscription", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["isSubscribed"] is True
    assert data["planLevel"] == "starter"


def test_sessions_endpoint_respects_limit_param(client, auth_headers, mock_transport):
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return httpx.Response(200, json=[])

    mock_transport(handler)
    res = client.get("/api/users/me/sessions?limit=3", headers=auth_headers)
    assert res.status_code == 200
    assert "limit=3" in captured_urls[0]
