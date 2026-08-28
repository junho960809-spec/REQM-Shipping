import unittest

from print_order_board_client import BOARD_SOURCES, parse_board_html, status_counts


class PrintOrderBoardClientTests(unittest.TestCase):
    def test_active_sources_exclude_completed_board(self):
        self.assertEqual([board for _, board in BOARD_SOURCES], ["Sian", "Order", "List", "LIST2"])
        self.assertNotIn("LIST4", [board for _, board in BOARD_SOURCES])

    def test_parses_board_row_into_dashboard_fields(self):
        source = """
        <table><tr><th>번호</th><th>제목</th></tr>
        <tr><td>7</td><td><a href="/apache/gnuboard5/bbs/board.php?bo_table=Order&amp;wr_id=7403">제목</a></td>
        <td>거래처</td><td>2026-08-26</td><td>Q1500 전면 인쇄</td><td>없음</td>
        <td>선물포장</td><td>300</td><td>2026-09-01</td><td>택배</td><td>작업자</td></tr></table>
        """
        rows = parse_board_html(source, "인쇄 진행", "http://orora.ipdisk.co.kr:8000/")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer"], "거래처")
        self.assertEqual(rows[0]["product"], "Q1500 전면 인쇄")
        self.assertEqual(rows[0]["quantity"], "300")
        self.assertEqual(rows[0]["print_pack"], "인쇄 · 선물포장")
        self.assertIn("wr_id=7403", rows[0]["url"])

    def test_counts_each_active_status(self):
        rows = [{"status": "신규 접수"}, {"status": "인쇄 진행"}, {"status": "인쇄 진행"}]
        counts = status_counts(rows)
        self.assertEqual(counts["신규 접수"], 1)
        self.assertEqual(counts["인쇄 진행"], 2)
        self.assertEqual(counts["패킹 진행"], 0)


if __name__ == "__main__":
    unittest.main()
