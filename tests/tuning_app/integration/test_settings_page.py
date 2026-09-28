import pytest
from d2u.registry.models import RuntimeSettings
from plain.test import Client

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def langfuse_configured(settings) -> None:
    settings.TELEMETRY_LANGFUSE_BASE_URL = "https://lf.example"
    settings.TELEMETRY_LANGFUSE_PUBLIC_KEY = "pk"
    settings.TELEMETRY_LANGFUSE_SECRET_KEY = "sk"
    settings.TELEMETRY_LANGFUSE_PROJECT_ID = "p"


@pytest.fixture
def langfuse_missing(settings) -> None:
    settings.TELEMETRY_LANGFUSE_BASE_URL = ""
    settings.TELEMETRY_LANGFUSE_PUBLIC_KEY = ""
    settings.TELEMETRY_LANGFUSE_SECRET_KEY = ""
    settings.TELEMETRY_LANGFUSE_PROJECT_ID = "p"


def stored() -> list[str]:
    return RuntimeSettings.load().trace_backends


@pytest.mark.usefixtures("langfuse_missing")
def test_settings_page_shows_the_current_choice_and_what_langfuse_needs() -> None:
    response = Client().get("/tuning/settings")

    html = response.content.decode()
    assert response.status_code == 200
    assert 'href="/tuning/settings"' in html
    assert 'value="native"\n                    checked' in html
    assert "disabled" in html
    assert (
        "Set LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY in both apps'"
        in html
    )


@pytest.mark.usefixtures("langfuse_configured")
def test_langfuse_can_be_chosen_once_configured() -> None:
    html = Client().get("/tuning/settings").content.decode()

    assert "disabled" not in html


@pytest.mark.usefixtures("langfuse_configured")
@pytest.mark.parametrize(
    ("submitted", "saved"),
    [
        (["langfuse", "native"], ["native", "langfuse"]),
        (["langfuse"], ["langfuse"]),
        ([], []),
    ],
)
def test_saving_stores_any_subset(submitted: list[str], saved: list[str]) -> None:
    response = Client().post("/tuning/settings", data={"trace_backends": submitted})

    assert response.status_code == 302
    assert response.headers["Location"] == "/tuning/settings?saved=1"
    assert stored() == saved


def test_the_saved_page_says_when_the_change_applies() -> None:
    html = Client().get("/tuning/settings?saved=1").content.decode()

    assert "Both apps use the new choice within 10 seconds." in html


@pytest.mark.usefixtures("langfuse_missing")
def test_langfuse_cannot_be_chosen_while_its_variables_are_missing() -> None:
    response = Client().post(
        "/tuning/settings", data={"trace_backends": ["native", "langfuse"]}
    )

    assert response.status_code == 200
    assert (
        "Langfuse can&#39;t be selected until LANGFUSE_BASE_URL, "
        "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY are set."
    ) in response.content.decode()
    assert stored() == ["native"]


def test_unknown_backends_are_rejected() -> None:
    response = Client().post("/tuning/settings", data={"trace_backends": ["zipkin"]})

    assert response.status_code == 200
    assert stored() == ["native"]


def test_the_trace_viewer_links_to_settings() -> None:
    html = Client().get("/tuning/traces").content.decode()

    assert "Traces are sent to: Native." in html
    assert '<a href="/tuning/settings">Change in Settings</a>' in html
