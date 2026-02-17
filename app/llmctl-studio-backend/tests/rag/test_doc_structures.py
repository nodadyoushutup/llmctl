import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

from rag.engine.doc_structures import html_spans, markdown_spans


class DocStructureTests(unittest.TestCase):
    def test_markdown_spans_include_code_fence(self):
        text = """# Title

Intro text

```python
print('hi')
```

## Next
More text
"""
        spans = markdown_spans(text)
        fence_blocks = [span for span in spans if span.get("metadata", {}).get("block_type") == "code_fence"]
        self.assertTrue(fence_blocks)

    def test_html_spans_strip_boilerplate(self):
        html_doc = """<html><head><style>.x{}</style></head>
        <body><h1>Title</h1><p>Hello</p><script>ignored()</script></body></html>"""
        spans = html_spans(html_doc)
        texts = " ".join(span["text"] for span in spans)
        self.assertIn("Title", texts)
        self.assertIn("Hello", texts)
        self.assertNotIn("ignored", texts)


if __name__ == "__main__":
    unittest.main()
