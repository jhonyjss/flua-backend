"""POST /api/realtime/session-metrics — one row of counters per voice session (Flua stage 2b)."""
import json

import httpx
import pytest

USER_ID = "00000000-0000-0000-0000-000000000001"  # make_token's default subject
SESSION_ID = "3f2b8c1e-9a4d-4e7b-8c2a-1d5e6f7a8b9c"

# A finished web lesson, every field filled.
LESSON_BODY = {
    "sessionId": SESSION_ID,
    "client": "web",
    "mode": "lesson",
    "language": "en",
    "level": "beginner",
    "model": "gpt-realtime-2.1-mini",
    "promptVersion": "deployment-01ABC",
    "lessonId": "beginner-01",
    "durationSeconds": 612,
    "learnerTurns": 14,
    "fluaTurns": 17,
    "fluaWords": 820,
    "fluaWordsMax": 61,
    "openingWords": 48,
    "openingSeconds": 9.5,
    "outcomes": {"correto": 6, "parcial": 3, "incorreto": 1, "fora_do_roteiro": 2},
    "goalsReached": 4,
    "goalsAfterMisses": 1,
    "skippedTurns": {"too_short": 3, "ghost": 1},
    "silenceNudges": 2,
    "unreadableEvaluations": 0,
    "reconnects": 1,
    "endedBy": "learner",
}


