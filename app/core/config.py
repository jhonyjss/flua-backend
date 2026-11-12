"""Application settings (pydantic-settings, loaded from env / .env)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CLAUDE_HAIKU_55 = "claude-haiku-5-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "development"
    # Set by Fly at runtime (registry.fly.io/<app>:deployment-<id>); its tag versions Flua's prompt.
    fly_image_ref: str = ""
    cors_origins: str = "http://localhost:5555"
    frontend_url: str = "http://localhost:5555"

    # Supabase
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_service_key: str = ""

    # AI providers
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_model_haiku: str = "claude-3-5-haiku-20241022"
    anthropic_model_text_tutor: str = CLAUDE_HAIKU_55
    anthropic_model_sonnet: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""
    openai_voice_model: str = "gpt-4o-mini"
    # OpenAI Realtime (voice class). Env-overridable so models can be swapped
    # without a redeploy. Values must be valid IDs from GET /v1/models or the
    # session mint 404s (model_not_found) and voice breaks entirely.
    # mini = ~3x cheaper audio ($10/$20 per 1M vs $32/$64) than the full family.
    openai_realtime_model: str = "gpt-realtime-2.1-mini"
    # Intermediate and advanced learners talk longer and more freely: the full model hears accents and
    # nuance better. Beginners keep the mini (realtime.model_for_level).
    openai_realtime_model_advanced: str = "gpt-realtime-2.1"
    # gpt-4o-transcribe keeps the biasing `prompt` (accuracy for PT/EN + names);
    # gpt-realtime-whisper is cheaper but drops the prompt. STT cost is tiny next
    # to the realtime audio, so accuracy wins by default.
    openai_realtime_transcribe_model: str = "gpt-4o-transcribe"
    openai_realtime_noise_reduction: str = "far_field"  # near_field | far_field
    # semantic_vad eagerness for free practice (flueai docs/flua-tutor/04-professor-por-voz.md).
    # "low" gives a learner searching for a word the most time and can lengthen the wait; compare with "medium".
    openai_realtime_vad_eagerness: Literal["low", "medium", "high", "auto"] = "low"
    # The tool lessons' end of turn (guided_lesson and the site's lesson with goalTool). Measured with audio
    # (evals/flua/voice_timing.py, 2026-11-12): "low" waited 4-8.6 s on short complete answers ("I am Ana.",
    # "Hello!"), its 8 s timeout; "medium" closes most turns in ~0.9 s against server VAD's 1.7 s; "high" cut
    # mid-sentence pauses. The client asks for every reply here, so a long wait is dead air.
    openai_realtime_lesson_vad_eagerness: Literal["low", "medium", "high", "auto"] = "medium"
    # Flua's speaking speed in the app's guided lesson (audio.output.speed; the API takes 0.25-1.5, 1.0 is its
    # default). Above 1.0 to keep the class moving; the other modes keep the API default.
    openai_realtime_guided_voice_speed: float = Field(1.1, ge=0.8, le=1.3)
    replicate_api_key: str = ""
    elevenlabs_api_key: str = ""
    google_tts_api_key: str = ""
    deepgram_api_key: str = ""

    classroom_v2_enabled: bool = False
    classroom_v2_users: str = ""
    classroom_voice_speed: float = Field(0.9, ge=0.75, le=1.1)
    classroom_teaching_pilot_enabled: bool = False
    classroom_roleplay_pilot_enabled: bool = False

    # Telegram error alerts (dormant unless both are set)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter_monthly: str = ""
    stripe_price_starter_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""

    # RevenueCat (in-app purchases on the App Store and Google Play)
    revenuecat_secret_key: str = ""
    # The exact Authorization header value set on the RevenueCat webhook (e.g. "Bearer <random>").
    revenuecat_webhook_auth: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def stripe_price_id(self, plan: str, billing: str) -> str:
        """Resolve the Stripe price ID for plan ('starter'|'pro') + billing ('monthly'|'yearly')."""
        return {
            ("starter", "monthly"): self.stripe_price_starter_monthly,
            ("starter", "yearly"): self.stripe_price_starter_yearly,
            ("pro", "monthly"): self.stripe_price_pro_monthly,
            ("pro", "yearly"): self.stripe_price_pro_yearly,
        }.get((plan, billing), "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
