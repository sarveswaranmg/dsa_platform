"""SQS worker loop for the judge-gen lane (differential testing during AI
question generation — Phase 2 Slice 2).

A completely separate process from the judge-live worker (`worker.py`,
untouched by this addition) polling a different queue — this is what makes
judge-gen naturally lower priority than judge-live: heavy generation
traffic runs on its own consumer and can never delay a candidate's real
submission. Same shape as `worker.py` otherwise (long-poll, run, publish,
delete-only-on-success).
"""

import logging
import uuid

from pydantic import ValidationError

from app import sqs
from app.config import get_settings
from app.gen_contracts import DiffJob
from app.gen_runner import run_diff
from app.logging import set_request_id

logger = logging.getLogger("judge.gen_worker")


def process_message(body: str) -> None:
    try:
        job = DiffJob.model_validate_json(body)
    except ValidationError:
        logger.exception("dropping unparseable diff job")
        return
    set_request_id(job.request_id or str(uuid.uuid4()))
    logger.info("judging diff job %s attempt %s (%s)", job.job_id, job.attempt, job.language)
    result = run_diff(job)
    settings = get_settings()
    # Slice 3's on-demand variant supplies its own throwaway reply queue so
    # it never contends with the persistent async consumer.
    sqs.send(job.results_queue or settings.gen_results_queue, result.model_dump_json())
    logger.info("diff job %s -> %.0f%% agreement", job.job_id, result.agreement_pct * 100)


def run_forever() -> None:
    settings = get_settings()
    logger.info("judge-gen worker polling %s", settings.gen_jobs_queue)
    while True:
        messages = sqs.receive(settings.gen_jobs_queue)
        for message in messages:
            try:
                process_message(message["body"])
            except Exception:
                logger.exception("error processing diff job; leaving it queued")
                continue
            sqs.delete(settings.gen_jobs_queue, message["receipt_handle"])


if __name__ == "__main__":
    from app.logging import configure_logging

    configure_logging("judge-gen")
    run_forever()
