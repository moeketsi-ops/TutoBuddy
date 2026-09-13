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
    llm_provider: str = "stub"  # stub | anthropic | groq | ollama
    anthropic_api_key: str = PLACEHOLDER
    router_model: str = "claude-haiku-4-5-20251001"
    reasoner_model: str = "claude-sonnet-5"

    # groq: free/cheap hosted inference for the open gpt-oss models. Same
    # cheap-router/frontier-reasoner split as Anthropic above.
    groq_api_key: str = PLACEHOLDER
    groq_router_model: str = "openai/gpt-oss-20b"
    groq_reasoner_model: str = "openai/gpt-oss-120b"

    # ollama: fully local/offline, no API key. `ollama_base_url` defaults to
    # the Docker Desktop hostname for the host machine, since Ollama itself
    # runs on the host, not in a container. Model names are NOT verified
    # defaults the way the Anthropic/Groq ones are above -- they're only a
    # guess at what's commonly pulled; set to whatever `ollama list` shows.
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_router_model: str = "llama3.2"
    ollama_reasoner_model: str = "llama3.2"

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
