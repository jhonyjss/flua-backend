"""Guided voice lesson ("Aula com a Flua" in the app): who may start one, the per-lesson time budget,
the plan contract, and the evaluation tool in the realtime session."""
import json

import httpx

LESSON = "fund-u1-l2"
OTHER = "fund-u1-l1"
# Three other lessons: an account that took them has used all of its trials.
TAKEN = ["fund-u1-l1", "fund-u1-l3", "fund-u1-l4"]
USER_ID = "00000000-0000-0000-0000-000000000001"  # conftest.make_token's default subject
# Trials of other accounts, in the same table: a read that does not filter by account sees them.
OTHER_ACCOUNTS_TRIALS = [{"lesson_id": "fund-u2-l1"}, {"lesson_id": "fund-u2-l2"}]

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


def _backend(*, plan_level=None, role="student", trial_lessons=(), claim_result=None, claim_fails=False,
             consumed=0, stripe_fails=False, trial_read_fails=False, calls=None):
    """Supabase + OpenAI as seen from the backend. `calls` collects ("openai", body) and ("claim", body)."""
    log = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "client_secrets" in path:
            log.append(("openai", json.loads(request.content)))
            return httpx.Response(200, json={"value": "ek_live_abc"})
        if path.endswith("/rpc/claim_guided_lesson_trial_slot"):
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
            # Like the table: filtered only when the query asks for this account, oldest first only
            # when the query orders by start.
            rows = [{"lesson_id": lesson} for lesson in trial_lessons]
            if request.url.params.get("user_id") != f"eq.{USER_ID}":
                rows += OTHER_ACCOUNTS_TRIALS
            if request.url.params.get("order") != "started_at.asc,lesson_id.asc":
                rows.reverse()
            return httpx.Response(200, json=rows)
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


