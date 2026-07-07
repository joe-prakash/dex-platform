import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import requests


# ---------------------------------------------------
# LOAD AGENT MODULE
# ---------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

AGENT_FILE = (
    PROJECT_ROOT
    / "agent"
    / "agent.py"
)

spec = importlib.util.spec_from_file_location(
    "dex_agent",
    AGENT_FILE
)

agent = importlib.util.module_from_spec(spec)

sys.modules["dex_agent"] = agent

spec.loader.exec_module(agent)


# ---------------------------------------------------
# HTTP RETRY TESTS
# ---------------------------------------------------

class TestHttpRetryBehavior(unittest.TestCase):

    def setUp(self):

        agent.shutdown_requested = False

    def tearDown(self):

        agent.shutdown_requested = False

    @patch.object(agent, "wait_with_shutdown")
    @patch.object(agent.session, "post")
    def test_retryable_status_is_retried(
        self,
        mock_post,
        mock_wait
    ):

        first_response = MagicMock()
        first_response.status_code = 503
        first_response.raise_for_status.return_value = None

        second_response = MagicMock()
        second_response.status_code = 200
        second_response.raise_for_status.return_value = None
        second_response.json.return_value = {
            "status": "saved"
        }

        mock_post.side_effect = [
            first_response,
            second_response
        ]

        result = agent.post_json(
            "/telemetry",
            {"test": True},
            "telemetry"
        )

        self.assertEqual(
            result,
            {"status": "saved"}
        )

        self.assertEqual(
            mock_post.call_count,
            2
        )

        mock_wait.assert_called_once_with(2)

    @patch.object(agent, "wait_with_shutdown")
    @patch.object(agent.session, "post")
    def test_permanent_400_is_not_retried(
        self,
        mock_post,
        mock_wait
    ):

        response = MagicMock()
        response.status_code = 400

        http_error = requests.HTTPError(
            "400 Client Error"
        )

        http_error.response = response

        response.raise_for_status.side_effect = (
            http_error
        )

        mock_post.return_value = response

        result = agent.post_json(
            "/telemetry",
            {"test": True},
            "telemetry"
        )

        self.assertIsNone(result)

        self.assertEqual(
            mock_post.call_count,
            1
        )

        mock_wait.assert_not_called()

    @patch.object(agent, "wait_with_shutdown")
    @patch.object(agent.session, "post")
    def test_connection_failure_does_not_crash(
        self,
        mock_post,
        mock_wait
    ):

        mock_post.side_effect = (
            requests.ConnectionError(
                "API unavailable"
            )
        )

        result = agent.post_json(
            "/telemetry",
            {"test": True},
            "telemetry"
        )

        self.assertIsNone(result)

        self.assertEqual(
            mock_post.call_count,
            agent.MAX_RETRIES
        )

    @patch.object(agent, "wait_with_shutdown")
    @patch.object(agent.session, "post")
    def test_exponential_backoff_is_bounded(
        self,
        mock_post,
        mock_wait
    ):

        mock_post.side_effect = (
            requests.ConnectionError(
                "API unavailable"
            )
        )

        result = agent.post_json(
            "/telemetry",
            {"test": True},
            "telemetry"
        )

        self.assertIsNone(result)

        self.assertEqual(
            mock_post.call_count,
            3
        )

        self.assertEqual(
            mock_wait.call_args_list,
            [
                call(2),
                call(4)
            ]
        )


# ---------------------------------------------------
# EVENT CHECKPOINT TESTS
# ---------------------------------------------------

