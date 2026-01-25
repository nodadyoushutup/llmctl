FROM mcp/chroma:latest

ENV PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends catatonit \
  && rm -rf /var/lib/apt/lists/* \
  && python -m venv /opt/mcp-proxy-venv \
  && /opt/mcp-proxy-venv/bin/python -m pip install --no-cache-dir mcp-proxy \
  && mv /usr/local/bin/chroma-mcp /usr/local/bin/chroma-mcp-real \
  && cat <<'PY' > /usr/local/bin/chroma-mcp \
  && chmod +x /usr/local/bin/chroma-mcp
#!/usr/local/bin/python
import builtins
import sys

_orig_print = builtins.print

def _stderr_print(*args, **kwargs):
    kwargs["file"] = sys.stderr
    return _orig_print(*args, **kwargs)

builtins.print = _stderr_print

import chroma_mcp.server as server

server.main()
PY

ENTRYPOINT ["catatonit", "--", "/opt/mcp-proxy-venv/bin/mcp-proxy"]
