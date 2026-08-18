import tempfile
import unittest
from pathlib import Path

import app_paths
from common_utils import AtomicJsonStore


class SuiteConfigTests(unittest.TestCase):
    def test_update_suite_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = app_paths._SUITE_STORE
            app_paths._SUITE_STORE = AtomicJsonStore(Path(tmp) / "suite.json", {})
            try:
                app_paths.save_suite({"onboarded": False, "theme": "pink"})
                updated = app_paths.update_suite(onboarded=True)

                self.assertEqual(updated, {"onboarded": True, "theme": "pink"})
                self.assertEqual(app_paths.load_suite(), updated)
            finally:
                app_paths._SUITE_STORE = original_store


if __name__ == "__main__":
    unittest.main()
