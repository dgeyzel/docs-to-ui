"""Test connection for a registered model (SPEC §7). Plain-free."""

from d2u.generation.client import FakeResponses, ModelSpec, Usage, complete_structured
from d2u.generation.exceptions import OutputValidationError
from d2u.generation.prompts import connection_check_messages
from d2u.schemas.generated import ConnectionCheck


def check_connection(model: ModelSpec, *, fake: FakeResponses | None = None) -> Usage:
    """Make one minimal structured-output call and return what it cost.

    Raises:
        LLMConfigurationError: Bad parameters or a missing key.
        ProviderError: The provider rejected the call.
        OutputValidationError: The answer didn't validate, or wasn't `ok`.
    """
    result = complete_structured(
        model=model,
        messages=connection_check_messages(),
        response_model=ConnectionCheck,
        fake=fake,
    )
    if not result.value.ok:
        raise OutputValidationError("The model answered, but not with ok=true.")
    return result.usage
