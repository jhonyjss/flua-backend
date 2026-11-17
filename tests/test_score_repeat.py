"""POST /api/ai/score-repeat (flueai-app docs/rotas/02-progresso-e-fala-no-backend.md): Deepgram is
faked at HTTP; the score, the status and the calibration row (transcript and score, never audio) are
what the learner and the owner get."""
import json

import httpx
import pytest

PHRASE = "Sure. Here's my passport."
ACCEPTS = ["Sure, here is my passport.", "Here's my passport."]


def _providers(transcript, confidence=0.95, *, rows=None, insert_fails=False):
    stored = rows if rows is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.deepgram.com":
            alt = {"transcript": transcript, "confidence": confidence}
            return httpx.Response(200, json={"results": {"channels": [{"alternatives": [alt]}]}})
        if request.url.path.endswith("/route_speech_scores"):
            if insert_fails:
                return httpx.Response(500, json={"message": "down"})
            stored.append(json.loads(request.content))
            return httpx.Response(201, json=[{}])
        return httpx.Response(404)

    return handler


def _post(client, auth_headers, *, phrase=PHRASE, accepts=ACCEPTS, audio=b"m4a-bytes"):
    return client.post(
        "/api/ai/score-repeat",
        headers=auth_headers,
        files={"audio": ("take.m4a", audio, "audio/x-m4a")},
        data={"phrase": phrase, "accepts": json.dumps(accepts), "eventId": "viagem-02-checkin", "itemId": "viagem-02-i2"},
    )


def test_the_sentence_said_right_is_correct_and_kept_for_calibration(client, auth_headers, mock_transport):
    rows = []
    mock_transport(_providers("Sure, here's my passport.", rows=rows))
    res = _post(client, auth_headers)
    assert res.status_code == 200
    assert res.json() == {"status": "correct", "accuracy": 1.0, "missing_words": [], "transcript": "Sure, here's my passport."}
    assert rows == [{
        "user_id": "00000000-0000-0000-0000-000000000001",
        "event_id": "viagem-02-checkin",
        "item_id": "viagem-02-i2",
        "phrase": PHRASE,
        "transcript": "Sure, here's my passport.",
        "accuracy": 1.0,
        "confidence": 0.95,
        "status": "correct",
    }]


def test_an_accepted_variation_counts(client, auth_headers, mock_transport):
    mock_transport(_providers("here is my passport"))
    # "here is my passport" is 4 of the 5 words of the first variation: 1 − WER = 0.8.
    assert _post(client, auth_headers).json()["status"] == "correct"


def test_half_the_sentence_is_almost_with_the_missing_words(client, auth_headers, mock_transport):
    mock_transport(_providers("my passport"))
    body = _post(client, auth_headers, phrase="Here's my passport.", accepts=[]).json()
    # 2 of 3 words: 1 − 1/3 = 0.667, under 0.70 for a short sentence.
    assert body["status"] == "almost"
    assert body["accuracy"] == pytest.approx(0.667)
    assert body["missing_words"] == ["here's"]


def test_something_else_is_retry(client, auth_headers, mock_transport):
    mock_transport(_providers("I have a ticket for the train today"))
    assert _post(client, auth_headers).json()["status"] == "retry"


def test_low_confidence_is_not_heard_never_a_fail(client, auth_headers, mock_transport):
    mock_transport(_providers("I have a ticket", confidence=0.3))
    assert _post(client, auth_headers).json()["status"] == "unheard"


def test_low_confidence_does_not_take_away_a_correct_sentence(client, auth_headers, mock_transport):
    mock_transport(_providers("Sure, here's my passport.", confidence=0.4))
    assert _post(client, auth_headers).json()["status"] == "correct"


def test_silence_is_not_heard(client, auth_headers, mock_transport):
    rows = []
    mock_transport(_providers("", rows=rows))
    body = _post(client, auth_headers).json()
    assert body == {"status": "unheard", "accuracy": 0.0, "missing_words": [], "transcript": ""}
    assert rows[0]["status"] == "unheard"


def test_the_learner_gets_the_score_when_calibration_storage_fails(client, auth_headers, mock_transport):
    mock_transport(_providers("Sure, here's my passport.", insert_fails=True))
    res = _post(client, auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "correct"


@pytest.mark.parametrize("accepts", ["not json", json.dumps({"a": 1}), json.dumps([""]), json.dumps(["x"] * 13)])
def test_accepts_must_be_a_short_list_of_sentences(client, auth_headers, mock_transport, accepts):
    mock_transport(_providers("Sure"))
    res = client.post(
        "/api/ai/score-repeat",
        headers=auth_headers,
        files={"audio": ("take.m4a", b"x", "audio/x-m4a")},
        data={"phrase": PHRASE, "accepts": accepts},
    )
    assert res.status_code == 422


def test_empty_audio_is_refused(client, auth_headers, mock_transport):
    mock_transport(_providers("Sure"))
    assert _post(client, auth_headers, audio=b"").status_code == 422


def test_scoring_needs_a_session(client):
    res = client.post("/api/ai/score-repeat", files={"audio": ("take.m4a", b"x", "audio/x-m4a")}, data={"phrase": PHRASE})
    assert res.status_code == 401


def test_an_oversized_body_is_refused_before_it_is_read(client, auth_headers, mock_transport):
    called = []
    mock_transport(lambda request: called.append(request) or httpx.Response(500))
    res = client.post(
        "/api/ai/score-repeat",
        headers={**auth_headers, "Content-Type": "multipart/form-data; boundary=x", "Content-Length": "5000000"},
        content=b"--x--",
    )
    assert res.status_code == 413
    assert called == []


def test_audio_over_the_cap_is_refused_without_transcribing(client, auth_headers, mock_transport):
    called = []
    mock_transport(lambda request: called.append(request) or httpx.Response(500))
    assert _post(client, auth_headers, audio=b"x" * 2_000_001).status_code == 413
    assert called == []


def test_the_phrase_is_required(client, auth_headers, mock_transport):
    mock_transport(_providers("Sure"))
    res = client.post(
        "/api/ai/score-repeat",
        headers=auth_headers,
        files={"audio": ("take.m4a", b"x", "audio/x-m4a")},
        data={"accepts": "[]"},
    )
    assert res.status_code == 422
