"""Kafka/Redpanda ingestion consumer — completes the event-bus decoupling.

The producer in ingest.py emits an event per ingested symbol; this consumer is
the downstream side (e.g. a vector-ingestion or cache-warming worker). Kept
minimal: it logs events and can be extended to trigger re-embedding or alerts.
Requires the `kafka` extra (confluent-kafka).
"""

from __future__ import annotations

import structlog

from arthaai.config import get_settings

log = structlog.get_logger()


def consume(max_messages: int | None = None) -> int:
    from confluent_kafka import Consumer

    s = get_settings()
    consumer = Consumer(
        {
            "bootstrap.servers": s.kafka_bootstrap,
            "group.id": "arthaai-ingest-worker",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([s.ingest_topic])
    seen = 0
    try:
        while max_messages is None or seen < max_messages:
            msg = consumer.poll(1.0)
            if msg is None:
                if max_messages is not None:
                    break
                continue
            if msg.error():
                log.warning("consume_error", error=str(msg.error()))
                continue
            log.info(
                "ingest_event",
                symbol=msg.key().decode() if msg.key() else None,
                bars=msg.value().decode() if msg.value() else None,
            )
            seen += 1
    finally:
        consumer.close()
    return seen
