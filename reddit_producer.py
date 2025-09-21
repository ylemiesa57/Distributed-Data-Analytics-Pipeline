import praw
from kafka import KafkaProducer
import json
import os

# --- Configuration ---
# It's best practice to use environment variables for credentials
CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID')
CLIENT_SECRET = os.environ.get('REDDIT_CLIENT_SECRET')
USER_AGENT = "MyDataPipeline/1.0"
KAFKA_TOPIC = 'reddit_comments'
KAFKA_SERVER = 'localhost:9092'

# --- Kafka Producer Setup ---
# Serializes messages as JSON
producer = KafkaProducer(
    bootstrap_servers=[KAFKA_SERVER],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

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
