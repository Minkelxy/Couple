import tempfile
import unittest
from pathlib import Path

from MovieBoard import store


class MovieStoreTests(unittest.TestCase):
    def test_updates_reject_invalid_status_rating_and_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db = store.DB_PATH
            store.DB_PATH = Path(tmp) / "movies.db"
            try:
                store.init_db()
                movie_id = store.add("Movie")
                store.update_status(movie_id, "invalid")
                store.update_rating(movie_id, "mine", 99)
                store.update_rating(movie_id, "mine", True)
                store.update_review(movie_id, "mine", None)

                unchanged = store.get(movie_id)
                self.assertEqual(unchanged["status"], store.STATUS_WANT)
                self.assertIsNone(unchanged["rating_mine"])
                self.assertIsNone(unchanged["review_mine"])

                store.update_status(movie_id, store.STATUS_WATCHED)
                store.update_rating(movie_id, "mine", 8)
                store.update_review(movie_id, "mine", "good")
                updated = store.get(movie_id)
                self.assertEqual(updated["status"], store.STATUS_WATCHED)
                self.assertEqual(updated["rating_mine"], 8)
                self.assertEqual(updated["review_mine"], "good")
            finally:
                store.DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
