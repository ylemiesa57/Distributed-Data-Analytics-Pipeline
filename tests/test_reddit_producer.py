"""Unit tests for reddit_producer.py.

This module used to run its Kafka/Reddit connection code at import time
(module-level `producer = connect_kafka_producer()` and
`reddit = praw.Reddit(...)`), which meant simply importing the file for
testing would try to open a real network connection. It's now wrapped in
main(), guarded by `if __name__ == "__main__":`, so the module can be
imported safely and its logic tested in isolation -- no live Kafka broker
or Reddit credentials required. Running the script directly is unchanged
(main() still does exactly what used to run at module level).
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kafka.errors import KafkaError

import reddit_producer as rp


class TestConnectKafkaProducer(unittest.TestCase):
    def test_returns_producer_on_first_success(self):
        sentinel = mock.Mock()
        with mock.patch.object(rp, "KafkaProducer", return_value=sentinel) as m:
            result = rp.connect_kafka_producer()
        self.assertIs(result, sentinel)
        self.assertEqual(m.call_count, 1)

    def test_retries_then_succeeds(self):
        sentinel = mock.Mock()
        with mock.patch.object(
            rp, "KafkaProducer",
            side_effect=[KafkaError("no broker"), KafkaError("no broker"), sentinel],
        ) as m, mock.patch.object(rp.time, "sleep") as sleep_mock:
            result = rp.connect_kafka_producer()
        self.assertIs(result, sentinel)
        self.assertEqual(m.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)  # slept between attempts 1->2 and 2->3, not after success

    def test_gives_up_after_configured_retry_count_and_chains_last_error(self):
        original_error = KafkaError("still no broker")
        with mock.patch.object(rp, "KafkaProducer", side_effect=original_error) as m, \
             mock.patch.object(rp.time, "sleep") as sleep_mock:
            with self.assertRaises(RuntimeError) as ctx:
                rp.connect_kafka_producer()
        self.assertEqual(m.call_count, rp.KAFKA_CONNECT_RETRIES)
        self.assertEqual(sleep_mock.call_count, rp.KAFKA_CONNECT_RETRIES - 1)
        self.assertIs(ctx.exception.__cause__, original_error)


class TestValidateRequiredEnvVars(unittest.TestCase):
    def test_no_error_when_both_vars_set(self):
        # Test that validation passes when credentials are set
        with mock.patch.object(rp, "CLIENT_ID", "test_id"), \
             mock.patch.object(rp, "CLIENT_SECRET", "test_secret"):
            # Should not raise
            rp.validate_required_env_vars()

    def test_raises_when_client_id_missing(self):
        with mock.patch.object(rp, "CLIENT_ID", None), \
             mock.patch.object(rp, "CLIENT_SECRET", "test_secret"):
            with self.assertRaises(SystemExit) as ctx:
                rp.validate_required_env_vars()
            self.assertIn("REDDIT_CLIENT_ID", str(ctx.exception))

    def test_raises_when_client_secret_missing(self):
        with mock.patch.object(rp, "CLIENT_ID", "test_id"), \
             mock.patch.object(rp, "CLIENT_SECRET", None):
            with self.assertRaises(SystemExit) as ctx:
                rp.validate_required_env_vars()
            self.assertIn("REDDIT_CLIENT_SECRET", str(ctx.exception))

    def test_raises_when_both_missing(self):
        with mock.patch.object(rp, "CLIENT_ID", None), \
             mock.patch.object(rp, "CLIENT_SECRET", None):
            with self.assertRaises(SystemExit) as ctx:
                rp.validate_required_env_vars()
            self.assertIn("REDDIT_CLIENT_ID", str(ctx.exception))
            self.assertIn("REDDIT_CLIENT_SECRET", str(ctx.exception))


class TestOnSendErrorCallback(unittest.TestCase):
    def test_callback_prints_the_comment_id_and_exception(self):
        callback = rp._on_send_error("abc123")
        with mock.patch("builtins.print") as print_mock:
            callback(KafkaError("delivery failed"))
        print_mock.assert_called_once()
        message = print_mock.call_args[0][0]
        self.assertIn("abc123", message)
        self.assertIn("delivery failed", message)

    def test_each_call_captures_its_own_comment_id(self):
        # _on_send_error is called fresh per comment inside the streaming
        # loop, so two callbacks for two different comments must not share
        # state (e.g. via a mutable default or module-level variable).
        cb_a = rp._on_send_error("aaa")
        cb_b = rp._on_send_error("bbb")
        with mock.patch("builtins.print") as print_mock:
            cb_a(KafkaError("x"))
            cb_b(KafkaError("y"))
        first_call, second_call = print_mock.call_args_list
        self.assertIn("aaa", first_call[0][0])
        self.assertIn("bbb", second_call[0][0])


class TestMain(unittest.TestCase):
    """main()'s per-comment streaming loop had no coverage at all: message
    construction from the comment object, the inner per-comment try/except,
    and the outer KeyboardInterrupt handling that's supposed to still flush
    and close the producer. All exercised here via mocks -- no live Kafka
    broker or Reddit credentials needed.
    """

    def _make_comment(self, comment_id, author="alice", body="hello",
                       subreddit_name="python", created_utc=1700000000.0):
        comment = mock.Mock()
        comment.id = comment_id
        comment.author = author
        comment.body = body
        comment.subreddit.display_name = subreddit_name
        comment.created_utc = created_utc
        return comment

    def _patch_main(self, comments_or_exc):
        """Patch connect_kafka_producer and praw.Reddit so main() streams
        the given comments (or raises the given exception mid-stream) from
        reddit.subreddit('all').stream.comments(...), and return the mock
        producer used so assertions can inspect calls made against it.
        """
        producer = mock.Mock()
        producer.send.return_value = mock.Mock()

        def comment_stream(**kwargs):
            if isinstance(comments_or_exc, BaseException):
                raise comments_or_exc
            yield from comments_or_exc

        reddit = mock.Mock()
        reddit.subreddit.return_value.stream.comments.side_effect = comment_stream

        connect_patch = mock.patch.object(
            rp, "connect_kafka_producer", return_value=producer
        )
        reddit_patch = mock.patch.object(rp.praw, "Reddit", return_value=reddit)
        validate_patch = mock.patch.object(rp, "validate_required_env_vars")
        return producer, connect_patch, reddit_patch, validate_patch

    def test_sends_each_comment_and_flushes_on_normal_completion(self):
        comments = [self._make_comment("c1"), self._make_comment("c2")]
        producer, connect_patch, reddit_patch, validate_patch = self._patch_main(comments)
        with connect_patch, reddit_patch, validate_patch:
            rp.main()

        self.assertEqual(producer.send.call_count, 2)
        first_call, second_call = producer.send.call_args_list
        self.assertEqual(first_call.args[0], rp.KAFKA_TOPIC)
        self.assertEqual(
            first_call.kwargs["value"],
            {
                "id": "c1",
                "author": "alice",
                "body": "hello",
                "subreddit": "python",
                "created_utc": 1700000000.0,
            },
        )
        self.assertEqual(second_call.kwargs["value"]["id"], "c2")
        # Both sent futures got an errback attached.
        self.assertEqual(producer.send.return_value.add_errback.call_count, 2)
        producer.flush.assert_called_once_with(timeout=10)
        producer.close.assert_called_once_with(timeout=10)

    def test_per_comment_exception_does_not_abort_the_stream(self):
        good_comment = self._make_comment("c_ok")
        bad_comment = self._make_comment("c_bad")
        # str(comment.subreddit.display_name) raising simulates a payload
        # construction failure for one comment (e.g. a transient API/attr
        # error), which should be caught and logged per-comment rather than
        # killing the whole streaming loop.
        type(bad_comment.subreddit).display_name = mock.PropertyMock(
            side_effect=RuntimeError("boom")
        )
        producer, connect_patch, reddit_patch, validate_patch = self._patch_main(
            [bad_comment, good_comment]
        )
        with connect_patch, reddit_patch, validate_patch:
            rp.main()

        # Only the good comment made it to producer.send; the bad one was
        # caught and logged, and the loop continued to the next comment.
        self.assertEqual(producer.send.call_count, 1)
        self.assertEqual(producer.send.call_args.kwargs["value"]["id"], "c_ok")
        producer.flush.assert_called_once_with(timeout=10)
        producer.close.assert_called_once_with(timeout=10)

    def test_keyboard_interrupt_still_flushes_and_closes_producer(self):
        producer, connect_patch, reddit_patch, validate_patch = self._patch_main(
            KeyboardInterrupt()
        )
        with connect_patch, reddit_patch, validate_patch:
            # Should not propagate -- main() catches KeyboardInterrupt itself
            # so Ctrl+C exits cleanly rather than printing a traceback.
            rp.main()

        producer.send.assert_not_called()
        producer.flush.assert_called_once_with(timeout=10)
        producer.close.assert_called_once_with(timeout=10)


if __name__ == "__main__":
    unittest.main()
