"""Real Postgres isolation/concurrency checks. Run with a dedicated *_test database."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

DSN = os.environ.get("CLASSROOM_TEST_DSN")
MIGRATION = os.environ.get("CLASSROOM_MIGRATION_PATH")
pytestmark = pytest.mark.skipif(
    not DSN or not MIGRATION, reason="Dedicated Postgres and migration path required"
)


@pytest.fixture(scope="module", autouse=True)
def schema():
    if not DSN or not MIGRATION:
        return
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn:
        assert conn.info.dbname.endswith("_test"), "Must use an isolated test database"
        conn.execute("create schema if not exists auth")
        for role in ("anon", "authenticated", "service_role"):
            if not conn.execute(
                "select 1 from pg_roles where rolname=%s", (role,)
            ).fetchone():
                conn.execute(f"create role {role}")
        conn.execute("create table if not exists auth.users(id uuid primary key)")
        conn.execute(
            "create table if not exists lesson_time_usage(user_id uuid,lesson_id text,consumed_seconds integer,limit_seconds integer,updated_at timestamptz,primary key(user_id,lesson_id))"
        )
        conn.execute(
            "drop table if exists classroom_events, classroom_sessions cascade"
        )
        conn.execute(Path(MIGRATION).read_text())


def seed():
    import psycopg

    user, session = str(uuid4()), str(uuid4())
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("insert into auth.users values(%s)", (user,))
        c.execute(
            "insert into classroom_sessions(id,user_id,lesson_id,content_version,state) values(%s,%s,'lesson','v1',%s::jsonb)",
            (session, user, json.dumps({"status": "active"})),
        )
    return user, session


def transition(user, session, event=None, fingerprint="same", version=0):
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as c:
        return c.execute(
            "select classroom_transition(%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                user,
                session,
                version,
                event or str(uuid4()),
                fingerprint,
                "test",
                '{"status":"active"}',
            ),
        ).fetchone()[0]


def lease(user, session, owner, action="claim"):
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as c:
        return c.execute(
            "select classroom_lease(%s,%s,%s,%s,600)", (user, session, owner, action)
        ).fetchone()[0]


def test_simultaneous_writers_only_one_wins():
    user, session = seed()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: transition(user, session), range(2)))
    assert sorted(r.get("error", 200) for r in results) == [200, 409]


def test_idempotent_replay_and_conflicting_payload():
    user, session = seed()
    event = str(uuid4())
    first = transition(user, session, event)
    replay = transition(user, session, event)
    assert first["version"] == replay["version"] == 1
    assert replay["replayed"]
    assert transition(user, session, event, "different")["error"] == 409


def test_cross_user_state_is_invisible():
    _user, session = seed()
    assert transition(str(uuid4()), session)["error"] == 404


def test_one_lease_per_account_and_stale_owner_rejected():
    user, session = seed()
    owners = [str(uuid4()), str(uuid4())]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda owner: lease(user, session, owner), owners))
    assert sum("error" not in r for r in results) == 1
    loser = owners[next(i for i, r in enumerate(results) if "error" in r)]
    assert lease(user, session, loser, "renew")["error"] == 409


def test_elapsed_time_is_charged_once():
    import psycopg

    user, session = seed()
    owner = str(uuid4())
    lease(user, session, owner)
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(
            "update classroom_sessions set billed_at=now()-interval '10 seconds' where id=%s",
            (session,),
        )
    first = lease(user, session, owner, "renew")
    second = lease(user, session, owner, "renew")
    assert first["remainingSeconds"] == second["remainingSeconds"] == 590


def test_authenticated_role_cannot_mutate_server_owned_progress():
    import psycopg

    user, session = seed()
    with psycopg.connect(DSN) as c:
        c.execute("set role authenticated")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "select classroom_transition(%s,%s,0,%s,%s,%s,%s::jsonb)",
                (user, session, str(uuid4()), "x", "test", "{}"),
            )
        c.rollback()
