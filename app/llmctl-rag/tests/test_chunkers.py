import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chunkers import pdf_chunker, token_chunker
from pipeline import ParsedDocument
from tests.helpers import test_config


class ChunkerTests(unittest.TestCase):
    def test_token_chunker_offsets(self):
        config = test_config()
        doc = ParsedDocument(
            content="one two three four five six seven eight nine ten",
            doc_type="text",
            language=None,
            source={},
        )
        chunks = token_chunker(doc, config)
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertIsNotNone(chunk.start_offset)
            self.assertIsNotNone(chunk.end_offset)

    def test_pdf_chunker_payloads(self):
        config = test_config()
        doc = ParsedDocument(
            content="",
            doc_type="pdf",
            language=None,
            source={},
            structural_hints={
                "pdf": {
                    "pages": [
                        {
                            "page_number": 1,
                            "text_layer": {"text": "Layer text", "char_boxes": []},
                            "ocr": {
                                "text": "OCR text",
                                "word_boxes": [{"text": "OCR", "bbox": [0, 0, 1, 1], "confidence": 90}],
                                "char_boxes": [],
                            },
                            "vector_primitives": [{"type": "line", "points": [[0, 0], [1, 1]]}],
                            "vector_raw": [{"items": []}],
                            "tables": [{"rows": [{"cells": [{"text": "A", "bbox": [0, 0, 1, 1]}]}]}],
                            "normalized_units": [{"value": 5, "unit": "in", "normalized_unit": "in"}],
                        }
                    ],
                    "vector_raw_document": [{"items": []}],
                }
            },
        )
        chunks = pdf_chunker(doc, config)
        sources = {chunk.source for chunk in chunks}
        self.assertTrue({"text", "ocr", "vector-geom", "vector-raw"}.issubset(sources))
        ocr_chunk = next(c for c in chunks if c.source == "ocr")
        payload = json.loads(ocr_chunk.text)
        self.assertIn("extracted_text", payload)
        self.assertIn("ocr_word_boxes", payload)


if __name__ == "__main__":
    unittest.main()
