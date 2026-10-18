"""Stories (ported from the site's Nitro routes): quota, scoring, and the four routes.

Supabase is faked at the HTTP boundary with a small in-memory PostgREST: it applies the eq/gte/is
filters and the select the service sends, inserts with the table's defaults and its unique
(user_id, story_id), and answers the two progress-core functions (award_web_xp, record_web_practice)
the way the SQL does for these cases. Expected values are worked out from the rules by hand."""
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app.services import stories

USER = "00000000-0000-0000-0000-000000000001"
OTHER_USER = "00000000-0000-0000-0000-000000000002"
S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"
S3 = "33333333-3333-4333-8333-333333333333"
S4 = "44444444-4444-4444-8444-444444444444"
DRAFT = "55555555-5555-4555-8555-555555555555"

QUOTA_MESSAGE = "Você atingiu o limite de 3 histórias nesta semana. Assine para leitura ilimitada."
CORRECT = [1, 0, 3, 2, 1]


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _story(sid, title, level, created, status="published"):
    return {
        "id": sid, "title": title, "cefr_level": level, "topic": "travel", "passage": f"Passage of {title}.",
        "word_count": 120, "status": status, "source": "ai", "created_at": created,
        "audio_url": None, "audio_voice": None, "audio_alignment": None,
    }


def _questions(story_id, correct=CORRECT):
    return [
        {"id": f"q{n}-{story_id[:4]}", "story_id": story_id, "question": f"Q{n}?", "options": ["a", "b", "c", "d"],
         "correct_index": c, "explanation": f"E{n}", "sort_order": n}
        for n, c in enumerate(correct)
    ]


def _progress(story_id, started_at, user=USER, **extra):
    row = {
        "id": str(uuid.uuid4()), "user_id": user, "story_id": story_id, "step": "reading", "quiz_score": None,
        "xp_earned": 0, "started_at": started_at, "completed_at": None, "updated_at": started_at,
    }
    return {**row, **extra}


class FakeSupabase:
    def __init__(self, **tables):
        self.tables: dict[str, list[dict]] = {
            "profiles": [{"id": USER, "xp": 100, "level": 1, "app_trial_ends_at": None}],
            "user_streaks": [{"user_id": USER, "current_streak": 4, "longest_streak": 9, "last_practice_date": "2026-01-01"}],
            "stripe_subscriptions": [],
            "app_store_subscriptions": [],
            "stories": [
                _story(S1, "One", "A1", "2026-10-01T10:00:00Z"),
                _story(S2, "Two", "A1", "2026-10-05T10:00:00Z"),
                _story(S3, "Three", "B1", "2026-10-02T10:00:00Z"),
                _story(S4, "Four", "A2", "2026-10-03T10:00:00Z"),
                _story(DRAFT, "Draft", "A1", "2026-10-04T10:00:00Z", status="draft"),
            ],
            "story_expressions": [
                {"id": "e1", "story_id": S1, "expression": "check in", "occurrence_index": 0, "part_of_speech": "phrasal verb",
                 "phonetic": "/tʃek ɪn/", "definition_en": "register", "definition_pt": "fazer check-in", "sort_order": 0,
                 "audio_url": None},
            ],
            "story_questions": _questions(S1) + _questions(S2) + _questions(S4)[:4],
            "user_story_progress": [],
        }
        for name, rows in tables.items():
            self.tables[name] = rows
        self.requests: list[tuple[str, str, dict]] = []
        self.rpc_calls: list[tuple[str, dict]] = []
        self.complete_before_patch = False

    @staticmethod
    def _matches(row: dict, params: dict) -> bool:
        for col, cond in params.items():
            if col in ("select", "order", "limit", "on_conflict"):
                continue
            op, _, value = cond.partition(".")
            cell = row.get(col)
            if op == "eq" and str(cell) != value:
                return False
            if op == "is" and value == "null" and cell is not None:
                return False
            if op == "gte" and (cell is None or _parse_dt(cell) < _parse_dt(value)):
                return False
        return True

    @staticmethod
    def _project(row: dict, select: str | None) -> dict:
        if not select or select == "*":
            return dict(row)
        return {col: row.get(col) for col in select.split(",")}

    def _rpc(self, fn: str, body: dict) -> httpx.Response:
        self.rpc_calls.append((fn, body))
        profile = next(p for p in self.tables["profiles"] if p["id"] == body["p_user_id"])
        if fn == "award_web_xp":
            old_level = profile["level"]
            profile["xp"] += max(body["p_amount"], 0)
            profile["level"] = profile["xp"] // 200 + 1
            return httpx.Response(200, json={"newXp": profile["xp"], "newLevel": profile["level"], "leveledUp": profile["level"] > old_level})
        if fn == "record_web_practice":
            streak = next(s for s in self.tables["user_streaks"] if s["user_id"] == body["p_user_id"])
            streak["current_streak"] += 1  # last practice was long ago in these fixtures → new day, +1
            return httpx.Response(200, json={"streak": streak["current_streak"], "isNewDay": True, "achievementsUnlocked": []})
        return httpx.Response(404, json={"message": f"unknown function {fn}"})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if "/rest/v1/rpc/" in path:
            return self._rpc(path.rsplit("/", 1)[-1], json.loads(request.content))
        table = path.rsplit("/", 1)[-1]
        self.requests.append((request.method, table, params))
        rows = self.tables.setdefault(table, [])
        if request.method == "GET":
            found = [self._project(r, params.get("select")) for r in rows if self._matches(r, params)]
            if "limit" in params:
                found = found[: int(params["limit"])]
            return httpx.Response(200, json=found)
        if request.method == "POST":
            new = json.loads(request.content)
            if table == "user_story_progress":
                if any(r["user_id"] == new["user_id"] and r["story_id"] == new["story_id"] for r in rows):
                    return httpx.Response(409, json={"code": "23505", "message": "duplicate key"})
                new = _progress(new["story_id"], _iso(datetime.now(UTC)), user=new["user_id"], step=new["step"])
            rows.append(new)
            return httpx.Response(201, json=[new])
        if request.method == "PATCH":
            values = json.loads(request.content)
            if self.complete_before_patch:  # another request completes the story between our read and our write
                for r in rows:
                    r["completed_at"] = r["completed_at"] or "2026-10-14T09:00:00Z"
                    r["quiz_score"] = 4 if r["quiz_score"] is None else r["quiz_score"]
            hit = [r for r in rows if self._matches(r, params)]
            for r in hit:
                r.update(values)
            return httpx.Response(200, json=hit)
        return httpx.Response(405)

    def progress_of(self, story_id: str, user: str = USER) -> list[dict]:
        return [r for r in self.tables["user_story_progress"] if r["story_id"] == story_id and r["user_id"] == user]

    def calls(self, method: str, table: str) -> list[dict]:
        return [p for m, t, p in self.requests if m == method and t == table]


