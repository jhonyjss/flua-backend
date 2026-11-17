"""Route events on the account (flueai-app docs/rotas/02-progresso-e-fala-no-backend.md): validation
against the route manifest, the first-time XP and stamp sent to finish_route_event, and the travel track
in the summary. The rules inside the SQL function (repeat XP, gold upgrade, order, streak) are checked
against Postgres by flueai supabase/tests/route_progress.test.sql; here the database is faked at HTTP."""
import json
from datetime import date

import httpx
import pytest

from app.services import app_progress

TODAY = date(2026, 11, 17)
USER = "00000000-0000-0000-0000-000000000001"
SESSION = "6a1d0c2e-1111-4c3b-9e21-0a1b2c3d4e5f"
EVENT = "viagem-02-checkin"
ITEMS = [f"viagem-02-i{n}" for n in range(1, 7)]
WRITE_ITEMS = ["viagem-02-i2", "viagem-02-i3", "viagem-02-i4"]
TURNS = [f"viagem-02-t{n}" for n in range(1, 6)]
PROFILE = {"id": USER, "full_name": "Jhony", "daily_goal_xp": 20, "motivation": "travel", "xp": 50}
STORED = {
    "xpAwarded": 36, "firstTryCorrect": 5, "mainTotal": 6, "passed": None, "unlockedActivityId": None,
    "newAchievementIds": [], "streakIncremented": True, "stamp": "gold",
}


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setattr(app_progress, "sao_paulo_day", lambda now=None: TODAY)


def _db(*, stamps=(), rpc=None, calls=None):
    log = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/rpc/finish_route_event"):
            log.append(("rpc", json.loads(request.content)))
            return rpc(request) if callable(rpc) else httpx.Response(200, json=rpc)
        if path.endswith("/profiles"):
            return httpx.Response(200, json=[PROFILE])
        if path.endswith("/route_stamps"):
            log.append(("route_stamps", dict(request.url.params)))
            return httpx.Response(200, json=[{"event_id": e, "stamp": s} for e, s in stamps])
        return httpx.Response(200, json=[])

    return handler


def _attempt(exercise, correct=True, hint=False):
    return {"exerciseId": exercise, "conceptId": EVENT, "correct": correct, "usedHint": hint}


def _gold_run():
    """i1 missed once then right; every sentence said right; "Ver a frase" on the third turn."""
    return (
        [_attempt("viagem-02-i1", correct=False), _attempt("viagem-02-i1")]
        + [_attempt(item) for item in ITEMS[1:]]
        + [_attempt(f"speak:{item}:nice") for item in ITEMS]
        + [_attempt(f"speak:{item}:again") for item in WRITE_ITEMS]
        + [_attempt(f"speak:{turn}", hint=turn == "viagem-02-t3") for turn in TURNS]
    )


def _event(**patch):
    body = {
        "client": "app",
        "contentVersion": "travel-1",
        "activityId": EVENT,
        "kind": "route_event",
        "completedAt": "2026-11-17T10:00:00-03:00",
        "origin": "normal",
        "attempts": _gold_run(),
    }
    return {**body, **patch}


def _put(client, auth_headers, body):
    return client.put(f"/api/users/me/sessions/{SESSION}/result", json=body, headers=auth_headers)


def test_gold_event_goes_to_the_core_with_its_xp_stamp_order_and_concepts(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(stamps=[(EVENT, "gold")], rpc={"replayed": False, "result": STORED}, calls=calls))
    res = _put(client, auth_headers, _event())
    assert res.status_code == 200
    body = res.json()
    assert body["replayed"] is False
    assert body["result"] == STORED
    assert body["summary"]["tracks"]["travel"] == {
        "completedActivityIds": [EVENT], "currentActivityId": None, "stamps": {EVENT: "gold"},
    }
    sent = dict(calls)["rpc"]
    # 6 items × 2 + 13 sentences paid (6 nice + 3 again + 4 turns; t3 used "Ver a frase") + 3 + 5 + gold 3.
    assert sent["p_first_xp"] == 36
    assert sent["p_stamp"] == "gold"
    assert sent["p_items_correct"] == 5
    assert sent["p_items_total"] == 6
    assert sent["p_route"] == "travel"
    assert sent["p_order"] == [EVENT]
    assert sent["p_concepts"] == [f"route:{EVENT}:t{n}" for n in range(1, 6)]
    assert sent["p_session_id"] == SESSION


