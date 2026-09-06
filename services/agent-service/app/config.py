"""Settings for agent-service, loaded from environment via pydantic-settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "agent-service"
    log_level: str = "INFO"

    # LangGraph Postgres checkpointer lives in app_db (04 §1); its tables are
    # created via Alembic revisions in core-api's tree (10 §9 rule 4), never here.
    database_url: str = Field(
        default="postgresql://agent_service:dummy-password@localhost:5432/app_db",
        description="app_db DSN for the LangGraph checkpointer (plain DSN).",
    )
    redis_url: str = "redis://localhost:6379/0"

    # All clinical reads/writes go through FHIR via core-api's decision-checked
    # path (04 §1) — these are the S3 wiring targets.
    fhir_base_url: str = "http://localhost:8080/fhir"
    core_api_base_url: str = "http://localhost:8001"

    # AuthN (02).
    # Split-horizon (02): public issuer validated in `iss`; internal URL for JWKS fetch.
    keycloak_issuer: str = "https://localhost/auth/realms/medagent"
    keycloak_internal_url: str = "http://keycloak:8080/auth/realms/medagent"
    auth_disabled: bool = Field(
        default=False,
        description="Local bootstrapping escape hatch ONLY. Never true outside local dev.",
    )
    jwks_cache_ttl_seconds: int = 300

    # Anthropic (04 §4): pinned model ID, low clinical temperature. The pin is
    # verified against the API at startup from S3 (replacing the prototype's
    # unpinned model string).
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_temperature: float = 0.2

    # --- Agent reliability knobs (04 §2; hardening so a slow/looping run can never
    # hang the SSE stream or return a silent blank bubble). ---
    # Per-LLM-call request timeout + retry budget.
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    # Hard output cap per model turn. Raised from the prototype's 2048 so a
    # tool-heavy answer (e.g. a full record summary) isn't silently truncated.
    agent_max_tokens: int = 4096
    # Output cap for the OpenAI-compatible (Groq) path specifically. Groq's free
    # on-demand tier enforces an output-tokens-per-minute limit (OTPM ~1000) and
    # rejects a request whose max output exceeds it ("request too large"), so this
    # is kept under that ceiling; the fuller cap above applies to Anthropic. Raise
    # it once on a paid Groq tier.
    llm_openai_max_tokens: int = 900
    # ReAct super-step cap. The LangGraph default (25) let a broad request chain so
    # many tool calls it exhausted the budget with an empty final turn; a tighter
    # cap forces the model to answer sooner.
    agent_recursion_limit: int = 18
    # Per-FHIR-tool-call timeout (seconds) — a slow HAPI read can't stall the loop.
    tool_timeout_seconds: float = 8.0
    # Whole-run wall-clock ceiling; on breach we emit a graceful floor message.
    # Kept under the web client's 120 s abort so the floor/answer always wins.
    agent_run_timeout_seconds: float = 110.0

    # LLM mode: "live" (real Claude), "stub" (deterministic offline model — no API
    # calls), or "openai" (any OpenAI-compatible provider — Groq / OpenRouter /
    # Cerebras / Together — for a free key when the Anthropic quota is capped).
    # Stub mode lets the chat be demoed when the provider is unavailable.
    agent_llm_mode: str = "live"

    # Which model runs the tool-using ReAct loop (specific Q&A). "anthropic" (default)
    # routes it to Claude even when agent_llm_mode is "openai"/Groq — Claude streams
    # the post-tool answer token by token (no timeout floor) and needs fewer round
    # trips, so tool-heavy asks feel fast. The instant fast paths stay on the
    # configured model. Set to "configured" to run the loop on agent_llm_mode too.
    agent_react_provider: str = "anthropic"

    # OpenAI-compatible fallback provider (used when agent_llm_mode == "openai").
    # The model MUST support tool/function calling (the agent is a ReAct+tools
    # graph). Example (Groq): base_url=https://api.groq.com/openai/v1,
    # model=llama-3.3-70b-versatile.
    llm_openai_base_url: str = "https://api.groq.com/openai/v1"
    llm_openai_api_key: str = ""
    llm_openai_model: str = "qwen/qwen3.6-27b"   # Groq; follows tool-discipline for the ReAct loop
