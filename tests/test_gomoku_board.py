import unittest

from PySide6.QtWidgets import QApplication

from Gomoku.board_widget import GomokuBoard


class GomokuBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_place_stone_reports_rejected_moves(self):
        board = GomokuBoard()

        self.assertFalse(board.place_stone(-1, 0, 2))
        self.assertTrue(board.place_stone(0, 0, 1))
        self.assertFalse(board.place_stone(0, 0, 2))
        self.assertFalse(board.place_stone(15, 0, 2))
        self.assertEqual(board.get_moves(), [(0, 0, 1)])


if __name__ == "__main__":
    unittest.main()