@pytest.fixture()
def fake(mock_transport):
    db = FakeSupabase()
    mock_transport(db)
    return db


def _this_week() -> str:
    return _iso(datetime.now(UTC))


# ── Pure rules ────────────────────────────────────────────────────────

@pytest.mark.parametrize(("now", "expected"), [
    (datetime(2026, 10, 14, 15, 30, tzinfo=UTC), datetime(2026, 10, 12, tzinfo=UTC)),         # Wednesday
    (datetime(2026, 10, 18, 23, 59, 59, tzinfo=UTC), datetime(2026, 10, 12, tzinfo=UTC)),     # Sunday, last second
    (datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC), datetime(2026, 10, 19, tzinfo=UTC)),        # Monday, first second
    # 01:00 on Monday in UTC+3 is still Sunday 22:00 UTC: the week is UTC's, not the clock's.
    (datetime(2026, 10, 19, 1, 0, tzinfo=timezone(timedelta(hours=3))), datetime(2026, 10, 12, tzinfo=UTC)),
])
def test_week_starts_on_monday_utc(now, expected):
    assert stories.week_start_utc(now) == expected


@pytest.mark.parametrize(("started", "expected"), [
    (0, {"limit": 3, "used": 0, "remaining": 3, "allowed": True}),
    (2, {"limit": 3, "used": 2, "remaining": 1, "allowed": True}),
    (3, {"limit": 3, "used": 3, "remaining": 0, "allowed": False}),
    (5, {"limit": 3, "used": 5, "remaining": 0, "allowed": False}),
])
def test_free_quota(started, expected):
    assert stories.compute_story_quota(False, started) == expected


def test_paid_quota_is_unlimited():
    assert stories.compute_story_quota(True, 7) == {"limit": None, "used": 7, "remaining": None, "allowed": True}


def test_scoring():
    assert stories.score_quiz([1, 0, 3, 2, 1], CORRECT) == 5
    assert stories.score_quiz([0, 1, 0, 0, 0], CORRECT) == 0
    assert stories.score_quiz([1, 0, 3, 2], CORRECT) == 0  # wrong length scores nothing
    assert stories.score_quiz([1, 0, 0, 0, 0], CORRECT) == 2  # first two right
    assert [stories.story_xp(n) for n in (0, 2, 5)] == [10, 14, 20]


