"""API integration test for speech correction endpoint."""
import pytest

from speech.pipeline import run_speech_pipeline
from speech.schemas import SpeechCorrectionRequest


@pytest.mark.asyncio
async def test_pipeline_how_r_u():
    request = SpeechCorrectionRequest(
        raw_transcription="how r u",
        expected_sentence="how are you",
    )
    response = await run_speech_pipeline(request)
    assert response.corrected_transcription == "how are you"
    assert response.score is not None
    assert response.score >= 0.95
