import json
import os
import time
from typing import Callable, Optional

import praw
from kafka import KafkaProducer
from kafka.errors import KafkaError

# --- Configuration ---
# It's best practice to use environment variables for credentials
CLIENT_ID: Optional[str] = os.environ.get('REDDIT_CLIENT_ID')
CLIENT_SECRET: Optional[str] = os.environ.get('REDDIT_CLIENT_SECRET')
USER_AGENT: str = "MyDataPipeline/1.0"
KAFKA_TOPIC: str = 'reddit_comments'
KAFKA_SERVER: str = 'localhost:9092'
KAFKA_CONNECT_RETRIES: int = 5
KAFKA_CONNECT_RETRY_DELAY_SECONDS: int = 5


def connect_kafka_producer() -> KafkaProducer:
    """Connect to Kafka with a short retry loop.

    docker-compose up -d returns as soon as the kafka container starts,
    but the broker takes a few seconds to finish coming up. Running this
    script right after (the README's documented workflow) reliably hit an
    unhandled KafkaError/connection-refused traceback with no indication
    of what to do about it. Retrying a few times with a delay covers that
    startup race without masking a genuinely misconfigured/absent broker.
    """
    last_error: Optional[KafkaError] = None
    for attempt in range(1, KAFKA_CONNECT_RETRIES + 1):
        try:
            return KafkaProducer(
                bootstrap_servers=[KAFKA_SERVER],
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
        except KafkaError as e:
            last_error = e
            print(
                f"Could not connect to Kafka at {KAFKA_SERVER} "
                f"(attempt {attempt}/{KAFKA_CONNECT_RETRIES}): {e}"
            )
            if attempt < KAFKA_CONNECT_RETRIES:
                time.sleep(KAFKA_CONNECT_RETRY_DELAY_SECONDS)
    raise RuntimeError(
        f"Giving up connecting to Kafka at {KAFKA_SERVER} after "
        f"{KAFKA_CONNECT_RETRIES} attempts. Is `docker-compose up -d` "
        "running and has the kafka container finished starting?"
    ) from last_error


def _on_send_error(comment_id: str) -> Callable[[Optional[Exception]], None]:
    """Errback for producer.send()'s returned future.

    KafkaProducer.send() is async: it enqueues the message and returns a
    FutureRecordMetadata immediately, so a broker-side failure (topic
    down, message too large, leader not available, etc.) never raises
    from the send() call itself and was previously never surfaced
    anywhere -- the try/except around send() only ever caught
    synchronous errors (e.g. serialization failures before the message
    was even queued). Without this errback, delivery failures were
    silently dropped with a misleading "Sent comment ... to Kafka" log
    line still printed right after the send() call.
    """
    def _callback(excp: Optional[Exception]) -> None:
        print(f"Failed to deliver comment {comment_id} to Kafka: {excp}")
    return _callback


def validate_required_env_vars() -> None:
    """Validate that required environment variables are set.

    Raises SystemExit if CLIENT_ID or CLIENT_SECRET are not configured,
    with a clear error message guiding the user to set them.
    """
    missing_vars = []
    if not CLIENT_ID:
        missing_vars.append('REDDIT_CLIENT_ID')
    if not CLIENT_SECRET:
        missing_vars.append('REDDIT_CLIENT_SECRET')

    if missing_vars:
        raise SystemExit(
            f"Missing required environment variables: {', '.join(missing_vars)}\n"
            "Please set these variables before running this script. "
            "See the README for instructions on obtaining Reddit API credentials."
        )


def main() -> None:
    """Stream Reddit comments and publish them to Kafka.

    Connects to the Reddit API, streams comments from r/all, constructs
    JSON messages containing comment metadata, and publishes them to a
    Kafka topic. Handles connection retries, delivery errors, and graceful
    shutdown (Ctrl+C) by flushing any queued messages before closing.

    Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET environment variables.
    """
    # --- Validate Configuration ---
    validate_required_env_vars()

    # --- Kafka Producer Setup ---
    # Serializes messages as JSON
    producer: KafkaProducer = connect_kafka_producer()

    # --- Reddit API Connection ---
    reddit: praw.Reddit = praw.Reddit(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        user_agent=USER_AGENT
    )

    print("Connected to Reddit API. Streaming comments...")

    # Stream comments from a popular subreddit like 'all'. Wrapped in
    # try/finally so that Ctrl+C (the documented way to stop this
    # indefinitely-running script) doesn't just kill the process outright:
    # producer.send() only queues messages in an in-memory buffer, so any
    # comments queued but not yet flushed to the broker at the moment of
    # interrupt were previously silently lost with no delivery attempt at
    # all, rather than just missing the errback's failure log.
    try:
        for comment in reddit.subreddit('all').stream.comments(skip_existing=True):
            try:
                # Construct the message payload
                message: dict[str, object] = {
                    'id': comment.id,
                    'author': str(comment.author),
                    'body': comment.body,
                    'subreddit': str(comment.subreddit.display_name),
                    'created_utc': comment.created_utc
                }

                # Send to Kafka. producer.send() only queues the message; actual
                # delivery success/failure is reported asynchronously, so attach
                # an errback rather than trusting that no exception means it
                # was delivered.
                future = producer.send(KAFKA_TOPIC, value=message)
                future.add_errback(_on_send_error(comment.id))
                print(f"Queued comment {comment.id} for Kafka.")

            except Exception as e:
                print(f"An error occurred: {e}")
    except KeyboardInterrupt:
        print("Interrupted. Flushing any comments still queued for Kafka before exiting...")
    finally:
        producer.flush(timeout=10)
        producer.close(timeout=10)


if __name__ == "__main__":
    main()
