import praw
from kafka import KafkaProducer
from kafka.errors import KafkaError
import json
import os
import time

# --- Configuration ---
# It's best practice to use environment variables for credentials
CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID')
CLIENT_SECRET = os.environ.get('REDDIT_CLIENT_SECRET')
USER_AGENT = "MyDataPipeline/1.0"
KAFKA_TOPIC = 'reddit_comments'
KAFKA_SERVER = 'localhost:9092'
KAFKA_CONNECT_RETRIES = 5
KAFKA_CONNECT_RETRY_DELAY_SECONDS = 5


def connect_kafka_producer():
    """Connect to Kafka with a short retry loop.

    docker-compose up -d returns as soon as the kafka container starts,
    but the broker takes a few seconds to finish coming up. Running this
    script right after (the README's documented workflow) reliably hit an
    unhandled KafkaError/connection-refused traceback with no indication
    of what to do about it. Retrying a few times with a delay covers that
    startup race without masking a genuinely misconfigured/absent broker.
    """
    last_error = None
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


# --- Kafka Producer Setup ---
# Serializes messages as JSON
producer = connect_kafka_producer()

# --- Reddit API Connection ---
reddit = praw.Reddit(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    user_agent=USER_AGENT
)

print("Connected to Reddit API. Streaming comments...")

# Stream comments from a popular subreddit like 'all'
for comment in reddit.subreddit('all').stream.comments(skip_existing=True):
    try:
        # Construct the message payload
        message = {
            'id': comment.id,
            'author': str(comment.author),
            'body': comment.body,
            'subreddit': str(comment.subreddit.display_name),
            'created_utc': comment.created_utc
        }

        # Send to Kafka
        producer.send(KAFKA_TOPIC, value=message)
        print(f"Sent comment {comment.id} to Kafka.")

    except Exception as e:
        print(f"An error occurred: {e}")
