import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.errorlog import CATEGORY_HARDWARE, record_exception


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
        })

    def test_long_message_is_truncated(self):
        fake_log = MagicMock()
        record_exception(fake_log, CATEGORY_HARDWARE, RuntimeError("x" * 500))

        recorded = fake_log.record.call_args[0][0]
        self.assertLessEqual(len(recorded['message']), 200)


if __name__ == "__main__":
    unittest.main()