def test_a_sentence_missed_makes_it_silver_and_pays_only_what_was_said(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(rpc={"replayed": False, "result": {**STORED, "stamp": "silver"}}, calls=calls))
    attempts = [a for a in _gold_run() if a["exerciseId"] != "speak:viagem-02-i5:nice"]
    attempts += [_attempt("speak:viagem-02-i5:nice", correct=False)]
    assert _put(client, auth_headers, _event(attempts=attempts)).status_code == 200
    sent = dict(calls)["rpc"]
    # 12 + 12 sentences paid + 3 + 5, no gold.
    assert sent["p_first_xp"] == 32
    assert sent["p_stamp"] == "silver"


def test_an_item_never_answered_right_pays_nothing_for_it(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(rpc={"replayed": False, "result": STORED}, calls=calls))
    attempts = [a for a in _gold_run() if a["exerciseId"] != "viagem-02-i6"]
    attempts += [_attempt("viagem-02-i6", correct=False), _attempt("viagem-02-i6", correct=False)]
    _put(client, auth_headers, _event(attempts=attempts))
    sent = dict(calls)["rpc"]
    assert sent["p_first_xp"] == 34
    assert sent["p_items_correct"] == 4


def test_the_same_sentence_twice_pays_once(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(rpc={"replayed": False, "result": STORED}, calls=calls))
    _put(client, auth_headers, _event(attempts=_gold_run() + [_attempt("speak:viagem-02-i1:nice")]))
    assert dict(calls)["rpc"]["p_first_xp"] == 36


def test_a_resend_returns_the_stored_result(client, auth_headers, mock_transport):
    mock_transport(_db(stamps=[(EVENT, "gold")], rpc={"replayed": True, "result": STORED}))
    body = _put(client, auth_headers, _event()).json()
    assert body["replayed"] is True
    assert body["result"] == STORED


def test_old_route_content_is_refused_with_409(client, auth_headers, mock_transport):
    mock_transport(_db(rpc={"replayed": False, "result": STORED}))
    res = _put(client, auth_headers, _event(contentVersion="travel-0"))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "content_version"


def test_locked_event_from_the_core_becomes_409(client, auth_headers, mock_transport):
    mock_transport(_db(rpc=lambda request: httpx.Response(400, json={"code": "P0001", "message": "activity_locked"})))
    res = _put(client, auth_headers, _event())
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "activity_locked"


@pytest.mark.parametrize("attempts, why", [
    ([a for a in _gold_run() if a["exerciseId"] != "speak:viagem-02-t5"], "a turn missing"),
    ([a for a in _gold_run() if a["exerciseId"] != "viagem-02-i4"], "an item missing"),
    (_gold_run() + [_attempt("speak:viagem-02-i1:again")], "again on an item with no writing"),
    (_gold_run() + [_attempt("viagem-02-i9")], "an id outside the manifest"),
])
def test_attempts_that_do_not_match_the_event_are_refused_with_422(client, auth_headers, mock_transport, attempts, why):
    calls = []
    mock_transport(_db(rpc={"replayed": False, "result": STORED}, calls=calls))
    res = _put(client, auth_headers, _event(attempts=attempts))
    assert res.status_code == 422, why
    assert res.json()["detail"]["code"] == "invalid_attempts"
    assert "rpc" not in dict(calls)


def test_an_event_not_in_the_manifest_is_refused_with_422(client, auth_headers, mock_transport):
    mock_transport(_db(rpc={"replayed": False, "result": STORED}))
    res = _put(client, auth_headers, _event(activityId="viagem-03-seguranca"))
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_activity"


def test_summary_reads_the_stamps_of_the_travel_route(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_db(stamps=[(EVENT, "silver")], calls=calls))
    travel = client.get("/api/users/me/summary", headers=auth_headers).json()["tracks"]["travel"]
    assert travel == {"completedActivityIds": [EVENT], "currentActivityId": None, "stamps": {EVENT: "silver"}}
    assert dict(calls)["route_stamps"]["route"] == "eq.travel"
