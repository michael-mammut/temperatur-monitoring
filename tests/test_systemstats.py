import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import micropython_mocks
micropython_mocks.install()

from WebServer.systemstats import get_memory_stats, get_storage_stats


class MemoryStatsTests(unittest.TestCase):
    def test_used_plus_free_equals_total(self):
        stats = get_memory_stats()
        self.assertEqual(stats['used'] + stats['free'], stats['total'])
        self.assertGreaterEqual(stats['used'], 0)
        self.assertGreaterEqual(stats['free'], 0)


class StorageStatsTests(unittest.TestCase):
    def test_used_plus_free_equals_total(self):
        stats = get_storage_stats()
        self.assertEqual(stats['used'] + stats['free'], stats['total'])
        self.assertGreaterEqual(stats['total'], 0)


if __name__ == "__main__":
    unittest.main()
