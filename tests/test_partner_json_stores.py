import tempfile
import unittest
from pathlib import Path

from common_utils import AtomicJsonStore
from DailyCheckin import store as checkin_store
from MovieBoard import store as movie_store


class PartnerJsonStoreTests(unittest.TestCase):
    def test_movie_partner_status_load_uses_atomic_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = movie_store._partner_status_store
            movie_store._partner_status_store = AtomicJsonStore(
                Path(tmp) / "partner_status.json", {}
            )
            try:
                movie_store._partner_status_store.save({"12": {"status": "watched"}})
                self.assertEqual(
                    movie_store._load_partner_status(),
                    {"12": {"status": "watched"}},
                )

                movie_store._partner_status_store.save(["invalid"])
                self.assertEqual(movie_store._load_partner_status(), {})
            finally:
                movie_store._partner_status_store = original_store

    def test_movie_partner_status_normalizes_invalid_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = movie_store._partner_status_store
            movie_store._partner_status_store = AtomicJsonStore(
                Path(tmp) / "partner_status.json", {}
            )
            try:
                movie_store.set_partner_status("12", "invalid", 99)
                self.assertEqual(
                    movie_store.get_partner_status("12"),
                    {"status": None, "rating": None},
                )

                movie_store.set_partner_status("13", "watched", 8)
                self.assertEqual(
                    movie_store.get_partner_status("13"),
                    {"status": "watched", "rating": 8},
                )
            finally:
                movie_store._partner_status_store = original_store

    def test_checkin_partner_load_uses_atomic_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_store = checkin_store._partner_store
            checkin_store._partner_store = AtomicJsonStore(
                Path(tmp) / "partner_checkins.json", {}
            )
            try:
                checkin_store._partner_store.save({"2026-08-18": {"mood": 5}})
                self.assertEqual(
                    checkin_store._load_partner(),
                    {"2026-08-18": {"mood": 5}},
                )

                checkin_store._partner_store.save("invalid")
                self.assertEqual(checkin_store._load_partner(), {})
            finally:
                checkin_store._partner_store = original_store


if __name__ == "__main__":
    unittest.main()
