"""Guided voice lesson ("Aula com a Flua" in the app): who may start one, the per-lesson time budget,
the plan contract, and the evaluation tool in the realtime session."""
import json

import httpx

LESSON = "fund-u1-l2"
OTHER = "fund-u1-l1"

PLAN = {
    "title": "Apresentações",
    "skill": "se apresentar",
    "items": [
        {"id": "c-i-am", "english": "I am Ana.", "portuguese": "Eu sou Ana.", "note": "I sempre vem com am."},
        {
            "id": "c-my-name-is",
            "english": "My name is Ana.",
            "portuguese": "Meu nome é Ana.",
            "note": "My name sempre vem com is.",
            "cue": "Diga o seu nome para a Flua.",
            "accepts": ["My name is <nome>.", "I am <nome>."],
        },
    ],
}


def _body(**patch):
    return {"mode": "guided_lesson", "lessonId": LESSON, "plan": PLAN, "studentName": "Jhony", **patch}


def _backend(*, plan_level=None, role="student", trial_lesson=None, claim_result=None, claim_fails=False,
             consumed=0, stripe_fails=False, trial_read_fails=False, calls=None):
    """Supabase + OpenAI as seen from the backend. `calls` collects ("openai", body) and ("claim", body)."""
    log = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "client_secrets" in path:
            log.append(("openai", json.loads(request.content)))
            return httpx.Response(200, json={"value": "ek_live_abc"})
        if path.endswith("/rpc/claim_guided_lesson_trial"):
            log.append(("claim", json.loads(request.content)))
            if claim_fails:
                return httpx.Response(500, json={"message": "boom"})
            return httpx.Response(200, json=claim_result)
        if "stripe_subscriptions" in path:
            if stripe_fails:
                return httpx.Response(500, json={"message": "down"})
            rows = [] if plan_level is None else [{"status": "active", "plan_level": plan_level}]
            return httpx.Response(200, json=rows)
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "role": role}])
        if "guided_lesson_trials" in path:
            if trial_read_fails:
                return httpx.Response(500, json={"message": "down"})
            return httpx.Response(200, json=[] if trial_lesson is None else [{"lesson_id": trial_lesson}])
        if "lesson_time_usage" in path:
            return httpx.Response(200, json=[{"id": "row-1", "consumed_seconds": consumed}] if consumed else [])
        return httpx.Response(200, json=[])

    return handler


def _kinds(calls):
    return [kind for kind, _ in calls]


def _openai_session(calls):
    return next(body for kind, body in calls if kind == "openai")["session"]


# ── Who may start ─────────────────────────────────────────────────────────────


