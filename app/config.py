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
    llm_provider: str = "stub"  # stub | anthropic | groq | ollama | openrouter
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

    # openrouter: OpenAI-compatible API (https://openrouter.ai/api/v1), one
    # key across many hosted models. The reasoner model also serves
    # photo_reply, so it must take images. Defaults are the cleanest models
    # from the 31 Oct bench pilot (0 failed calls), pending the judged screen;
    # Qwen3.5-35B-A3B was dropped because half its calls came back empty. Router stays on whichever
    # provider LLM_PROVIDER already points to unless you also set
    # LLM_PROVIDER=openrouter, in which case openrouter handles intent
    # routing too. To mix providers per tier, see REASONER_PROVIDER below.
    openrouter_api_key: str = PLACEHOLDER
    openrouter_router_model: str = "z-ai/glm-5.3-flash"
    openrouter_reasoner_model: str = "openai/gpt-6-luna"
    openrouter_vision_model: str = "openai/gpt-6-luna"

    # Intent router tier (app/adapters/router.py). "" = follow LLM_PROVIDER;
    # "jev" = TypeSafe AI's typed-decision model, with confidence-threshold
    # fallback to the LLM router. Pin the model version, per TypeSafe's docs.
    router_provider: str = ""  # "" | jev

    # Reasoner tier (tutoring, practice questions, grading, photos, eval
    # answers). "" = follow LLM_PROVIDER. Set it to split the tiers, e.g.
    # LLM_PROVIDER=groq for cheap routing + REASONER_PROVIDER=anthropic for
    # tutoring. Values: "" | stub | anthropic | groq | ollama | openrouter.
    # Uses that provider's *_REASONER_MODEL setting.
    reasoner_provider: str = ""

    # How a tutoring turn reports its state (spec v0.1; founder chose
    # structured output, 16 Oct): "json" = schema-constrained JSON object
    # (state + reply), falling back to the STATE line if the provider
    # refuses the schema; "state_line" = the hidden STATE line only.
    structured_output: str = "json"

    # Reasoning effort per tier (blank = each call's built-in default, which
    # is today's behaviour). none | minimal | low | medium | high. Sent as
    # OpenRouter reasoning.effort, Anthropic output_config.effort, or Groq
    # reasoning_effort; the output-token limit grows with it so reasoning
    # can't eat the visible reply. Chosen by evals/bench (model bake-off).
    router_effort: str = ""
    reasoner_effort: str = ""
    # Pin OpenRouter to one host for open models (e.g. "Groq"); sent with
    # allow_fallbacks=false so a silent reroute can't change quality.
    openrouter_provider: str = ""

    # Prompt layout for tutoring replies (prompt caching, 5 Nov 2026).
    # "classic": rules, then this turn's teaching line, memory and notes in one
    # system prompt (only ~650 tokens are the same from turn to turn).
    # "layered": most stable first, so providers can cache the prefix:
    # rules + grade frame + this learner's profile (frozen for the session)
    # as the system prompt, then the session's turns as real chat messages,
    # then this turn's teaching line and notes, then the learner's message.
    prompt_layout: str = "classic"
    # Send OpenRouter a session_id per learner so their turns stay on one host
    # (sticky routing; ignored when OPENROUTER_PROVIDER pins a host).
    openrouter_session_ids: bool = True
    # How long a cached prefix is assumed to live when estimating cacheable
    # tokens (OpenRouter sticky routing: 10 minutes idle).
    cache_ttl_seconds: int = 600

    typesafe_api_key: str = PLACEHOLDER
    jev_model: str = "jev-1.13.0"
    jev_min_confidence: float = 0.6

    # Speech-to-text
    stt_provider: str = "stub"  # stub | local | openai | groq
    groq_stt_model: str = "whisper-large-v3"  # or whisper-large-v3-turbo (faster, cheaper)
    stt_base_url: str = "http://stt:9000"
    # Language Whisper is told to expect. "en" (today's behaviour) or "auto"
    # (let it detect; for code-switched notes). See evals/bench/media.
    stt_language: str = "en"
    # Optional hint to Whisper (Groq/OpenAI `prompt`): a short sample of the
    # style wanted, e.g. maths written in symbols. Blank = none (today).
    stt_prompt: str = ""
    # Rewrite spoken maths in a transcript as symbols ("x equals negative
    # five" -> "x = -5") before the tutor sees it, so the code answer check
    # works on voice notes (app/tutor/spoken.py). false = the transcript as heard.
    stt_symbols: bool = True
    # Homework photos. "read" (default since 15 Nov 2026, after the real-photo
    # test): the photo is read into text (problem, working, diagram) and that
    # text goes through the normal tutor engine, so memory, the code answer
    # check, mastery evidence and the leak guard all apply. A photo that can't
    # be read falls back to "single": one stand-alone vision reply (the old path).
    photo_pipeline: str = "read"
    openai_api_key: str = PLACEHOLDER

    # Embeddings
    embeddings_provider: str = "hash"  # hash | openai
    embedding_dim: int = 384

    # Safeguarding (child-safety layer 4): where a flagged crisis/abuse
    # message alerts a real human. WhatsApp is reused deliberately -- no new
    # service/credential, works with the same WhatsAppClient already wired
    # up. Leave unset (PLACEHOLDER) and alerts are logged at CRITICAL and
    # persisted to safeguarding_flags, but nothing is pushed to anyone.
    safeguarding_alert_phone: str = PLACEHOLDER

    # Infra
    database_url: str = "postgresql://katlego:katlego@db:5432/katlego"
    redis_url: str = "redis://redis:6379/0"

    def is_set(self, value: str) -> bool:
        return bool(value) and value != PLACEHOLDER


settings = Settings()
