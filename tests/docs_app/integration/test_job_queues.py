"""Each app's worker serves only its own queue (SPEC §14)."""

import pytest
from d2u.telemetry.jobs import MirrorFeedbackJob
from d2u.traces.jobs import PruneTracesJob
from plain.jobs import Job
from plain.jobs.models import JobRequest
from plain.test import Client

from app.generate.jobs import GenerateDocJob
from tests.helpers import read_fixture


@pytest.mark.usefixtures("db")
def test_generations_are_queued_for_the_docs_worker() -> None:
    Client().post(
        "/generations",
        data={"text": read_fixture("openapi/petstore-3.0.yaml"), "language": ""},
    )

    request = JobRequest.query.get(job_class="app.generate.jobs.GenerateDocJob")
    assert request.queue == "docs"


@pytest.mark.parametrize(
    "job",
    [
        GenerateDocJob(1),
        PruneTracesJob(),
        MirrorFeedbackJob(
            backend="langfuse",
            trace_id="a" * 32,
            generation_id=1,
            operation_id="",
            score=1,
            comment="",
        ),
    ],
)
def test_docs_app_jobs_use_the_docs_queue(job: Job) -> None:
    assert job.default_queue() == "docs"
