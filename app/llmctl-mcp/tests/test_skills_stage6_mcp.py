from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import insert

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
MCP_SRC = REPO_ROOT / "app" / "llmctl-mcp" / "src"
for path in (str(STUDIO_SRC), str(MCP_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    AgentTask,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartNode,
    LLMModel,
    Script,
)
import tools as mcp_tools


class _DummyMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class SkillsStage6McpToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'skills-stage6-mcp.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        self.mcp = _DummyMCP()
        mcp_tools.register(self.mcp)

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    def _insert_legacy_skill_script(self) -> int:
        with session_scope() as session:
            result = session.execute(
                insert(Script.__table__).values(
                    file_name="legacy-mcp.sh",
                    file_path=None,
                    description="legacy",
                    content="echo mcp\n",
                    script_type="skill",
                )
            )
            return int(result.inserted_primary_key[0])

    def test_bind_flowchart_node_script_rejects_legacy_skill_script(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="mcp-stage6-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="mcp-stage6-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json="{}",
            )
            flowchart_id = int(flowchart.id)
            node_id = int(node.id)

        legacy_script_id = self._insert_legacy_skill_script()
        bind_script = self.mcp.tools["llmctl_bind_flowchart_node_script"]
        result = bind_script(
            flowchart_id=flowchart_id,
            node_id=node_id,
            script_id=legacy_script_id,
        )
        self.assertFalse(result["ok"])
        self.assertIn("Legacy script_type=skill", str(result.get("error") or ""))

    def test_set_task_scripts_rejects_skill_script_type_key(self) -> None:
        with session_scope() as session:
            task = AgentTask.create(
                session,
                status="queued",
                prompt="stage6",
            )
            task_id = int(task.id)

        set_task_scripts = self.mcp.tools["set_task_scripts"]
        result = set_task_scripts(task_id=task_id, script_ids_by_type={"skill": [1]})
        self.assertFalse(result["ok"])
        self.assertIn("Unknown script type", str(result.get("error") or ""))


if __name__ == "__main__":
    unittest.main()
