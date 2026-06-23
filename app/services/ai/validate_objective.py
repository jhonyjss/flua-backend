"""Validate objective — port of validate-objective.post.ts."""
from app.schemas.ai import ValidateObjectiveRequest, ValidateObjectiveResult
from app.core.config import get_settings
from app.services.anthropic_client import complete, extract_json

SYSTEM_TEMPLATE = """You are a STRICT English lesson objective validator.

PRIMARY GOAL: Honest correction. Mark correct only when the target is truly achieved.

VALID EVALUATIONS: EXACT_MATCH, ACCEPTABLE_EQUIVALENT, PARTIALLY_CORRECT, INCORRECT, INCOMPLETE, OFF_TOPIC

LESSON COMPLETION: completed ONLY for EXACT_MATCH or ACCEPTABLE_EQUIVALENT.

VALIDATION MODE: {mode}
- repetition: require target structure (not pronunciation perfection).
- free-production: accept valid equivalents that demonstrate the target.

Return JSON ONLY:
{{"evaluation":"...","lessonGoalStatus":"COMPLETED|NEEDS_RETRY|IN_PROGRESS","shouldAdvance":bool,"correctedText":str|null,"expectedRetry":str|null,"tutorMessage":str,"matchedPhrase":str|null,"reason":str,"confidence":float}}"""


async def validate_objective(req: ValidateObjectiveRequest) -> ValidateObjectiveResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return ValidateObjectiveResult(
            success=False,
            reason="Anthropic API key not configured",
            tutorMessage="Validation unavailable.",
        )

    phrases = "\n".join(f'{i + 1}. "{p}"' for i, p in enumerate(req.keyPhrases))
    system = SYSTEM_TEMPLATE.format(mode=req.validationMode)
    user = (
        f"Target phrases:\n{phrases}\n\nStudent said: \"{req.userMessage}\"\n\n"
        "Classify. Advance only if target truly achieved. "
        "If words and structure match a target phrase, prefer EXACT_MATCH even with accent."
    )
    try:
        raw = await complete(system, user, max_tokens=400, temperature=0.2, model=settings.anthropic_model_haiku)
        result = extract_json(raw)
    except ValueError:
        return ValidateObjectiveResult(
            success=False,
            reason="Failed to parse AI response",
            evaluation="INCORRECT",
            lessonGoalStatus="NEEDS_RETRY",
            tutorMessage="Not correct yet — try the target structure again.",
        )

    evaluation = result.get("evaluation", "INCORRECT")
    should_advance = evaluation in ("EXACT_MATCH", "ACCEPTABLE_EQUIVALENT")
    return ValidateObjectiveResult(
        success=True,
        match=should_advance,
        confidence=float(result.get("confidence") or 0),
        matchedPhrase=result.get("matchedPhrase"),
        reason=result.get("reason") or "",
        evaluation=evaluation,
        lessonGoalStatus=result.get("lessonGoalStatus") or ("COMPLETED" if should_advance else "NEEDS_RETRY"),
        shouldAdvance=should_advance,
        correctedText=result.get("correctedText"),
        expectedRetry=result.get("expectedRetry"),
        tutorMessage=result.get("tutorMessage") or "",
    )
