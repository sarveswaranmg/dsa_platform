"""Background verdict consumer.

Runs as a lifespan task in dev: long-polls the verdicts queue and persists each
message through the idempotent `process_verdict_message`. The blocking boto3
calls are pushed to threads so the event loop stays free. Tests never start
this loop — they call `process_verdict_message` directly.
"""

import asyncio
import logging

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.messaging import sqs
from app.services.verdicts import process_verdict_message

logger = logging.getLogger("exam.consumer")


async def run_verdict_consumer(stop: asyncio.Event) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    logger.info("verdict consumer polling %s", settings.verdicts_queue)
    while not stop.is_set():
        messages = await asyncio.to_thread(
            sqs.receive, settings.verdicts_queue, wait_seconds=5
        )
        for message in messages:
            async with sessionmaker() as session:
                try:
                    await process_verdict_message(session, message["body"])
                except Exception:
                    logger.exception("failed to persist verdict; will retry")
                    continue
            await asyncio.to_thread(
                sqs.delete, settings.verdicts_queue, message["receipt_handle"]
            )
