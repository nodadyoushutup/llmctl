from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTOR_RUN = REPO_ROOT / "app" / "llmctl-executor" / "run.py"


class ExecutorStage4Tests(unittest.TestCase):
    def _run_executor(self, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tmp:
            output_path = Path(tmp.name)
        try:
            cmd = [
                sys.executable,
                str(EXECUTOR_RUN),
                "--payload-json",
                json.dumps(payload),
                "--output-file",
                str(output_path),
            ]
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                cwd=str(REPO_ROOT),
            )
            result = json.loads(output_path.read_text(encoding="utf-8"))
            return completed.returncode, result
        finally:
            output_path.unlink(missing_ok=True)

    def test_success_result_contract(self) -> None:
        code, result = self._run_executor(
            {
                "contract_version": "v1",
                "provider": "workspace",
                "request_id": "unit-success",
                "command": ["/bin/bash", "-lc", "echo stage4-success"],
            }
        )
        self.assertEqual(0, code)
        self.assertEqual("v1", result.get("contract_version"))
        self.assertEqual("success", result.get("status"))
        self.assertIn("stage4-success", str(result.get("stdout") or ""))
        self.assertIsNone(result.get("error"))

    def test_non_zero_exit_returns_failed(self) -> None:
        code, result = self._run_executor(
            {
                "contract_version": "v1",
                "provider": "workspace",
                "request_id": "unit-failed",
                "command": ["/bin/bash", "-lc", "echo bad >&2; exit 7"],
            }
        )
        self.assertEqual(7, code)
        self.assertEqual("failed", result.get("status"))
        self.assertEqual(7, int(result.get("exit_code") or 0))
        error = result.get("error") or {}
        self.assertEqual("execution_error", error.get("code"))
        self.assertIn("bad", str(result.get("stderr") or ""))

    def test_contract_version_mismatch_is_infra_error(self) -> None:
        code, result = self._run_executor(
            {
                "contract_version": "v2",
                "provider": "workspace",
                "request_id": "unit-version-mismatch",
                "command": ["/bin/bash", "-lc", "echo wont-run"],
            }
        )
        self.assertEqual(1, code)
        self.assertEqual("infra_error", result.get("status"))
        error = result.get("error") or {}
        self.assertEqual("infra_error", error.get("code"))

    def test_node_execution_payload_returns_output_and_routing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module_path = Path(tmp_dir) / "node_entrypoint_test.py"
            module_path.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "",
                        "def run_node(request):",
                        "    return (",
                        '        {"node_type": str(getattr(request, "node_type", "")), "executed": True},',
                        '        {"route_key": "next"},',
                        "    )",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            code, result = self._run_executor(
                {
                    "contract_version": "v1",
                    "provider": "kubernetes",
                    "request_id": "unit-node-exec",
                    "node_execution": {
                        "entrypoint": "node_entrypoint_test:run_node",
                        "python_paths": [tmp_dir],
                        "request": {
                            "node_type": "start",
                            "enabled_providers": ["kubernetes"],
                            "mcp_server_keys": [],
                        },
                    },
                }
            )
        self.assertEqual(0, code)
        self.assertEqual("success", result.get("status"))
        self.assertEqual(
            {"node_type": "start", "executed": True},
            result.get("output_state"),
        )
        self.assertEqual({"route_key": "next"}, result.get("routing_state"))
        provider_metadata = result.get("provider_metadata") or {}
        self.assertEqual("node_execution", provider_metadata.get("execution_mode"))

    def test_node_execution_payload_requires_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            module_path = Path(tmp_dir) / "node_entrypoint_invalid.py"
            module_path.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "",
                        "def run_node(_request):",
                        '    return "invalid"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            code, result = self._run_executor(
                {
                    "contract_version": "v1",
                    "provider": "kubernetes",
                    "request_id": "unit-node-invalid",
                    "node_execution": {
                        "entrypoint": "node_entrypoint_invalid:run_node",
                        "python_paths": [tmp_dir],
                        "request": {
                            "node_type": "start",
                            "enabled_providers": [],
                            "mcp_server_keys": [],
                        },
                    },
                }
            )
        self.assertEqual(1, code)
        self.assertEqual("failed", result.get("status"))
        error = result.get("error") or {}
        self.assertEqual("execution_error", error.get("code"))
        self.assertIn("Node execution failed", str(error.get("message") or ""))


if __name__ == "__main__":
    unittest.main()
