GENERATIONS_MAX_INPUT_BYTES: int = 5242880
GENERATIONS_TIMEOUT_S: int = 900

LLM_MODEL: str = "gemini/gemini-3.8-flash"
LLM_THINKING_LEVEL: str = "medium"
LLM_JUDGE_MODEL: str = "gemini/gemini-3.8-flash"
LLM_JUDGE_THINKING_LEVEL: str = "high"
LLM_PROGRAM_VERSION: str = "baseline"
LLM_BATCH_TOKEN_BUDGET: int = 60000
LLM_BATCH_MAX_OPERATIONS: int = 25
LLM_MAX_CONCURRENCY: int = 4
# DummyLM fixture file used when LLM_MODEL is "fake" (tests only).
LLM_FAKE_RESPONSES: str = ""
