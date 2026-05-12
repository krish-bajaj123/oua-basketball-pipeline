"""Kafka -> S3 raw landing consumer.

Subscribes to the three usports.* topics and writes each message as a
single JSON line into S3 partitioned by topic and date:
    s3://<bucket>/raw/<topic>/dt=YYYY-MM-DD/<uuid>.jsonl

Files are flushed when they reach BATCH_SIZE messages or BATCH_SECS
elapses, whichever comes first.
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("consumer")

TOPICS = ["usports.team_season.raw", "usports.player_profile.raw", "usports.game.raw"]
BUCKET = os.environ["S3_BUCKET"]
PREFIX = os.environ.get("S3_PREFIX", "raw")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "200"))
BATCH_SECS = int(os.environ.get("BATCH_SECS", "30"))


def make_consumer() -> KafkaConsumer:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
    for attempt in range(1, 31):
        try:
            return KafkaConsumer(
                *TOPICS,
                bootstrap_servers=bootstrap,
                group_id=os.environ.get("CONSUMER_GROUP", "usports-s3-sink"),
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            )
        except NoBrokersAvailable:
            log.info("kafka not ready, retry %d", attempt)
            time.sleep(2)
    raise RuntimeError("kafka unreachable")


def make_s3():
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
    )


class Batch:
    def __init__(self, topic: str):
        self.topic = topic
        self.buf = io.StringIO()
        self.count = 0
        self.opened_at = time.monotonic()

    def add(self, value: dict) -> None:
        self.buf.write(json.dumps(value, default=str))
        self.buf.write("\n")
        self.count += 1

    def should_flush(self) -> bool:
        return self.count >= BATCH_SIZE or (time.monotonic() - self.opened_at) >= BATCH_SECS


def flush(s3, batch: Batch) -> None:
    if batch.count == 0:
        return
    dt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{PREFIX}/{batch.topic}/dt={dt}/{uuid.uuid4().hex}.jsonl"
    s3.put_object(Bucket=BUCKET, Key=key, Body=batch.buf.getvalue().encode("utf-8"),
                  ContentType="application/x-ndjson")
    log.info("flushed %d -> s3://%s/%s", batch.count, BUCKET, key)


def main() -> int:
    s3 = make_s3()
    consumer = make_consumer()
    batches: dict[str, Batch] = {t: Batch(t) for t in TOPICS}
    last_tick = time.monotonic()
    log.info("consuming %s -> s3://%s/%s/", TOPICS, BUCKET, PREFIX)

    while True:
        msgs = consumer.poll(timeout_ms=1000)
        for tp, records in msgs.items():
            for r in records:
                batches[tp.topic].add(r.value)
        # Flush full or stale batches
        for t, b in list(batches.items()):
            if b.should_flush():
                flush(s3, b)
                batches[t] = Batch(t)
        if time.monotonic() - last_tick > 60:
            sizes = {t: b.count for t, b in batches.items()}
            log.info("alive — pending=%s", sizes)
            last_tick = time.monotonic()


if __name__ == "__main__":
    raise SystemExit(main())
