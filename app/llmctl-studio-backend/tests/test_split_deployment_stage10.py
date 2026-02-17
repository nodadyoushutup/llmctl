from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INGRESS_PATH = REPO_ROOT / "kubernetes" / "studio-ingress.yaml"
FRONTEND_NGINX_PATH = REPO_ROOT / "app" / "llmctl-studio-frontend" / "docker" / "nginx.conf"


class SplitDeploymentStage10IntegrationTests(unittest.TestCase):
    def test_ingress_routes_api_and_web_paths_to_expected_services(self) -> None:
        content = INGRESS_PATH.read_text(encoding="utf-8")

        self.assertRegex(
            content,
            r"- path: /api\s+pathType: Prefix\s+backend:\s+service:\s+name: llmctl-studio-backend",
        )
        self.assertRegex(
            content,
            r"- path: /web\s+pathType: Prefix\s+backend:\s+service:\s+name: llmctl-studio-frontend",
        )
        self.assertRegex(
            content,
            r"- path: /\s+pathType: Prefix\s+backend:\s+service:\s+name: llmctl-studio-frontend",
        )

    def test_frontend_nginx_preserves_split_proxy_contract(self) -> None:
        content = FRONTEND_NGINX_PATH.read_text(encoding="utf-8")

        self.assertIn("location /web/ {", content)
        self.assertIn("try_files $uri $uri/ /web/index.html;", content)
        self.assertIn("location /api/ {", content)
        self.assertIn("location /socket.io/ {", content)
        self.assertRegex(
            content,
            re.compile(
                r"location /api/\s*\{[^}]*proxy_pass http://llmctl-studio-backend:5155;",
                re.S,
            ),
        )
        self.assertRegex(
            content,
            re.compile(
                r"location /socket.io/\s*\{[^}]*proxy_pass http://llmctl-studio-backend:5155;",
                re.S,
            ),
        )
        self.assertRegex(
            content,
            re.compile(
                r"location /\s*\{[^}]*proxy_pass http://llmctl-studio-backend:5155;",
                re.S,
            ),
        )
        self.assertIn("return 302 $scheme://$http_host/web/overview;", content)
        self.assertIn(
            'add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;',
            content,
        )


if __name__ == "__main__":
    unittest.main()
