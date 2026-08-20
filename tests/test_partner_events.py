import unittest
from unittest.mock import patch

from DailyCheckin import checkin_window
from TravelMap import map_window


class PartnerEventValidationTests(unittest.TestCase):
    def test_checkin_rejects_invalid_date_and_mood(self):
        with patch.object(checkin_window.store, "add_partner_record") as save:
            checkin_window.handle_partner_event(
                {"date": "2026-02-30", "mood": 5}, "", b"", ""
            )
            checkin_window.handle_partner_event(
                {"date": "2026-02-20", "mood": 99}, "", b"", ""
            )

        save.assert_not_called()

    def test_checkin_accepts_valid_date_and_mood(self):
        with patch.object(checkin_window.store, "add_partner_record") as save:
            checkin_window.handle_partner_event(
                {"date": "2026-02-20", "mood": 5, "note": "good"}, "", b"", ""
            )

        save.assert_called_once_with("2026-02-20", 5, "good", "")

    def test_travel_rejects_non_finite_and_out_of_range_coordinates(self):
        with patch.object(map_window.store, "add_partner_city") as save:
            map_window.handle_partner_event(
                {"city": "A", "lat": "nan", "lng": 0}, "", b"", ""
            )
            map_window.handle_partner_event(
                {"city": "B", "lat": 91, "lng": 0}, "", b"", ""
            )

        save.assert_not_called()

    def test_travel_accepts_valid_coordinates(self):
        with patch.object(map_window.store, "add_partner_city") as save:
            map_window.handle_partner_event(
                {"city": "Suzhou", "lat": 31.3, "lng": 120.6, "note": "trip"},
                "",
                b"",
                "",
            )

        save.assert_called_once_with("Suzhou", 31.3, 120.6, "trip", "")

    def test_storage_failure_is_reported_for_sync_retry(self):
        with patch.object(
            checkin_window.store, "add_partner_record", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                checkin_window.handle_partner_event(
                    {"date": "2026-02-20", "mood": 5}, "", b"", ""
                )
        with patch.object(
            map_window.store, "add_partner_city", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                map_window.handle_partner_event(
                    {"city": "Suzhou", "lat": 31.3, "lng": 120.6}, "", b"", ""
                )


if __name__ == "__main__":
    unittest.main()
