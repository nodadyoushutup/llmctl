from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / "audit" / "claim_guardrails.py"
SPEC = importlib.util.spec_from_file_location("claim_guardrails", MODULE_PATH)
assert SPEC and SPEC.loader
claim_guardrails = importlib.util.module_from_spec(SPEC)
sys.modules["claim_guardrails"] = claim_guardrails
SPEC.loader.exec_module(claim_guardrails)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


class ClaimGuardrailsTests(unittest.TestCase):
    def _write_inventory(self, root: Path, claim_id: str = "RMC-9000") -> Path:
        inventory = root / "docs" / "planning" / "active" / "RUNTIME_MIGRATION_CLAIM_INVENTORY.md"
        _write_text(
            inventory,
            f"""
            # Inventory

            | claim_id | source | line | domain | invariant | claim_text |
            |---|---|---:|---|---|---|
            | {claim_id} | `docs/planning/archive/source.md` | 1 | `testing` | `yes` | example |
            """,
        )
        return inventory

    def _write_matrix(self, root: Path, *, claim_id: str = "RMC-9000", code_evidence: str, test_evidence: str) -> Path:
        matrix = root / "docs" / "planning" / "active" / "RUNTIME_MIGRATION_CLAIM_EVIDENCE_MATRIX.md"
        _write_text(
            matrix,
            f"""
            # Matrix

            | claim_id | source | line | domain | invariant | code_evidence | test_evidence | ui_api_evidence | status | severity | notes |
            |---|---|---:|---|---|---|---|---|---|---|---|
            | {claim_id} | `docs/planning/archive/source.md` | 1 | `testing` | `yes` | {code_evidence} | {test_evidence} | `TBD` | `pass` | `high` | example |
            """,
        )
        return matrix

    def test_passes_with_static_and_runtime_evidence_linked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = self._write_inventory(root)
            matrix = self._write_matrix(
                root,
                code_evidence="`app/runtime/core.py:2`",
                test_evidence="`app/runtime/core.test.js:3`",
            )
            _write_text(
                root / "app" / "runtime" / "core.py",
                """
                VALUE = 1
                def do_work():
                    return VALUE
                """,
            )
            _write_text(
                root / "app" / "runtime" / "core.test.js",
                """
                test('runtime behavior', () => {
                  expect(true).toBe(true)
                })
                """,
            )

            failures = claim_guardrails.run_guardrails(
                matrix_path=matrix,
                inventory_path=inventory,
                repo_root=root,
            )
            self.assertEqual([], failures)

    def test_fails_when_static_code_evidence_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = self._write_inventory(root)
            matrix = self._write_matrix(
                root,
                code_evidence="`TBD`",
                test_evidence="`app/tests/test_runtime.py:1`",
            )
            _write_text(root / "app" / "tests" / "test_runtime.py", "def test_runtime():\n    assert True\n")

            failures = claim_guardrails.run_guardrails(
                matrix_path=matrix,
                inventory_path=inventory,
                repo_root=root,
            )
            self.assertTrue(any("missing static code evidence" in failure for failure in failures))

    def test_fails_when_runtime_test_evidence_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = self._write_inventory(root)
            matrix = self._write_matrix(
                root,
                code_evidence="`app/runtime/core.py:1`",
                test_evidence="`TBD`",
            )
            _write_text(root / "app" / "runtime" / "core.py", "VALUE = 1\n")

            failures = claim_guardrails.run_guardrails(
                matrix_path=matrix,
                inventory_path=inventory,
                repo_root=root,
            )
            self.assertTrue(any("missing runtime test evidence" in failure for failure in failures))

    def test_fails_when_claim_to_test_linkage_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = self._write_inventory(root)
            matrix = self._write_matrix(
                root,
                code_evidence="`app/runtime/core.py:1`",
                test_evidence="`app/runtime/core.py:1`",
            )
            _write_text(root / "app" / "runtime" / "core.py", "VALUE = 1\n")

            failures = claim_guardrails.run_guardrails(
                matrix_path=matrix,
                inventory_path=inventory,
                repo_root=root,
            )
            self.assertTrue(any("claim-to-test linkage" in failure for failure in failures))

    def test_fails_when_claim_missing_from_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = self._write_inventory(root, claim_id="RMC-9001")
            matrix = self._write_matrix(
                root,
                claim_id="RMC-9002",
                code_evidence="`app/runtime/core.py:1`",
                test_evidence="`app/tests/test_runtime.py:1`",
            )
            _write_text(root / "app" / "runtime" / "core.py", "VALUE = 1\n")
            _write_text(root / "app" / "tests" / "test_runtime.py", "def test_runtime():\n    assert True\n")

            failures = claim_guardrails.run_guardrails(
                matrix_path=matrix,
                inventory_path=inventory,
                repo_root=root,
            )
            self.assertTrue(any("missing inventory linkage" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
