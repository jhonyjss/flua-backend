"""Learning recommendations — port of learning-recommendations.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import LearningRecommendationsRequest, LearningRecommendationsResult, StudyTip
from app.services.anthropic_client import complete, extract_json

SYSTEM_PROMPT = """You are an English-learning coach for Brazilian students.
Given student stats, identify focus areas and next steps.
Respond ONLY with JSON:
{"focusAreas":[{"title":str,"description":str,"severity":"low"|"medium"|"high"}],
"studyTips":[{"title":str,"description":str}],
"overallAssessment":str,"overallAssessmentPt":str,"suggestedNextLesson":str,
"recommendedTopics":[str],"motivationPt":str}"""


def _user_message(req: LearningRecommendationsRequest) -> str:
    grammar = "; ".join(
        f"{g.topic}: mastery {g.masteryLevel}, {g.exercisesCorrect}/{g.exercisesCompleted}"
        for g in req.grammarProgress
    ) or "no grammar data"
    return (
        f"Level: {req.userLevel}. Streak: {req.streakDays} days. "
        f"Lessons completed: {req.totalLessonsCompleted}. Grammar: {grammar}. "
        f"Vocabulary: {req.vocabularyStats.mastered}/{req.vocabularyStats.total} mastered, "
        f"{req.vocabularyStats.dueForReview} due. Sessions: {len(req.sessionHistory)}."
    )


async def learning_recommendations(req: LearningRecommendationsRequest) -> LearningRecommendationsResult:
    try:
        raw = await complete(
            SYSTEM_PROMPT,
            _user_message(req),
            max_tokens=900,
            temperature=0.4,
            model=get_settings().anthropic_model_sonnet,
        )
        data = extract_json(raw)
        tips = [StudyTip(**t) if isinstance(t, dict) else StudyTip(title=str(t), description="") for t in data.get("studyTips", [])]
        return LearningRecommendationsResult(
            success=True,
            focusAreas=data.get("focusAreas", []),
            studyTips=tips,
            overallAssessment=data.get("overallAssessment", ""),
            overallAssessmentPt=data.get("overallAssessmentPt", ""),
            suggestedNextLesson=data.get("suggestedNextLesson", ""),
            recommendedTopics=data.get("recommendedTopics", []),
            motivationPt=data.get("motivationPt", ""),
        )
    except ValueError:
        return LearningRecommendationsResult(success=False, error="Não foi possível gerar recomendações.")
