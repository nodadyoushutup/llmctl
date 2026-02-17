from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.engine.pdf_pipeline import _should_capture_vector_payload, _summarize_vector_geometry


class PdfPipelineVectorGatingTests(unittest.TestCase):
    def test_axis_aligned_layout_is_skipped(self):
        drawings = [
            {
                "items": [
                    ("l", (0, 0), (100, 0)),
                    ("l", (0, 20), (100, 20)),
                    ("l", (0, 0), (0, 20)),
                    ("l", (100, 0), (100, 20)),
                    ("re", (0, 0, 100, 20)),
                ]
            }
        ]
        stats = _summarize_vector_geometry(drawings)
        capture, reason = _should_capture_vector_payload(stats)
        self.assertFalse(capture)
        self.assertEqual(reason, "axis_aligned_layout")

    def test_non_axis_lines_are_captured(self):
        drawings = [
            {
                "items": [
                    ("l", (0, 0), (10, 8)),
                    ("l", (0, 0), (11, 7)),
                    ("l", (0, 0), (12, 6)),
                    ("l", (0, 0), (13, 5)),
                    ("l", (0, 0), (14, 4)),
                    ("l", (0, 0), (15, 3)),
                    ("l", (0, 0), (16, 5)),
                    ("l", (0, 0), (17, 4)),
                ]
            }
        ]
        stats = _summarize_vector_geometry(drawings)
        capture, reason = _should_capture_vector_payload(stats)
        self.assertTrue(capture)
        self.assertEqual(reason, "non_axis_lines")

    def test_curves_are_captured(self):
        drawings = [
            {
                "items": [
                    ("c", (0, 0), (1, 1), (2, 2), (3, 3)),
                ]
            }
        ]
        stats = _summarize_vector_geometry(drawings)
        capture, reason = _should_capture_vector_payload(stats)
        self.assertTrue(capture)
        self.assertEqual(reason, "curve_or_quad")


if __name__ == "__main__":
    unittest.main()
