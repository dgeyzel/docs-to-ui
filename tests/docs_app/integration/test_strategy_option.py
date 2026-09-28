import pytest
from d2u.generations.models import Generation
from plain.test import Client

from tests.helpers import read_fixture

PETSTORE = read_fixture("openapi/petstore-3.0.yaml")

pytestmark = pytest.mark.usefixtures("db")


def latest() -> Generation:
    generation = Generation.query.order_by("-id").first()
    assert generation is not None
    return generation


def test_the_form_hides_the_strategy_choice_by_default() -> None:
    html = Client().get("/").content.decode()

    assert 'name="strategy"' not in html
    assert "Model: Fake" in html
    assert "chosen in the Tuning app" in html


def test_a_submitted_strategy_is_ignored_unless_hybrid_is_enabled() -> None:
    Client().post(
        "/generations", data={"text": PETSTORE, "language": "", "strategy": "hybrid"}
    )

    assert latest().strategy == "llm"


def test_hybrid_can_be_chosen_when_enabled(settings) -> None:
    settings.GENERATIONS_ENABLE_HYBRID = True

    html = Client().get("/").content.decode()
    Client().post(
        "/generations", data={"text": PETSTORE, "language": "", "strategy": "hybrid"}
    )

    assert 'name="strategy"' in html
    assert latest().strategy == "hybrid"


def test_regenerate_keeps_the_strategy(settings) -> None:
    settings.GENERATIONS_ENABLE_HYBRID = True
    Client().post(
        "/generations", data={"text": PETSTORE, "language": "", "strategy": "hybrid"}
    )
    original = latest()

    Client().post(f"/generations/{original.id}/regenerate")

    assert latest().id != original.id
    assert latest().strategy == "hybrid"
