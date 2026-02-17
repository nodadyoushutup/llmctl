#!/usr/bin/env python3
from __future__ import annotations

import builtins
import sys

_orig_print = builtins.print


def _stderr_print(*args, **kwargs):
    kwargs["file"] = sys.stderr
    return _orig_print(*args, **kwargs)


builtins.print = _stderr_print

from chroma_mcp.server import main


if __name__ == "__main__":
    main()