@pytest.mark.parametrize(("status", "plan", "paid"), [
    ("active", "pro_monthly", True),
    ("trialing", "starter_yearly", True),
    ("past_due", "pro_monthly", False),
    ("canceled", "pro_monthly", False),
    ("active", "free", False),
    (None, None, False),
])
def test_paid_plan(status, plan, paid):
    assert stories.is_paid_plan(status, plan) is paid


# ── Quota context (week boundary, trial, subscription sources) ────────

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday; the week started Monday 2026-10-12


def test_quota_counts_only_stories_started_since_monday_utc(fake):
    fake.tables["user_story_progress"] = [
        _progress(S1, "2026-10-11T23:59:59Z"),   # Sunday before → last week
        _progress(S2, "2026-10-12T00:00:00Z"),   # Monday 00:00 → this week
        _progress(S3, "2026-10-13T09:00:00Z"),
        _progress(S4, "2026-10-13T10:00:00Z", user=OTHER_USER),
    ]
    context = asyncio.run(stories.user_context(USER, now=NOW))
    assert context == {
        "isPaid": False,
        "quota": {"limit": 3, "used": 2, "remaining": 1, "allowed": True},
        "stats": {"xp": 100, "streak": 4},
    }
    assert fake.calls("GET", "user_story_progress")[0]["started_at"] == "gte.2026-10-12T00:00:00Z"


def test_active_trial_reads_unlimited(fake):
    fake.tables["profiles"][0]["app_trial_ends_at"] = _iso(NOW + timedelta(hours=1))
    fake.tables["user_story_progress"] = [_progress(s, "2026-10-13T09:00:00Z") for s in (S1, S2, S3)]
    context = asyncio.run(stories.user_context(USER, now=NOW))
    assert context["isPaid"] is True
    assert context["quota"] == {"limit": None, "used": 3, "remaining": None, "allowed": True}


def test_expired_trial_is_free(fake):
    fake.tables["profiles"][0]["app_trial_ends_at"] = _iso(NOW - timedelta(seconds=1))
    fake.tables["user_story_progress"] = [_progress(s, "2026-10-13T09:00:00Z") for s in (S1, S2, S3)]
    context = asyncio.run(stories.user_context(USER, now=NOW))
    assert context["isPaid"] is False
    assert context["quota"] == {"limit": 3, "used": 3, "remaining": 0, "allowed": False}


def test_stripe_plan_reads_unlimited(fake):
    fake.tables["stripe_subscriptions"] = [{"user_id": USER, "status": "active", "plan_name": "pro_monthly"}]
    assert (asyncio.run(stories.user_context(USER, now=NOW)))["quota"]["limit"] is None


def test_past_due_stripe_plan_is_free(fake):
    fake.tables["stripe_subscriptions"] = [{"user_id": USER, "status": "past_due", "plan_name": "pro_monthly"}]
    assert (asyncio.run(stories.user_context(USER, now=NOW)))["quota"]["limit"] == 3


def test_plan_bought_in_the_app_reads_unlimited(fake):
    fake.tables["app_store_subscriptions"] = [{
        "user_id": USER, "entitlement": "pro", "product_id": "flua_pro_monthly", "expires_at": "2099-01-01T00:00:00Z",
        "period_type": "normal", "billing_issue": False, "will_renew": True, "store": "app_store",
    }]
    assert (asyncio.run(stories.user_context(USER, now=NOW)))["quota"] == {"limit": None, "used": 0, "remaining": None, "allowed": True}


# ── GET /api/stories ──────────────────────────────────────────────────

