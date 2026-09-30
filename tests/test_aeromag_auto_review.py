import csv
from pathlib import Path
import tempfile
import unittest


import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aeromag_auto_review import auto_review_survey_lines, review_rows


class AutoReviewTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"id": "S-01", "source": "sortie-alpha", "metres": "8000", "az": "89"},
            {"id": "S-02", "source": "sortie-beta", "metres": "8100", "az": "91"},
            {"id": "C-01", "source": "control-west", "metres": "10000", "az": "179"},
            {
                "id": "C-02",
                "source": r"attitude+control\line-control.csv",
                "metres": "9900",
                "az": "1",
            },
            {"id": "CAL", "source": "attitude calibration", "metres": "7000", "az": "90"},
        ]
        self.columns = ["id", "source", "metres", "az"]
        self.mapping = {
            "line_id": "id",
            "source": "source",
            "length_m": "metres",
            "heading_deg": "az",
        }

    def test_assisted_mode_reinfers_each_dataset(self):
        reviewed, summary = review_rows(
            self.rows,
            self.columns,
            mode="assisted",
            column_map=self.mapping,
            intersection_ids={"C-01", "C-02"},
        )
        decisions = {row["id"]: row["审核决定"] for row in reviewed}
        self.assertEqual(decisions["S-01"], "测线")
        self.assertEqual(decisions["S-02"], "测线")
        self.assertEqual(decisions["C-01"], "控制线")
        self.assertEqual(decisions["C-02"], "控制线")
        self.assertEqual(decisions["CAL"], "删除")
        self.assertEqual(summary["requires_review"], 0)
        self.assertAlmostEqual(summary["dominant_traverse_heading_deg"], 89.0, delta=2.0)

    def test_unconnected_control_requires_review_in_assisted_mode(self):
        reviewed, _ = review_rows(
            self.rows,
            self.columns,
            mode="assisted",
            column_map=self.mapping,
            intersection_ids=set(),
        )
        control = next(row for row in reviewed if row["id"] == "C-01")
        self.assertEqual(control["审核决定"], "待审核")
        self.assertIn("未出现在交点表", control["自动审核异常"])

    def test_rotated_survey_without_project_keywords(self):
        rows = [
            {"segment": "A", "distance": "6200", "bearing": "33"},
            {"segment": "B", "distance": "6300", "bearing": "35"},
            {"segment": "X", "distance": "7000", "bearing": "124"},
        ]
        reviewed, summary = review_rows(
            rows,
            ["segment", "distance", "bearing"],
            mode="assisted",
            column_map={
                "line_id": "segment",
                "length_m": "distance",
                "heading_deg": "bearing",
            },
            intersection_ids={"X"},
        )
        decisions = {row["segment"]: row["审核决定"] for row in reviewed}
        self.assertEqual(decisions, {"A": "测线", "B": "测线", "X": "控制线"})
        self.assertAlmostEqual(summary["dominant_traverse_heading_deg"], 33.0, delta=2.0)

    def test_preview_is_read_only_and_output_must_be_new(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "candidates.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=self.columns)
                writer.writeheader()
                writer.writerows(self.rows)
            preview = auto_review_survey_lines(
                str(source), column_map=self.mapping, mode="strict"
            )
            self.assertFalse(preview["written"])
            output = root / "review"
            written = auto_review_survey_lines(
                str(source), str(output), column_map=self.mapping, mode="strict"
            )
            self.assertTrue(Path(written["review_path"]).is_file())
            with self.assertRaises(FileExistsError):
                auto_review_survey_lines(
                    str(source), str(output), column_map=self.mapping, mode="strict"
                )


if __name__ == "__main__":
    unittest.main()
