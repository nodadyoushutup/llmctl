"""Sphinx configuration for llmctl technical API documentation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOCS_DIR.parent.parent
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
API_OUTPUT = DOCS_DIR / "api"
STUDIO_PACKAGES = ["chat", "core", "rag", "services", "storage", "web"]
APIDOC_EXCLUDES = {
    "core": [
        STUDIO_SRC / "core" / "integrated_mcp.py",
        STUDIO_SRC / "core" / "migrations.py",
        STUDIO_SRC / "core" / "models",
        STUDIO_SRC / "core" / "seed.py",
    ],
    "rag": [
        STUDIO_SRC / "rag" / "engine" / "ingest.py",
        STUDIO_SRC / "rag" / "repositories",
        STUDIO_SRC / "rag" / "runtime",
        STUDIO_SRC / "rag" / "web",
        STUDIO_SRC / "rag" / "worker" / "tasks.py",
    ],
    "services": [
        STUDIO_SRC / "services" / "code_review.py",
        STUDIO_SRC / "services" / "integrations.py",
        STUDIO_SRC / "services" / "tasks.py",
    ],
    "web": [
        STUDIO_SRC / "web" / "app.py",
        STUDIO_SRC / "web" / "views",
    ],
}

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

sys.path.insert(0, str(STUDIO_SRC))

project = "llmctl"
author = "llmctl contributors"
copyright = "2026, llmctl contributors"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

root_doc = "index"
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
suppress_warnings = ["ref.ref"]
autodoc_mock_imports = [
    "celery",
    "chroma_mcp",
    "chromadb",
    "cv2",
    "fastmcp",
    "flask",
    "flask_seeder",
    "google",
    "mcp_atlassian",
    "openai",
    "openpyxl",
    "PIL",
    "pptx",
    "pytesseract",
    "redis",
    "tiktoken",
    "watchdog",
]

html_theme = "sphinx_rtd_theme"
html_title = "llmctl technical API documentation"
html_static_path = ["_static"]


def _generate_apidoc(_: object) -> None:
    """Generate API RST files for llmctl-studio package modules."""
    from sphinx.ext.apidoc import main

    API_OUTPUT.mkdir(parents=True, exist_ok=True)
    for rst_file in API_OUTPUT.glob("*.rst"):
        rst_file.unlink()

    for package_name in STUDIO_PACKAGES:
        excludes = [str(path) for path in APIDOC_EXCLUDES.get(package_name, [])]
        main(
            [
                "-f",
                "-e",
                "-M",
                "-T",
                "-o",
                str(API_OUTPUT),
                str(STUDIO_SRC / package_name),
                *excludes,
            ]
        )

    toctree = "\n".join(f"   {package_name}" for package_name in STUDIO_PACKAGES)
    modules_index = (
        "Studio API Packages\n"
        "===================\n\n"
        ".. toctree::\n"
        "   :maxdepth: 3\n\n"
        f"{toctree}\n"
    )
    (API_OUTPUT / "modules.rst").write_text(modules_index, encoding="utf-8")


def setup(app: object) -> None:
    app.connect("builder-inited", _generate_apidoc)