def test_subscriber_starts_without_touching_the_trial(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(plan_level="starter_monthly", calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200
    assert _kinds(calls) == ["openai"]


def test_admin_starts_without_a_subscription_or_the_trial(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(role="admin", calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200
    assert _kinds(calls) == ["openai"]


def test_non_subscriber_claims_the_trial_on_their_first_lesson(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(claim_result=LESSON, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200
    assert _kinds(calls) == ["claim", "openai"]
    claim = calls[0][1]
    assert claim == {"p_user_id": "00000000-0000-0000-0000-000000000001", "p_lesson_id": LESSON}


def test_non_subscriber_is_refused_a_second_lesson(client, auth_headers, mock_transport):
    calls = []
    # The account's trial is already another lesson: the claim answers with that one.
    mock_transport(_backend(claim_result=OTHER, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "guided_trial_used"
    assert res.json()["detail"]["trialLessonId"] == OTHER
    assert "openai" not in _kinds(calls)  # no OpenAI money spent


def test_non_subscriber_gets_no_lesson_when_the_trial_cannot_be_recorded(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(claim_fails=True, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "guided_lesson_unavailable"
    assert "openai" not in _kinds(calls)


def test_unreadable_subscription_fails_open_like_the_other_budgets(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(stripe_fails=True, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200
    assert "claim" not in _kinds(calls)


# ── Per-lesson time budget ────────────────────────────────────────────────────


def test_spent_lesson_time_is_refused_before_claiming_anything(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(consumed=10 * 60, claim_result=LESSON, calls=calls))  # free budget: 10 min
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "lesson_time_expired"
    assert calls == []


def test_subscriber_with_time_left_on_the_paid_budget_starts(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="pro_monthly", consumed=10 * 60))  # paid budget: 15 min
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200


def test_admin_has_no_lesson_time_limit(client, auth_headers, mock_transport):
    mock_transport(_backend(role="admin", consumed=60 * 60))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200


# ── Plan contract ─────────────────────────────────────────────────────────────


def test_guided_lesson_requires_a_lesson_and_a_plan(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="pro_monthly"))
    assert client.post("/api/realtime/session", json=_body(plan=None), headers=auth_headers).status_code == 422
    assert client.post("/api/realtime/session", json=_body(lessonId=""), headers=auth_headers).status_code == 422


def test_plan_is_bounded(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="pro_monthly"))
    item = PLAN["items"][0]
    nine = {**PLAN, "items": [{**item, "id": f"c-{i}"} for i in range(9)]}
    assert client.post("/api/realtime/session", json=_body(plan=nine), headers=auth_headers).status_code == 422
    long_phrase = {**PLAN, "items": [{**item, "english": "x" * 161}]}
    assert client.post("/api/realtime/session", json=_body(plan=long_phrase), headers=auth_headers).status_code == 422
    assert client.post("/api/realtime/session", json=_body(lessonId="fund u1; drop"), headers=auth_headers).status_code == 422


def test_resume_must_point_at_an_item_of_the_plan(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="pro_monthly"))
    assert client.post("/api/realtime/session", json=_body(resumeFromItem=2), headers=auth_headers).status_code == 422
    assert client.post("/api/realtime/session", json=_body(resumeFromItem=1), headers=auth_headers).status_code == 200


# ── The realtime session ──────────────────────────────────────────────────────


def test_session_carries_the_plan_and_the_evaluation_tool(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(plan_level="pro_monthly", calls=calls))
    client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    session = _openai_session(calls)
    tool = session["tools"][0]
    assert tool["type"] == "function"
    assert tool["name"] == "registrar_resultado"
    props = tool["parameters"]["properties"]
    assert props["etapa"]["enum"] == ["repetir", "sozinho"]
    assert props["resultado"]["enum"] == ["correto", "parcial", "incorreto", "fora_do_roteiro"]
    assert tool["parameters"]["required"] == ["item_id", "etapa", "resultado", "o_que_ouviu"]
    assert session["tool_choice"] == "auto"
    assert "id=c-my-name-is" in session["instructions"]
    assert "Diga o seu nome para a Flua." in session["instructions"]


def test_other_modes_carry_no_tools(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(plan_level="pro_monthly", calls=calls))
    client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
    client.post("/api/realtime/session", json={"mode": "lesson"}, headers=auth_headers)
    sessions = [body["session"] for kind, body in calls if kind == "openai"]
    assert len(sessions) == 2
    assert all("tools" not in s and "tool_choice" not in s for s in sessions)


# ── What the app shows (read-only; never claims) ──────────────────────────────


def _access(client, auth_headers, lesson=LESSON):
    return client.get(f"/api/users/me/guided-lesson/access?lessonId={lesson}", headers=auth_headers)


def test_access_for_a_subscriber(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="starter_monthly"))
    assert _access(client, auth_headers).json() == {"canStart": True, "reason": "subscriber", "trialLessonId": None}


def test_access_before_and_during_the_trial(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(calls=calls))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "trial_available", "trialLessonId": None,
    }
    mock_transport(_backend(trial_lesson=LESSON, calls=calls))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "trial_in_progress", "trialLessonId": LESSON,
    }
    assert "claim" not in _kinds(calls)


def test_access_after_the_trial(client, auth_headers, mock_transport):
    mock_transport(_backend(trial_lesson=OTHER))
    assert _access(client, auth_headers).json() == {
        "canStart": False, "reason": "trial_used", "trialLessonId": OTHER,
    }


def test_access_fails_closed_for_a_non_subscriber_when_the_trial_is_unreadable(client, auth_headers, mock_transport):
    mock_transport(_backend(trial_read_fails=True))
    assert _access(client, auth_headers).json() == {
        "canStart": False, "reason": "unavailable", "trialLessonId": None,
    }


def test_access_needs_a_session(client):
    assert client.get(f"/api/users/me/guided-lesson/access?lessonId={LESSON}").status_code == 401
