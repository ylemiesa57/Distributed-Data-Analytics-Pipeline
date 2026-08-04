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


if __name__ == "__main__":
    unittest.main()
