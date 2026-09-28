GENERATIONS_MAX_INPUT_BYTES: int = 1048576
GENERATIONS_TIMEOUT_S: int = 900
# Parallel LLM calls when an input is split, or for hybrid batches.
GENERATIONS_MAX_CONCURRENCY: int = 4
# Offer the hybrid strategy (parsed structure, LLM prose) in the Docs app.
GENERATIONS_ENABLE_HYBRID: bool = False
# Fixture file for the fake model (tests only), relative to the repository root.
GENERATIONS_FAKE_RESPONSES: str = ""