class TestEventCheckpointBehavior(unittest.TestCase):

    def setUp(self):

        agent.shutdown_requested = False

        self.original_checkpoints = (
            agent.event_checkpoints
        )

    def tearDown(self):

        agent.event_checkpoints = (
            self.original_checkpoints
        )

        agent.shutdown_requested = False

    @patch.object(agent, "save_event_checkpoints")
    @patch.object(agent, "post_json")
    @patch.object(agent, "collect_event_logs")
    def test_failed_post_does_not_advance_checkpoint(
        self,
        mock_collect,
        mock_post,
        mock_save
    ):

        old_checkpoint = {
            "System": 100,
            "Application": 200
        }

        new_checkpoint = {
            "System": 101,
            "Application": 201
        }

        events = [
            {
                "hostname": "TEST",
                "record_number": 101
            }
        ]

        agent.event_checkpoints = (
            old_checkpoint.copy()
        )

        mock_collect.return_value = (
            events,
            new_checkpoint
        )

        mock_post.return_value = None

        result = agent.send_event_logs()

        self.assertFalse(result)

        self.assertEqual(
            agent.event_checkpoints,
            old_checkpoint
        )

        mock_save.assert_not_called()

    @patch.object(agent, "save_event_checkpoints")
    @patch.object(agent, "post_json")
    @patch.object(agent, "collect_event_logs")
    def test_successful_post_advances_checkpoint(
        self,
        mock_collect,
        mock_post,
        mock_save
    ):

        old_checkpoint = {
            "System": 100,
            "Application": 200
        }

        new_checkpoint = {
            "System": 101,
            "Application": 201
        }

        events = [
            {
                "hostname": "TEST",
                "record_number": 101
            }
        ]

        agent.event_checkpoints = (
            old_checkpoint.copy()
        )

        mock_collect.return_value = (
            events,
            new_checkpoint
        )

        mock_post.return_value = {
            "status": "saved"
        }

        result = agent.send_event_logs()

        self.assertTrue(result)

        self.assertEqual(
            agent.event_checkpoints,
            new_checkpoint
        )

        mock_save.assert_called_once_with(
            new_checkpoint
        )

    @patch.object(agent, "save_event_checkpoints")
    @patch.object(agent, "post_json")
    @patch.object(agent, "collect_event_logs")
    def test_empty_event_batch_is_not_posted(
        self,
        mock_collect,
        mock_post,
        mock_save
    ):

        checkpoint = {
            "System": 100,
            "Application": 200
        }

        agent.event_checkpoints = (
            checkpoint.copy()
        )

        mock_collect.return_value = (
            [],
            checkpoint
        )

        result = agent.send_event_logs()

        self.assertTrue(result)

        mock_post.assert_not_called()

        mock_save.assert_called_once_with(
            checkpoint
        )


# ---------------------------------------------------
# CONFIGURATION AND SCHEDULING TESTS
# ---------------------------------------------------

class TestSchedulerConfiguration(unittest.TestCase):

    def test_collectors_have_separate_intervals(
        self
    ):

        self.assertEqual(
            agent.TELEMETRY_INTERVAL_SECONDS,
            30
        )

        self.assertEqual(
            agent.PROCESS_INTERVAL_SECONDS,
            60
        )

        self.assertEqual(
            agent.EVENT_LOG_INTERVAL_SECONDS,
            30
        )

        self.assertEqual(
            agent.INVENTORY_INTERVAL_SECONDS,
            3600
        )

        self.assertGreater(
            agent.INVENTORY_INTERVAL_SECONDS,
            agent.TELEMETRY_INTERVAL_SECONDS
        )

        self.assertGreater(
            agent.PROCESS_INTERVAL_SECONDS,
            agent.TELEMETRY_INTERVAL_SECONDS
        )

    def test_retry_configuration_is_bounded(
        self
    ):

        self.assertEqual(
            agent.MAX_RETRIES,
            3
        )

        self.assertEqual(
            agent.BACKOFF_BASE_SECONDS,
            2
        )

        expected_waits = [
            agent.BACKOFF_BASE_SECONDS
            * (2 ** (attempt - 1))
            for attempt in range(
                1,
                agent.MAX_RETRIES
            )
        ]

        self.assertEqual(
            expected_waits,
            [2, 4]
        )


# ---------------------------------------------------
# RUN TESTS
# ---------------------------------------------------

if __name__ == "__main__":

    unittest.main(
        verbosity=2
    )