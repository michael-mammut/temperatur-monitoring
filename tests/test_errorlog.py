import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.errorlog import CATEGORY_HARDWARE, MERGE_WINDOW_SECONDS, record_exception


class RecordExceptionTests(unittest.TestCase):
    def test_none_error_log_is_a_safe_no_op(self):
        record_exception(None, CATEGORY_HARDWARE, ValueError("boom"))  # must not raise

    def test_records_exception_type_name_as_code_and_message(self):
        fake_log = MagicMock()
        record_exception(fake_log, CATEGORY_HARDWARE, ValueError("sensor missing"))

        fake_log.record.assert_called_once_with({
            'category': CATEGORY_HARDWARE,
            'code': 'ValueError',
            'message': 'sensor missing',
        }, merge_within_seconds=MERGE_WINDOW_SECONDS)

    def test_repeats_are_merged_within_12_hours(self):
        self.assertEqual(MERGE_WINDOW_SECONDS, 12 * 60 * 60)

    def test_long_message_is_truncated(self):
        fake_log = MagicMock()
        record_exception(fake_log, CATEGORY_HARDWARE, RuntimeError("x" * 500))

        recorded = fake_log.record.call_args[0][0]
        self.assertLessEqual(len(recorded['message']), 200)

    def test_disabled_category_is_not_recorded(self):
        fake_log = MagicMock()
        fake_logging_settings = MagicMock()
        fake_logging_settings.is_enabled.return_value = False

        record_exception(fake_log, CATEGORY_HARDWARE, ValueError("sensor missing"),
                          logging_settings=fake_logging_settings)

        fake_logging_settings.is_enabled.assert_called_once_with(CATEGORY_HARDWARE)
        fake_log.record.assert_not_called()

    def test_enabled_category_is_recorded(self):
        fake_log = MagicMock()
        fake_logging_settings = MagicMock()
        fake_logging_settings.is_enabled.return_value = True

        record_exception(fake_log, CATEGORY_HARDWARE, ValueError("sensor missing"),
                          logging_settings=fake_logging_settings)

        fake_log.record.assert_called_once()

    def test_no_logging_settings_means_always_recorded(self):
        """Backward compatible: callers that don't pass logging_settings
        (e.g. existing code before this feature) must keep working exactly
        as before - everything gets recorded."""
        fake_log = MagicMock()
        record_exception(fake_log, CATEGORY_HARDWARE, ValueError("sensor missing"))

        fake_log.record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