def test_list_returns_published_stories_with_progress(client, auth_headers, fake):
    done = _progress(S2, _this_week(), step="done", quiz_score=4, xp_earned=18, completed_at="2026-10-13T10:00:00Z")
    fake.tables["user_story_progress"] = [done, _progress(S1, _this_week(), user=OTHER_USER)]

    res = client.get("/api/stories", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert [s["id"] for s in body["stories"]] == [S1, S2, S3, S4]  # the draft is not listed
    assert body["stories"][1] == {
        "id": S2, "title": "Two", "cefr_level": "A1", "topic": "travel", "word_count": 120,
        "created_at": "2026-10-05T10:00:00Z",
        "progress": {"step": "done", "quiz_score": 4, "xp_earned": 18, "completed_at": "2026-10-13T10:00:00Z"},
    }
    assert body["stories"][0]["progress"] is None  # another user's progress is not mine
    assert body["quota"] == {"limit": 3, "used": 1, "remaining": 2, "allowed": True}
    assert body["stats"] == {"xp": 100, "streak": 4}
    assert body["success"] is True
    listed = fake.calls("GET", "stories")[0]
    assert listed["status"] == "eq.published"
    assert listed["order"] == "cefr_level.asc,created_at.desc"


def test_routes_require_auth(client, fake):
    assert client.get("/api/stories").status_code == 401
    assert client.post(f"/api/stories/{S1}/open").status_code == 401
    assert client.post(f"/api/stories/{S1}/complete", json={"answers": CORRECT}).status_code == 401


# ── POST /api/stories/{id}/open ───────────────────────────────────────

def test_open_rejects_an_invalid_id(client, auth_headers, fake):
    res = client.post("/api/stories/not-a-uuid/open", headers=auth_headers)
    assert res.status_code == 400
    assert res.json() == {"detail": "ID inválido."}


@pytest.mark.parametrize("story_id", [DRAFT, "66666666-6666-4666-8666-666666666666"])
def test_open_unpublished_or_missing_is_404(client, auth_headers, fake, story_id):
    res = client.post(f"/api/stories/{story_id}/open", headers=auth_headers)
    assert res.status_code == 404
    assert res.json() == {"detail": "História não encontrada."}
    assert fake.tables["user_story_progress"] == []


def test_open_a_new_story_starts_it_and_spends_one_of_the_week(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(S2, _this_week())]

    res = client.post(f"/api/stories/{S1}/open", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["story"] == {
        "id": S1, "title": "One", "cefr_level": "A1", "topic": "travel", "passage": "Passage of One.",
        "word_count": 120, "audio_url": None, "audio_voice": None, "audio_alignment": None,
    }
    assert body["progress"] == {"step": "reading", "quiz_score": None, "xp_earned": 0, "completed_at": None}
    # 1 started before + this one = 2 used, 1 left (adjusted after the insert, as the site does)
    assert body["quota"] == {"limit": 3, "used": 2, "remaining": 1, "allowed": True}
    assert body["expressions"] == [{
        "id": "e1", "expression": "check in", "occurrence_index": 0, "part_of_speech": "phrasal verb",
        "phonetic": "/tʃek ɪn/", "definition_en": "register", "definition_pt": "fazer check-in", "sort_order": 0,
        "audio_url": None,
    }]
    assert [q["correct_index"] for q in body["questions"]] == CORRECT
    assert set(body["questions"][0]) == {"id", "question", "options", "correct_index", "explanation", "sort_order"}
    assert len(fake.progress_of(S1)) == 1


def test_open_a_new_story_past_the_free_limit_is_refused(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(s, _this_week()) for s in (S2, S3, S4)]

    res = client.post(f"/api/stories/{S1}/open", headers=auth_headers)

    assert res.status_code == 403
    assert res.json() == {"detail": {"code": "QUOTA_EXCEEDED", "reason": "QUOTA_EXCEEDED", "message": QUOTA_MESSAGE}}
    assert fake.progress_of(S1) == []
    assert fake.calls("POST", "user_story_progress") == []


def test_reopening_a_started_story_at_the_limit_is_allowed_and_spends_nothing(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [
        _progress(S1, _this_week(), step="vocab"), _progress(S2, _this_week()), _progress(S3, _this_week()),
    ]

    res = client.post(f"/api/stories/{S1}/open", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["progress"] == {"step": "vocab", "quiz_score": None, "xp_earned": 0, "completed_at": None}
    assert body["quota"] == {"limit": 3, "used": 3, "remaining": 0, "allowed": False}
    assert fake.calls("POST", "user_story_progress") == []


def test_open_a_new_story_with_the_app_trial_past_three(client, auth_headers, fake):
    fake.tables["profiles"][0]["app_trial_ends_at"] = "2099-01-01T00:00:00Z"
    fake.tables["user_story_progress"] = [_progress(s, _this_week()) for s in (S2, S3, S4)]

    res = client.post(f"/api/stories/{S1}/open", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["quota"] == {"limit": None, "used": 4, "remaining": None, "allowed": True}


# ── POST /api/stories/{id}/progress ───────────────────────────────────

def test_progress_saves_the_step(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(S1, _this_week())]
    res = client.post(f"/api/stories/{S1}/progress", json={"step": "quiz"}, headers=auth_headers)
    assert res.json() == {"success": True, "step": "quiz"}
    assert fake.progress_of(S1)[0]["step"] == "quiz"


def test_progress_of_a_completed_story_stays_done(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(S1, _this_week(), step="done", completed_at="2026-10-13T10:00:00Z")]
    res = client.post(f"/api/stories/{S1}/progress", json={"step": "reading"}, headers=auth_headers)
    assert res.json() == {"success": True, "step": "done"}
    assert fake.progress_of(S1)[0]["step"] == "done"


def test_progress_without_opening_first_is_404(client, auth_headers, fake):
    res = client.post(f"/api/stories/{S1}/progress", json={"step": "vocab"}, headers=auth_headers)
    assert res.status_code == 404
    assert res.json() == {"detail": "Progresso não encontrado. Abra a história primeiro."}


@pytest.mark.parametrize("body", [{"step": "done"}, {"step": "nope"}, {}, None])
def test_progress_rejects_an_invalid_step(client, auth_headers, fake, body):
    fake.tables["user_story_progress"] = [_progress(S1, _this_week())]
    res = client.post(f"/api/stories/{S1}/progress", json=body, headers=auth_headers)
    assert res.status_code == 400
    assert res.json() == {"detail": "Etapa inválida."}


# ── POST /api/stories/{id}/complete ───────────────────────────────────

def test_complete_pays_xp_once(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(S1, _this_week(), step="quiz")]
    answers = [1, 0, 3, 0, 0]  # 3 of 5 right → 10 + 2*3 = 16 XP

    first = client.post(f"/api/stories/{S1}/complete", json={"answers": answers}, headers=auth_headers)

    assert first.status_code == 200
    assert first.json() == {
        "success": True, "alreadyCompleted": False, "correctCount": 3, "total": 5,
        "xpEarned": 16, "quizScore": 3, "streak": 5,
    }
    row = fake.progress_of(S1)[0]
    assert (row["step"], row["quiz_score"], row["xp_earned"]) == ("done", 3, 16)
    assert row["completed_at"] is not None
    assert fake.tables["profiles"][0]["xp"] == 116
    assert fake.rpc_calls == [
        ("award_web_xp", {"p_user_id": USER, "p_amount": 16}),
        ("record_web_practice", {"p_user_id": USER, "p_time_seconds": 0, "p_lesson_completed": False}),
    ]

    second = client.post(f"/api/stories/{S1}/complete", json={"answers": CORRECT}, headers=auth_headers)

    assert second.status_code == 200
    assert second.json() == {
        "success": True, "alreadyCompleted": True, "correctCount": 5, "total": 5,
        "xpEarned": 0, "quizScore": 3, "streak": 5,
    }
    assert fake.tables["profiles"][0]["xp"] == 116
    assert len(fake.rpc_calls) == 2
    assert fake.progress_of(S1)[0]["quiz_score"] == 3


def test_complete_that_loses_the_race_pays_nothing(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(S1, _this_week(), step="quiz")]
    fake.complete_before_patch = True

    res = client.post(f"/api/stories/{S1}/complete", json={"answers": CORRECT}, headers=auth_headers)

    assert res.status_code == 200
    assert res.json() == {
        "success": True, "alreadyCompleted": True, "correctCount": 5, "total": 5,
        "xpEarned": 0, "quizScore": 4, "streak": 4,
    }
    assert fake.rpc_calls == []
    assert fake.tables["profiles"][0]["xp"] == 100


def test_complete_without_opening_first_is_404(client, auth_headers, fake):
    res = client.post(f"/api/stories/{S1}/complete", json={"answers": CORRECT}, headers=auth_headers)
    assert res.status_code == 404
    assert fake.rpc_calls == []


@pytest.mark.parametrize("body", [
    {"answers": [1, 0, 3, 2]},
    {"answers": [1, 0, 3, 2, 1, 0]},
    {"answers": [1, 0, 3, 2, 4]},
    {"answers": [1, 0, 3, 2, -1]},
    {"answers": [True, 0, 3, 2, 1]},
    {},
])
def test_complete_rejects_invalid_answers(client, auth_headers, fake, body):
    fake.tables["user_story_progress"] = [_progress(S1, _this_week(), step="quiz")]
    res = client.post(f"/api/stories/{S1}/complete", json=body, headers=auth_headers)
    assert res.status_code == 400
    assert res.json() == {"detail": "Respostas inválidas."}
    assert fake.rpc_calls == []


def test_complete_a_story_without_five_questions_fails_without_paying(client, auth_headers, fake):
    fake.tables["user_story_progress"] = [_progress(S4, _this_week(), step="quiz")]
    res = client.post(f"/api/stories/{S4}/complete", json={"answers": CORRECT}, headers=auth_headers)
    assert res.status_code == 500
    assert res.json() == {"detail": "Falha ao corrigir o quiz."}
    assert fake.rpc_calls == []
    assert fake.progress_of(S4)[0]["completed_at"] is None
