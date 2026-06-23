"""FastAPI service wrapper for the speech correction pipeline."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure src/ is on the path when imported from app/
_SRC = Path(__file__).resolve().parents[2] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from speech.config import SpeechPipelineConfig
from speech.pipeline import run_speech_pipeline
from speech.schemas import SpeechCorrectionRequest, SpeechCorrectionResponse

logger = logging.getLogger(__name__)

_pipeline_config = SpeechPipelineConfig()


def warm_speech_pipeline() -> None:
    """Pre-load dictionary at startup to avoid first-request latency."""
    from speech.dictionary import get_dictionary

    logger.info("Warming speech correction dictionary...")
    get_dictionary(
        dictionary_size=_pipeline_config.dictionary_size,
        max_edit_distance=_pipeline_config.max_edit_distance,
    )


async def correct_speech(request: SpeechCorrectionRequest) -> SpeechCorrectionResponse:
    """Run the full correction pipeline for an API request."""
    return await run_speech_pipeline(request, config=_pipeline_config)
