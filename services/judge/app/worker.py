"""SQS worker loop.

Long-polls the submissions queue, runs each job through the sandboxed runner,
and publishes the verdict. The judge holds no state: re-running a submission is
deterministic, and idempotency is enforced at the exam service's persistence
boundary (dedupe on submission_id), so a redelivered job is harmless.
"""

import logging

from pydantic import ValidationError

from app import sqs
from app.config import get_settings
from app.contracts import SubmissionJob
from app.runner import run

logger = logging.getLogger("judge.worker")


def process_message(body: str) -> None:
    try:
        job = SubmissionJob.model_validate_json(body)
    except ValidationError:
        logger.exception("dropping unparseable submission job")
        return
    logger.info("judging submission %s (%s)", job.submission_id, job.language)
    verdict = run(job)
    settings = get_settings()
    sqs.send(settings.verdicts_queue, verdict.model_dump_json())
    logger.info("submission %s -> %s", job.submission_id, verdict.summary_verdict)


def run_forever() -> None:
    settings = get_settings()
    logger.info("judge worker polling %s", settings.submissions_queue)
    while True:
        messages = sqs.receive(settings.submissions_queue)
        for message in messages:
            try:
                process_message(message["body"])
            except Exception:
                # Don't delete on failure — SQS will redeliver after the
                # visibility timeout. A poison message is dropped by the parse
                # guard in process_message.
                logger.exception("error processing message; leaving it queued")
                continue
            sqs.delete(settings.submissions_queue, message["receipt_handle"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
