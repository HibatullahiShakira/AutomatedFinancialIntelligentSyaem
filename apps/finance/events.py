"""
Finance event publisher — Step 12 of the implementation plan.

Every time a journal entry is posted, a canonical event is published to the
SQS event bus. If SQS is not configured (local dev), the event is logged
instead. This lets us verify event correctness before the infrastructure exists.

Canonical event envelope (all events across the system share this schema):
    event_id:       uuid-v4
    event_type:     string  (e.g. JOURNAL_ENTRY_POSTED)
    schema_version: "2.0"
    tenant_id:      uuid-v4
    user_id:        uuid-v4 | null
    timestamp:      ISO-8601 UTC
    correlation_id: uuid-v4
    causation_id:   uuid-v4
    source_service: "amss.finance"
    payload:        object (event-specific)
    metadata:       object (ip, user_agent, request_id)
"""
import json
import uuid
import logging
import os
from datetime import datetime, timezone as dt_tz

logger = logging.getLogger("amss.finance.events")

_SOURCE_SERVICE = "amss.finance"
_SCHEMA_VERSION = "2.0"


def _build_envelope(
    event_type: str,
    tenant_id,
    payload: dict,
    user_id=None,
    correlation_id: str = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": _SCHEMA_VERSION,
        "tenant_id": str(tenant_id),
        "user_id": str(user_id) if user_id else None,
        "timestamp": datetime.now(dt_tz.utc).isoformat(),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "causation_id": str(uuid.uuid4()),
        "source_service": _SOURCE_SERVICE,
        "payload": payload,
        "metadata": {},
    }


def _publish(envelope: dict) -> None:
    """
    Publish an event envelope to SQS FIFO queue, or log it if SQS is not
    configured. Publishing failures are raised so the caller can decide
    whether to suppress them (best-effort) or let them propagate.
    """
    queue_url = os.environ.get("SQS_EVENT_BUS_URL")

    if not queue_url:
        logger.info(
            "EVENT [no-SQS] %s | tenant=%s | %s",
            envelope["event_type"],
            envelope["tenant_id"],
            json.dumps(envelope, default=str),
        )
        return

    import boto3
    sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(envelope, default=str),
        MessageGroupId=envelope["tenant_id"],
        MessageDeduplicationId=envelope["event_id"],
    )
    logger.info(
        "Published %s (%s) for tenant %s",
        envelope["event_type"],
        envelope["event_id"],
        envelope["tenant_id"],
    )


def publish_journal_entry_posted(entry) -> None:
    """
    Publish JOURNAL_ENTRY_POSTED event.

    Payload includes full line detail so downstream consumers (tax engine,
    event store, cash flow forecaster) can act without a separate DB query.
    """
    lines_payload = [
        {
            "account_id": str(line.account_id),
            "account_code": line.account.code,
            "account_name": line.account.name,
            "account_type": line.account.account_type,
            "debit": str(line.debit),
            "credit": str(line.credit),
        }
        for line in entry.lines.select_related("account").all()
    ]

    envelope = _build_envelope(
        event_type="JOURNAL_ENTRY_POSTED",
        tenant_id=entry.tenant_id,
        user_id=entry.posted_by_id,
        payload={
            "journal_entry_id": str(entry.id),
            "reference_number": entry.reference_number,
            "date": entry.date.isoformat(),
            "source": entry.source,
            "description": entry.description,
            "total_amount": str(entry.total_debits),
            "lines": lines_payload,
        },
    )
    _publish(envelope)
