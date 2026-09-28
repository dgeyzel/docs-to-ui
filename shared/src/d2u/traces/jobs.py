import logging
from datetime import UTC, datetime, timedelta

from plain.jobs import Job, register_job
from plain.runtime import settings

from d2u.traces.models import TraceSpan

logger = logging.getLogger(__name__)


@register_job
class PruneTracesJob(Job):
    """Delete native spans older than `TRACES_RETENTION_DAYS`."""

    def default_queue(self) -> str:
        # Scheduled by the Docs app, whose worker serves this queue (SPEC §14).
        return "docs"

    def run(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=settings.TRACES_RETENTION_DAYS)
        deleted = TraceSpan.query.where(TraceSpan.start_time.lt(cutoff)).delete()
        logger.info("Pruned %s trace spans", deleted)
