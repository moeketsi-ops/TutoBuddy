from pydantic_settings import BaseSettings

PLACEHOLDER = "REPLACE_ME"


class Settings(BaseSettings):
    # Meta / WhatsApp Cloud API
    whatsapp_access_token: str = PLACEHOLDER
    whatsapp_phone_number_id: str = "000000000000000"
    whatsapp_verify_token: str = "katlego-verify-token"
    meta_app_secret: str = PLACEHOLDER
    graph_api_base_url: str = "http://mockwa:8001"

    # LLM
    llm_provider: str = "stub"  # stub | anthropic
    anthropic_api_key: str = PLACEHOLDER
    router_model: str = "claude-haiku-4-5-20251001"
    reasoner_model: str = "claude-sonnet-5"

    # Speech-to-text
    stt_provider: str = "stub"  # stub | local | openai
    stt_base_url: str = "http://stt:9000"
    openai_api_key: str = PLACEHOLDER

    # Embeddings
    embeddings_provider: str = "hash"  # hash | openai
    embedding_dim: int = 384

    # Infra
    database_url: str = "postgresql://katlego:katlego@db:5432/katlego"
    redis_url: str = "redis://redis:6379/0"

    def is_set(self, value: str) -> bool:
        return bool(value) and value != PLACEHOLDER


settings = Settings()
