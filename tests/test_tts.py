import base64

import httpx

from app.services.tts import resolve_google_voice, split_text_for_tts


def test_split_short_text_single_chunk():
    assert split_text_for_tts("Hello world.", 100) == ["Hello world."]


def test_split_respects_limit_and_sentence_boundaries():
    text = "One sentence here. Another sentence there! A question? Final bit."
    chunks = split_text_for_tts(text, 30)
    assert all(len(c) <= 30 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_split_hard_breaks_very_long_sentence():
    text = "word " * 100
    chunks = split_text_for_tts(text.strip(), 40)
    assert all(len(c) <= 40 for c in chunks)


def test_resolve_google_voice_named_and_chirp():
    assert resolve_google_voice("sarah", "en-US")["name"] == "en-US-Studio-O"
    assert resolve_google_voice("chirp3hd_Charon", "pt-BR")["name"] == "pt-BR-Chirp3-HD-Charon"
    assert resolve_google_voice("en-GB-Neural2-A", "en-GB")["name"] == "en-GB-Neural2-A"
    assert resolve_google_voice("unknown", "en-US")["name"] == "en-US-Studio-O"


def test_speak_google_returns_base64_audio(client, auth_headers, mock_transport):
    fake_mp3 = b"ID3fakeaudio"
    google = {"audioContent": base64.b64encode(fake_mp3).decode()}
    mock_transport(lambda request: httpx.Response(200, json=google))
    res = client.post(
        "/api/avatar/speak",
        json={"text": "Hello!", "ttsProvider": "google", "voiceId": "sarah"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["provider"] == "google"
    assert base64.b64decode(data["audioBase64"]) == fake_mp3


def test_speak_browser_provider_returns_no_audio(client, auth_headers):
    res = client.post(
        "/api/avatar/speak",
        json={"text": "Olá!", "ttsProvider": "browser"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json() == {"success": True, "audioBase64": None, "provider": "browser", "error": None}


def test_speak_provider_failure_returns_502(client, auth_headers, mock_transport):
    mock_transport(lambda request: httpx.Response(500, text="boom"))
    res = client.post(
        "/api/avatar/speak",
        json={"text": "Hello!", "ttsProvider": "openai", "voiceId": "coral"},
        headers=auth_headers,
    )
    assert res.status_code == 502