def recording_supabase(captured: list):
    """PostgREST stand-in: records each write and answers like a successful insert."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.append({
                "path": request.url.path,
                "on_conflict": request.url.params.get("on_conflict"),
                "prefer": request.headers.get("prefer"),
                "row": json.loads(request.content),
            })
            return httpx.Response(201, json=[{"id": 1}])
        return httpx.Response(200, json=[])

    return handler


def test_metrics_insert_one_snake_case_row_for_the_user(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json=LESSON_BODY, headers=auth_headers)

    assert res.status_code == 201
    assert res.json() == {"success": True}
    assert captured == [{
        "path": "/rest/v1/voice_session_metrics",
        # The same session sent again keeps its first row.
        "on_conflict": "session_id",
        "prefer": "resolution=ignore-duplicates,return=representation",
        "row": {
            "user_id": USER_ID,
            "session_id": SESSION_ID,
            "client": "web",
            "mode": "lesson",
            "language": "en",
            "level": "beginner",
            "model": "gpt-realtime-2.1-mini",
            "prompt_version": "deployment-01ABC",
            "lesson_id": "beginner-01",
            "duration_seconds": 612,
            "learner_turns": 14,
            "flua_turns": 17,
            "flua_words": 820,
            "flua_words_max": 61,
            "opening_words": 48,
            "opening_seconds": 9.5,
            "outcome_correto": 6,
            "outcome_parcial": 3,
            "outcome_incorreto": 1,
            "outcome_fora_do_roteiro": 2,
            "goals_reached": 4,
            "goals_after_misses": 1,
            "skipped_turns": {"too_short": 3, "ghost": 1},
            "silence_nudges": 2,
            "unreadable_evaluations": 0,
            "reconnects": 1,
            "ended_by": "learner",
        },
    }]


def test_metrics_defaults_for_a_conversation_where_the_learner_never_spoke(client, auth_headers, mock_transport):
    # App free practice: no lesson, no tool evaluations, learner silent (openingSeconds null), at the caps.
    body = {
        **LESSON_BODY,
        "client": "app",
        "mode": "free_practice",
        "language": "es",
        "level": "advanced",
        "model": "",
        "promptVersion": "",
        "durationSeconds": 7200,
        "learnerTurns": 0,
        "openingSeconds": None,
        "outcomes": {},
        "skippedTurns": {},
        "goalsReached": 0,
        "goalsAfterMisses": 0,
        "endedBy": "time",
    }
    del body["lessonId"]
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json=body, headers=auth_headers)

    assert res.status_code == 201
    row = captured[0]["row"]
    assert (row["client"], row["mode"], row["language"], row["level"]) == ("app", "free_practice", "es", "advanced")
    assert (row["model"], row["prompt_version"], row["lesson_id"]) == ("", "", "")
    assert row["duration_seconds"] == 7200
    assert row["opening_seconds"] is None
    assert [row["outcome_correto"], row["outcome_parcial"], row["outcome_incorreto"],
            row["outcome_fora_do_roteiro"]] == [0, 0, 0, 0]
    assert row["skipped_turns"] == {}
    assert row["ended_by"] == "time"


def test_metrics_require_auth(client, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json=LESSON_BODY)

    assert res.status_code == 401
    assert captured == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("durationSeconds", 7201),
        ("learnerTurns", -1),
        ("fluaWords", 200_001),
        ("fluaWordsMax", 5001),
        ("openingSeconds", 7200.5),
        ("goalsReached", 101),
        ("reconnects", 1001),
        ("outcomes", {"parcial": 2001}),
        ("model", "m" * 65),
        ("promptVersion", "v" * 129),
        ("lessonId", "l" * 65),
    ],
)
def test_metrics_reject_values_out_of_bounds(client, auth_headers, mock_transport, field, value):
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json={**LESSON_BODY, field: value}, headers=auth_headers)

    assert res.status_code == 422
    assert captured == []


@pytest.mark.parametrize(
    "skipped",
    [
        {"Too_Short": 1},
        {"too-short": 1},
        {"": 1},
        {"a" * 33: 1},
        {"too_short": 2001},
        {f"reason_{'x' * n}": 1 for n in range(11)},
    ],
    ids=["uppercase", "hyphen", "empty", "33-chars", "count-over-2000", "11-reasons"],
)
def test_metrics_reject_bad_skipped_turns(client, auth_headers, mock_transport, skipped):
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post(
        "/api/realtime/session-metrics", json={**LESSON_BODY, "skippedTurns": skipped}, headers=auth_headers,
    )

    assert res.status_code == 422
    assert captured == []


def test_metrics_accept_ten_skip_reasons(client, auth_headers, mock_transport):
    skipped = {f"reason_{'x' * n}": 1 for n in range(10)}
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post(
        "/api/realtime/session-metrics", json={**LESSON_BODY, "skippedTurns": skipped}, headers=auth_headers,
    )

    assert res.status_code == 201
    assert captured[0]["row"]["skipped_turns"] == skipped


@pytest.mark.parametrize(("field", "value"), [("endedBy", "crash"), ("client", "ios"), ("mode", "interview")])
def test_metrics_reject_unknown_enum_values(client, auth_headers, mock_transport, field, value):
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json={**LESSON_BODY, field: value}, headers=auth_headers)

    assert res.status_code == 422
    assert captured == []


def test_metrics_reject_a_body_missing_how_the_session_ended(client, auth_headers, mock_transport):
    body = {k: v for k, v in LESSON_BODY.items() if k != "endedBy"}
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json=body, headers=auth_headers)

    assert res.status_code == 422
    assert captured == []


def test_metrics_reject_a_session_id_that_is_not_a_uuid(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post("/api/realtime/session-metrics", json={**LESSON_BODY, "sessionId": "lesson-1"}, headers=auth_headers)

    assert res.status_code == 422
    assert captured == []


def test_a_failed_write_is_logged_and_answered_without_the_database_error(client, auth_headers, mock_transport, caplog):
    mock_transport(lambda request: httpx.Response(
        404, json={"message": 'relation "public.voice_session_metrics" does not exist'},
    ))

    with caplog.at_level("WARNING", logger="app.services.voice_metrics"):
        res = client.post("/api/realtime/session-metrics", json=LESSON_BODY, headers=auth_headers)

    assert res.status_code == 502
    assert res.json()["detail"] == "Não foi possível gravar as métricas da sessão."
    assert [record.getMessage() for record in caplog.records] == [
        (f"voice session metrics not saved (user {USER_ID}): Supabase upsert error 404: "
        '{"message":"relation \\"public.voice_session_metrics\\" does not exist"}'),
    ]


def test_metrics_allow_a_few_sessions_a_minute_not_a_loop(client, auth_headers, mock_transport):
    mock_transport(recording_supabase([]))

    statuses = [
        client.post("/api/realtime/session-metrics", json=LESSON_BODY, headers=auth_headers).status_code
        for _ in range(7)
    ]

    assert statuses == [201] * 6 + [429]
