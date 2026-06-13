from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Pydantic will automatically look for these names in your .env file
    # If it doesn't find them, it uses the default value.
    
    # App Settings

    APP_NAME: str = "Sabor Casero AI"
    DEBUG: bool = False
    
    # API Keys (Automatically pulled from env vars)
    deepseek_api_key: str = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = "https://api.deepseek.com"  # DEPRECATED — use LiteLLM's api_base via env var instead
    openai_api_key: str = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default=None, alias="ANTHROPIC_API_KEY")
    gemini_api_key: str = Field(default=None, alias="GEMINI_API_KEY")
    groq_api_key: str = Field(default=None, alias="GROQ_API_KEY")
    minimax_api_key: str = Field(default=None, alias="MINIMAX_API_KEY")
    minimax_group_id: str = Field(default=None, alias="MINIMAX_GROUP_ID")  # DEPRECATED — LiteLLM handles Minimax config internally

    # LLM Models by stage (LiteLLM format: "provider/model_name")
    llm_model_classifier: str = Field(default="deepseek/deepseek-v4-flash", alias="LLM_MODEL_CLASSIFIER")
    llm_model_retriever: str = Field(default="deepseek/deepseek-v4-flash", alias="LLM_MODEL_RETRIEVER")
    llm_model_thought_generator: str = Field(default="deepseek/deepseek-v4-flash", alias="LLM_MODEL_THOUGHT_GENERATOR")
    llm_model_action_planner: str = Field(default="deepseek/deepseek-v4-flash", alias="LLM_MODEL_ACTION_PLANNER")
    llm_model_summarizer: str = Field(default="deepseek/deepseek-v4-flash", alias="LLM_MODEL_SUMMARIZER")
    llm_model_response: str = Field(default="deepseek/deepseek-v4-flash", alias="LLM_MODEL_RESPONSE")

    # Paths
    # Using your specific Windows path as a default
    vector_db_path: str = Field(default=None, alias="VECTOR_DB_PATH")
    chroma_path: str = "chroma_db_storage"
    documents_path: str = Field(default=None, alias="DOCUMENTS_PATH")
    storage_path: str = "conversation_states.json"
    brand_voice_path: str = "data/templates/brand_templates.json"
    classifier_prompt_path:str = "prompts/classifier_intent/classifier_prompt_v4.0.txt"
    response_generation_prompt_path: str = "prompts/response/response_generator_prompt_v3.0.txt"
    reconcilier_prompt_path: str = "prompts/reconcilier_intent/reconcilier_prompt_v5.0.txt"
    # reconcilier_bypass_prompt_path: str = "prompts/reconcilier_intent/reconcilier_bypass_prompt_v1.0.txt"
    thought_generator_prompt_path: str = "prompts/thought_generator/thought_generator_prompt_v3.0.txt"
    action_planner_prompt_path: str = "prompts/action_planner/action_planner_prompt_v1.1.txt"
    sessions_path: str = "data/persistence/sessions.json"
    orders_path: str = "data/orders/"
    conversation_logs_path: str = "data/conversation_logs/"
    summaries_path: str = "data/summaries/"
    summary_prompt_path: str = "prompts/summary/summary_prompt_v1.0.txt"
    judge_prompt_path: str = "prompts/evaluation/judge_v1.0.txt"
    
    # OWL paths
    owl_ontology_path: str = "data/ontology/menu.ttl"
    router_prompt_path: str = "prompts/owl_router/router_prompt_v1.0.txt"

    # Planner prompt (LLM orchestrator)
    planner_prompt_path: str = "prompts/planner/system_prompt.txt"

    # Langfuse (read from .env by pydantic-settings, NOT os.environ)
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://us.cloud.langfuse.com", alias="LANGFUSE_HOST")

    # Feature flags
    use_order_flow_tracker: bool = True
    use_llm_planner: bool = False
    use_owl: bool = Field(default=True, alias="USE_OWL")

    # Evaluation
    evaluation_enabled: bool = Field(default=True, alias="EVALUATION_ENABLED")
    judge_model: str = Field(default="deepseek/deepseek-v4-flash", alias="JUDGE_MODEL")

    @property
    def prompt_fallback_map(self) -> dict[str, str]:
        """Map of prompt names to file paths for fallback when Langfuse is unavailable."""
        return {
            "classifier": self.classifier_prompt_path,
            "response": self.response_generation_prompt_path,
            "reconcilier": self.reconcilier_prompt_path,
            "thought-generator": self.thought_generator_prompt_path,
            "action-planner": self.action_planner_prompt_path,
            "summary": self.summary_prompt_path,
            "router": self.router_prompt_path,
            "judge": self.judge_prompt_path,
            "planner": self.planner_prompt_path,
        }

    # P1 — Pipeline validation (null/empty stage output guards)
    pipeline_validation_enabled: bool = True

    # P1 — Service type inference from UserPreferences
    service_type_inference_enabled: bool = True

    # P2 — Skill framework (orchestrator, registry, BaseSkill)
    skill_framework_enabled: bool = True

    # P3 — Checkpointing (save/restore per-skill, crash resume)
    checkpointing_enabled: bool = True

    # P4 — Semantic memory (entity extraction, ChromaDB memory_semantic collection)
    semantic_memory_enabled: bool = True

    # P5 — RAG v2 (multi-signal RRF pipeline with OWL, BM25, cross-encoder)
    rag_v2_enabled: bool = True

    # P6 — Skill orchestration (SkillOrchestrator loop replacing hardcoded pipeline)
    skills_enabled: bool = True

    # Models & Logic
    retriever_type: str = Field(default="vector_db", alias="RETRIEVER_WAY")
    llm_model: str = "deepseek-v4-flash"
    llm_temperature: float = 0.1
    certainty_threshold: float = 0.45

    @classmethod
    def for_test(cls, **overrides):
        """Create an isolated Settings instance for testing, ignoring .env.
        
        Uses explicit kwargs so pydantic-settings skips .env lookup for fields
        that are typed as ``str`` but default to ``None`` (the model's pattern
        for optional-via-env-only fields).
        """
        # Collect fields typed as str with default=None — those that need
        # an explicit value when running without a .env file.
        defaults = {}
        for field_name, field_info in cls.model_fields.items():
            if field_info.annotation is str and field_info.default is None:
                defaults[field_name] = "test-placeholder"
        defaults.update(overrides)
        return cls(**defaults)

    # This magic line tells Pydantic to read the .env file
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore" # Ignore extra env vars you might have
    )

    # _instance = None

    # def __new__(cls, *args, **kwargs):
    #     if cls._instance is None:
    #         cls._instance = super().__new__(cls)
    #     return cls._instance

# THE SINGLETON INSTANCE
settings = Settings()