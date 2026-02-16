"""Sphinx configuration for llmctl project docs."""

from __future__ import annotations

project = "llmctl"
author = "llmctl contributors"
copyright = "2026, llmctl contributors"

extensions = [
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

root_doc = "index"
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

myst_heading_anchors = 3

html_theme = "sphinx_rtd_theme"
html_title = "llmctl documentation"
html_static_path = ["_static"]
