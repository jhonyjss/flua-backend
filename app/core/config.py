"""Application settings (pydantic-settings, loaded from env / .env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
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
    anthropic_model_sonnet: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""
    openai_voice_model: str = "gpt-4o-mini"
    replicate_api_key: str = ""
    elevenlabs_api_key: str = ""
    google_tts_api_key: str = ""
    deepgram_api_key: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter_monthly: str = ""
    stripe_price_starter_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""

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
