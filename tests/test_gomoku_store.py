import tempfile
import unittest
from pathlib import Path

from Gomoku import store


class GomokuStoreTests(unittest.TestCase):
    def test_game_reads_use_atomic_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = store.GOMOKU_DIR
            store.GOMOKU_DIR = Path(tmp)
            try:
                game_id = store.save_game("black", [], "2026-08-18T12:00:00")

                self.assertEqual(store.get_game(game_id)["winner"], "black")
                self.assertEqual(store.list_games()[0]["id"], game_id)

                (Path(tmp) / "broken.json").write_text("[]", encoding="utf-8")
                self.assertNotIn("broken", {game["id"] for game in store.list_games()})
            finally:
                store.GOMOKU_DIR = original_dir

    def test_session_ids_cannot_escape_storage_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = store.GOMOKU_DIR
            store.GOMOKU_DIR = Path(tmp)
            try:
                with self.assertRaises(ValueError):
                    store.append_move("../outside", {"row": 1})

                self.assertEqual(store.load_moves("../outside"), [])
                self.assertIsNone(store.get_game("../outside"))
                self.assertFalse((Path(tmp).parent / "outside.jsonl").exists())
            finally:
                store.GOMOKU_DIR = original_dir

    def test_append_move_is_durable_and_replay_skips_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = store.GOMOKU_DIR
            store.GOMOKU_DIR = Path(tmp)
            try:
                store.append_move("session-1", {"row": 2, "col": 3})
                path = Path(tmp) / "session-1.jsonl"
                with path.open("a", encoding="utf-8") as f:
                    f.write("not json\n")

                self.assertEqual(store.load_moves("session-1"), [{"row": 2, "col": 3}])
            finally:
                store.GOMOKU_DIR = original_dir


if __name__ == "__main__":
    unittest.main()
