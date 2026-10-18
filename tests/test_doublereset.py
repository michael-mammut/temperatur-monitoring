import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WlanNetwork.doublereset import check_double_reset, consume_setup_request


class DoubleResetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(self._restore)

    def _restore(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_single_boot_is_a_normal_boot(self):
        self.assertFalse(check_double_reset(sleep_ms=lambda ms: None))
        self.assertFalse(consume_setup_request())

    def test_marker_is_gone_after_the_window(self):
        check_double_reset(sleep_ms=lambda ms: None)

        self.assertEqual(os.listdir('.'), [])

    def test_reset_during_the_window_requests_setup(self):
        def reset_while_waiting(ms):
            # The second press reboots the board while the first boot is
            # still waiting - its marker is still on flash.
            self.assertTrue(check_double_reset(sleep_ms=lambda ms: None))
            raise SystemExit  # first boot never gets past the sleep

        with self.assertRaises(SystemExit):
            check_double_reset(sleep_ms=reset_while_waiting)

        self.assertTrue(consume_setup_request())

    def test_setup_request_is_consumed_only_once(self):
        open('reset_marker', 'w').close()
        check_double_reset(sleep_ms=lambda ms: None)

        self.assertTrue(consume_setup_request())
        self.assertFalse(consume_setup_request())

    def test_interrupted_boot_does_not_leave_a_marker_behind(self):
        """Regression guard: the deploy script interrupts boot.py with
        Ctrl-C. A leftover marker would make the next boot look like a
        double RESET press and open the setup network."""
        def interrupted(ms):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            check_double_reset(sleep_ms=interrupted)

        self.assertFalse(check_double_reset(sleep_ms=lambda ms: None))
        self.assertFalse(consume_setup_request())


if __name__ == "__main__":
    unittest.main()
