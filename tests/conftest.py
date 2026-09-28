from pathlib import Path

import pytest

from tests.helpers import FIXTURES_DIR


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(autouse=True)
def fake_active_model(request: pytest.FixtureRequest) -> None:
    """Make the fake model the Docs app's active model in database tests.

    Tests never call a real LLM (AGENTS.md §8.3). The seeded models stay in
    the registry; only the active choice changes.
    """
    if not {"db", "isolated_db"} & set(request.fixturenames):
        return
    request.getfixturevalue("db" if "db" in request.fixturenames else "isolated_db")
    from tests.helpers import activate_fake_model

    activate_fake_model()
