import pytest
from d2u.registry.models import ModelConfig, RuntimeSettings
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
    response = Client().post(
        "/tuning/settings", data={"trace_backends": submitted, "default_judge": ""}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/tuning/settings?saved=1"
    assert stored() == saved


def test_the_saved_page_says_when_the_change_applies() -> None:
    html = Client().get("/tuning/settings?saved=1").content.decode()

    assert "Both apps use the new choice within 10 seconds." in html


@pytest.mark.usefixtures("langfuse_missing")
def test_langfuse_cannot_be_chosen_while_its_variables_are_missing() -> None:
    response = Client().post(
        "/tuning/settings",
        data={"trace_backends": ["native", "langfuse"], "default_judge": ""},
    )

    assert response.status_code == 200
    assert (
        "Langfuse can&#39;t be selected until LANGFUSE_BASE_URL, "
        "LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY are set."
    ) in response.content.decode()
    assert stored() == ["native"]


def test_unknown_backends_are_rejected() -> None:
    response = Client().post(
        "/tuning/settings", data={"trace_backends": ["zipkin"], "default_judge": ""}
    )

    assert response.status_code == 200
    assert stored() == ["native"]


def test_the_trace_viewer_links_to_settings() -> None:
    html = Client().get("/tuning/traces").content.decode()

    assert "Traces are sent to: Native." in html
    assert '<a href="/tuning/settings">Change in Settings</a>' in html


def test_the_default_judge_is_preselected_from_judging_models() -> None:
    claude = ModelConfig.query.get(name="Claude Sonnet 4.5")

    html = Client().get("/tuning/settings").content.decode()

    assert f'<option value="{claude.id}" selected>Claude Sonnet 4.5</option>' in html
    assert ">Gemini 3.8 Flash</option>" not in html


def test_saving_changes_the_default_judge() -> None:
    judge = ModelConfig(
        name="Judge B", litellm_model="openai/gpt-4o", enabled_for_judging=True
    )
    judge.create()

    Client().post(
        "/tuning/settings",
        data={"trace_backends": ["native"], "default_judge": str(judge.id)},
    )

    runtime = RuntimeSettings.load()
    assert runtime.default_judge_model is not None
    assert runtime.default_judge_model.id == judge.id


def test_a_model_not_enabled_for_judging_cannot_be_the_default_judge() -> None:
    gemini = ModelConfig.query.get(name="Gemini 3.8 Flash")

    response = Client().post(
        "/tuning/settings", data={"trace_backends": [], "default_judge": str(gemini.id)}
    )

    assert response.status_code == 200
    judge = RuntimeSettings.load().default_judge_model
    assert judge is not None
    assert judge.name == "Claude Sonnet 4.5"


def test_settings_warn_when_the_judge_is_the_docs_app_model() -> None:
    runtime = RuntimeSettings.load()
    runtime.active_model = runtime.default_judge_model
    runtime.update()

    html = Client().get("/tuning/settings").content.decode()

    assert "evals of that model grade themselves" in html