def test_non_subscriber_takes_a_trial_on_their_first_lesson(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(claim_result={"granted": True, "lessonIds": [LESSON]}, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200
    assert _kinds(calls) == ["claim", "openai"]
    claim = calls[0][1]
    assert claim == {"p_user_id": USER_ID, "p_lesson_id": LESSON, "p_limit": 3}


def test_non_subscriber_takes_a_third_lesson(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(claim_result={"granted": True, "lessonIds": [*TAKEN[:2], LESSON]}, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200
    assert _kinds(calls) == ["claim", "openai"]


def test_non_subscriber_resumes_a_trial_after_using_all_three(client, auth_headers, mock_transport):
    mock_transport(_backend(claim_result={"granted": True, "lessonIds": [TAKEN[0], LESSON, TAKEN[1]]}))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 200


def test_non_subscriber_is_refused_a_fourth_lesson(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(claim_result={"granted": False, "lessonIds": TAKEN}, calls=calls))
    res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == {
        "code": "guided_trial_used",
        "message": "Aulas com a Flua são para assinantes. Suas 3 aulas de teste já foram usadas.",
        "trialLessonId": TAKEN[-1],
        "trialsUsed": 3,
        "trialLimit": 3,
    }
    assert "openai" not in _kinds(calls)  # no OpenAI money spent


def test_a_claim_that_contradicts_itself_gives_no_lesson(client, auth_headers, mock_transport):
    # Granted, but the lesson is not among the trials; refused while there is room; the old
    # one-trial answer (a bare lesson id): each is malformed, and malformed fails closed.
    for claim in (
        {"granted": True, "lessonIds": TAKEN[:2]},
        {"granted": False, "lessonIds": TAKEN[:2]},
        {"granted": False, "lessonIds": [*TAKEN[:2], LESSON]},
        LESSON,
        {"granted": "yes", "lessonIds": [LESSON]},
    ):
        calls = []
        mock_transport(_backend(claim_result=claim, calls=calls))
        res = client.post("/api/realtime/session", json=_body(), headers=auth_headers)
        assert res.status_code == 403, claim
        assert res.json()["detail"]["code"] == "guided_lesson_unavailable", claim
        assert "openai" not in _kinds(calls), claim


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
    mock_transport(_backend(consumed=10 * 60, claim_result={"granted": True, "lessonIds": [LESSON]}, calls=calls))  # free budget: 10 min
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


def test_plan_grammar_is_optional_and_bounded(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="pro_monthly"))
    grammar = {"name": "Verbo to be: I am", "rule": "Com I usamos am.",
               "forms": [{"label": "Afirmativa", "english": "I am Ana."}], "recap": "Com I, am."}
    ok = client.post("/api/realtime/session", json=_body(plan={**PLAN, "grammar": grammar}), headers=auth_headers)
    assert ok.status_code == 200
    long_rule = {**grammar, "rule": "x" * 321}
    assert client.post(
        "/api/realtime/session", json=_body(plan={**PLAN, "grammar": long_rule}), headers=auth_headers,
    ).status_code == 422
    five_forms = {**grammar, "forms": grammar["forms"] * 5}
    assert client.post(
        "/api/realtime/session", json=_body(plan={**PLAN, "grammar": five_forms}), headers=auth_headers,
    ).status_code == 422


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
    assert props["etapa"]["enum"] == ["repetir", "sozinho", "cena", "memoria"]
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


def test_tools_describe_what_flua_heard_not_a_transcript(client, auth_headers, mock_transport):
    # she gets audio, never the input transcription: "como foi transcrita" made her judge text she never saw
    calls = []
    mock_transport(_backend(plan_level="pro_monthly", calls=calls))
    client.post("/api/realtime/session", json=_body(), headers=auth_headers)
    client.post("/api/realtime/session", json={"mode": "lesson", "lessonContext": "Metas", "goalTool": True},
                headers=auth_headers)
    for session in [body["session"] for kind, body in calls if kind == "openai"]:
        heard = session["tools"][0]["parameters"]["properties"]["o_que_ouviu"]["description"]
        assert "ouviu" in heard
        assert "transcri" not in heard


# ── The site's lesson with client-owned goals (goalTool) ─────────────────────


def test_lesson_with_goal_tool_carries_registrar_meta_and_stays_client_driven(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(plan_level="pro_monthly", calls=calls))
    res = client.post(
        "/api/realtime/session",
        # a responsive turnMode can't sneak in: the forced tool call needs the client to own each reply
        json={"mode": "lesson", "lessonContext": "Metas desta aula:\n1. Cumprimentar", "goalTool": True,
              "turnMode": "responsive"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["goalTool"] is True
    session = _openai_session(calls)
    tool = session["tools"][0]
    assert tool["name"] == "registrar_meta"
    props = tool["parameters"]["properties"]
    assert props["resultado"]["enum"] == ["correto", "parcial", "incorreto", "fora_do_roteiro"]
    assert tool["parameters"]["required"] == ["meta", "resultado", "o_que_ouviu"]
    assert session["tool_choice"] == "auto"
    vad = session["audio"]["input"]["turn_detection"]
    assert vad["create_response"] is False and vad["interrupt_response"] is False
    assert "# Metas da aula (o app conduz" in session["instructions"]


def test_goal_tool_is_ignored_outside_the_lesson(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(plan_level="pro_monthly", calls=calls))
    free = client.post("/api/realtime/session", json={"mode": "free_practice", "goalTool": True},
                       headers=auth_headers)
    lesson = client.post("/api/realtime/session", json={"mode": "lesson", "lessonContext": "Metas"},
                         headers=auth_headers)
    # a lesson without context has no goals: the tool would be forced with nothing to judge against
    empty = client.post("/api/realtime/session", json={"mode": "lesson", "lessonContext": "  ", "goalTool": True},
                        headers=auth_headers)
    assert free.json()["goalTool"] is False
    assert lesson.json()["goalTool"] is False
    assert empty.json()["goalTool"] is False
    sessions = [body["session"] for kind, body in calls if kind == "openai"]
    assert len(sessions) == 3
    assert all("tools" not in s for s in sessions)
    assert all("# Metas da aula" not in s["instructions"] for s in sessions)


# ── What the app shows (read-only; never claims) ──────────────────────────────


def _access(client, auth_headers, lesson=LESSON):
    return client.get(f"/api/users/me/guided-lesson/access?lessonId={lesson}", headers=auth_headers)


def test_access_for_a_subscriber(client, auth_headers, mock_transport):
    mock_transport(_backend(plan_level="starter_monthly"))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "subscriber", "trialLessonId": None, "trialsUsed": None, "trialLimit": 3,
    }


def test_access_before_and_during_the_trials(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_backend(calls=calls))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "trial_available", "trialLessonId": None, "trialsUsed": 0, "trialLimit": 3,
    }
    mock_transport(_backend(trial_lessons=TAKEN[:2], calls=calls))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "trial_available", "trialLessonId": TAKEN[1], "trialsUsed": 2, "trialLimit": 3,
    }
    mock_transport(_backend(trial_lessons=[TAKEN[0], LESSON, TAKEN[1]], calls=calls))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "trial_in_progress", "trialLessonId": LESSON, "trialsUsed": 3, "trialLimit": 3,
    }
    assert "claim" not in _kinds(calls)


def test_access_after_the_three_trials(client, auth_headers, mock_transport):
    mock_transport(_backend(trial_lessons=TAKEN))
    assert _access(client, auth_headers).json() == {
        "canStart": False, "reason": "trial_used", "trialLessonId": TAKEN[-1], "trialsUsed": 3, "trialLimit": 3,
    }


def test_access_for_an_account_that_used_the_old_single_trial(client, auth_headers, mock_transport):
    # Accounts from the one-trial days keep that lesson and have two more.
    mock_transport(_backend(trial_lessons=[OTHER]))
    assert _access(client, auth_headers).json() == {
        "canStart": True, "reason": "trial_available", "trialLessonId": OTHER, "trialsUsed": 1, "trialLimit": 3,
    }


def test_access_fails_closed_for_a_non_subscriber_when_the_trials_are_unreadable(client, auth_headers, mock_transport):
    mock_transport(_backend(trial_read_fails=True))
    assert _access(client, auth_headers).json() == {
        "canStart": False, "reason": "unavailable", "trialLessonId": None, "trialsUsed": None, "trialLimit": 3,
    }


def test_access_needs_a_session(client):
    assert client.get(f"/api/users/me/guided-lesson/access?lessonId={LESSON}").status_code == 401
