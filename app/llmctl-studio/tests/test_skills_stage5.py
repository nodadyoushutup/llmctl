from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    FlowchartNode,
    LLMModel,
    Skill,
    SkillFile,
    SkillVersion,
    TaskTemplate,
    flowchart_node_skills,
)
from rag.web.views import bp as rag_bp
import web.views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_dir / 'skills-stage5.sqlite3'}"
        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("skills-stage5-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "skills-stage5"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None


class SkillsStage5Tests(StudioDbTestCase):
    def _create_flowchart(self, name: str) -> int:
        response = self.client.post("/flowcharts", json={"name": name})
        self.assertEqual(201, response.status_code)
        payload = response.get_json() or {}
        return int(payload["flowchart"]["id"])

    def _create_active_skill(self, *, name: str = "stage5-skill") -> int:
        with session_scope() as session:
            skill = Skill.create(
                session,
                name=name,
                display_name="Stage 5 Skill",
                description="Skill for stage 5 web tests.",
                status="active",
                source_type="ui",
            )
            version = SkillVersion.create(
                session,
                skill_id=skill.id,
                version="1.0.0",
                manifest_hash="",
            )
            skill_md = (
                "---\n"
                f"name: {name}\n"
                "display_name: Stage 5 Skill\n"
                "description: Skill for stage 5 web tests.\n"
                "version: 1.0.0\n"
                "status: active\n"
                "---\n\n"
                "# Stage 5 Skill\n"
            )
            SkillFile.create(
                session,
                skill_version_id=version.id,
                path="SKILL.md",
                content=skill_md,
                checksum="",
                size_bytes=len(skill_md.encode("utf-8")),
            )
            return int(skill.id)

    def test_skill_crud_routes_and_import_preview(self) -> None:
        create_response = self.client.post(
            "/skills",
            data={
                "name": "ui-skill",
                "display_name": "UI Skill",
                "description": "Skill created from web form.",
                "version": "1.0.0",
                "status": "active",
                "skill_md": (
                    "---\n"
                    "name: ui-skill\n"
                    "display_name: UI Skill\n"
                    "description: Skill created from web form.\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# UI Skill\n"
                ),
            },
            follow_redirects=False,
        )
        self.assertEqual(302, create_response.status_code)
        skill_location = str(create_response.headers.get("Location") or "")
        self.assertIn("/skills/", skill_location)
        skill_id = int(skill_location.rstrip("/").split("/")[-1])

        list_response = self.client.get("/skills")
        self.assertEqual(200, list_response.status_code)
        self.assertIn("UI Skill", (list_response.get_data(as_text=True) or ""))

        detail_response = self.client.get(f"/skills/{skill_id}")
        self.assertEqual(200, detail_response.status_code)
        self.assertIn("UI Skill", (detail_response.get_data(as_text=True) or ""))

        update_response = self.client.post(
            f"/skills/{skill_id}",
            data={
                "display_name": "UI Skill Updated",
                "description": "Skill updated from web form.",
                "status": "active",
                "new_version": "1.1.0",
                "new_skill_md": (
                    "---\n"
                    "name: ui-skill\n"
                    "display_name: UI Skill Updated\n"
                    "description: Skill updated from web form.\n"
                    "version: 1.1.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# UI Skill Updated\n"
                ),
            },
            follow_redirects=False,
        )
        self.assertEqual(302, update_response.status_code)

        updated_detail = self.client.get(f"/skills/{skill_id}?version=1.1.0")
        self.assertEqual(200, updated_detail.status_code)
        self.assertIn("UI Skill Updated", (updated_detail.get_data(as_text=True) or ""))

        import_package_dir = Path(self._tmp.name) / "import-skill"
        (import_package_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (import_package_dir / "SKILL.md").write_text(
            (
                "---\n"
                "name: import-skill\n"
                "display_name: Import Skill\n"
                "description: Import preview package.\n"
                "version: 1.0.0\n"
                "status: active\n"
                "---\n\n"
                "# Import Skill\n"
            ),
            encoding="utf-8",
        )
        (import_package_dir / "scripts" / "run.sh").write_text(
            "echo preview\n",
            encoding="utf-8",
        )
        import_preview = self.client.post(
            "/skills/import",
            data={
                "action": "preview",
                "source_kind": "path",
                "local_path": str(import_package_dir),
            },
            follow_redirects=False,
        )
        self.assertEqual(200, import_preview.status_code)
        self.assertIn("Validation Preview", (import_preview.get_data(as_text=True) or ""))

        delete_response = self.client.post(
            f"/skills/{skill_id}/delete",
            data={"next": "/skills"},
            follow_redirects=False,
        )
        self.assertEqual(302, delete_response.status_code)
        with session_scope() as session:
            self.assertIsNone(session.get(Skill, skill_id))

    def test_flowchart_node_skill_attach_detach_reorder_routes(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="stage5-model",
                provider="codex",
                config_json="{}",
            )
            template = TaskTemplate.create(
                session,
                name="stage5-template",
                prompt="hello",
                model_id=model.id,
            )
            template_id = int(template.id)

        flowchart_id = self._create_flowchart("Stage 5 Node Skill Routes")
        current_graph = self.client.get(f"/flowcharts/{flowchart_id}/graph")
        self.assertEqual(200, current_graph.status_code)
        current_nodes = (current_graph.get_json() or {}).get("nodes") or []
        start_node_id = int(
            next(node["id"] for node in current_nodes if node.get("node_type") == FLOWCHART_NODE_TYPE_START)
        )
        graph_response = self.client.post(
            f"/flowcharts/{flowchart_id}/graph",
            json={
                "nodes": [
                    {
                        "id": start_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_START,
                        "x": 0,
                        "y": 0,
                    },
                    {
                        "client_id": "task",
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "ref_id": template_id,
                        "x": 140,
                        "y": 0,
                    },
                ],
                "edges": [{"source_node_id": start_node_id, "target_node_id": "task", "edge_mode": "solid"}],
            },
        )
        self.assertEqual(200, graph_response.status_code)
        payload = graph_response.get_json() or {}
        nodes = payload.get("nodes") or []
        task_node_id = int(
            next(node["id"] for node in nodes if node.get("node_type") == FLOWCHART_NODE_TYPE_TASK)
        )

        skill_a_id = self._create_active_skill(name="stage5-a")
        skill_b_id = self._create_active_skill(name="stage5-b")

        attach_a = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills",
            json={"skill_id": skill_a_id},
        )
        self.assertEqual(200, attach_a.status_code)
        attach_b = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills",
            json={"skill_id": skill_b_id},
        )
        self.assertEqual(200, attach_b.status_code)

        reorder = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills/reorder",
            json={"skill_ids": [skill_b_id, skill_a_id]},
        )
        self.assertEqual(200, reorder.status_code)
        reordered_node = (reorder.get_json() or {}).get("node") or {}
        self.assertEqual({skill_a_id, skill_b_id}, set(reordered_node.get("skill_ids") or []))

        with session_scope() as session:
            ordered_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_skills.c.skill_id)
                    .where(flowchart_node_skills.c.flowchart_node_id == task_node_id)
                    .order_by(flowchart_node_skills.c.position.asc())
                ).all()
            ]
        self.assertEqual([skill_b_id, skill_a_id], ordered_skill_ids)

        detach = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills/{skill_b_id}/delete",
        )
        self.assertEqual(200, detach.status_code)
        with session_scope() as session:
            remaining_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_skills.c.skill_id)
                    .where(flowchart_node_skills.c.flowchart_node_id == task_node_id)
                    .order_by(flowchart_node_skills.c.position.asc())
                ).all()
            ]
        self.assertEqual([skill_a_id], remaining_skill_ids)

        utilities = self.client.get(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/utilities"
        )
        self.assertEqual(200, utilities.status_code)
        utilities_node = (utilities.get_json() or {}).get("node") or {}
        self.assertEqual([skill_a_id], utilities_node.get("skill_ids"))


if __name__ == "__main__":
    unittest.main()
