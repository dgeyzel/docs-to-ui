import pytest
from plain.http import BadRequestError400

from app.api.waiting import parse_wait


@pytest.mark.parametrize(("raw", "seconds"), [(None, 0), ("", 0), ("0", 0), ("5", 5)])
def test_parse_wait_reads_whole_seconds(raw: str | None, seconds: int) -> None:
    assert parse_wait(raw) == seconds


def test_parse_wait_is_capped_by_the_setting(settings) -> None:
    settings.API_MAX_WAIT_S = 10

    assert parse_wait("600") == 10


@pytest.mark.parametrize("raw", ["1.5", "soon", "-3"])
def test_parse_wait_refuses_other_values(raw: str) -> None:
    with pytest.raises(BadRequestError400, match="wait"):
        parse_wait(raw)
