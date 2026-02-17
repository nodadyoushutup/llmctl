from __future__ import annotations

import json
from io import BytesIO
import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    Agent,
    FLOWCHART_NODE_TYPE_START,
    FLOWCHART_NODE_TYPE_TASK,
    FlowchartNode,
    LLMModel,
    Skill,
    SkillFile,
    SkillVersion,
    agent_skill_bindings,
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
    def _create_agent(self, *, name: str = "stage5-agent") -> int:
        with session_scope() as session:
            agent = Agent.create(
                session,
                name=name,
                description="Stage 5 test agent",
                prompt_json="{}",
            )
            return int(agent.id)

    def _create_flowchart(self, name: str) -> int:
        response = self.client.post("/flowcharts", json={"name": name})
        self.assertEqual(201, response.status_code)
        payload = response.get_json() or {}
        return int(payload["flowchart"]["id"])

    def _create_active_skill(
        self,
        *,
        name: str = "stage5-skill",
        source_type: str = "ui",
        extra_files: list[tuple[str, str]] | None = None,
    ) -> int:
        with session_scope() as session:
            skill = Skill.create(
                session,
                name=name,
                display_name="Stage 5 Skill",
                description="Skill for stage 5 web tests.",
                status="active",
                source_type=source_type,
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
            for path, content in extra_files or []:
                SkillFile.create(
                    session,
                    skill_version_id=version.id,
                    path=path,
                    content=content,
                    checksum="",
                    size_bytes=len(content.encode("utf-8")),
                )
            return int(skill.id)

    def test_agent_skill_routes_attach_move_detach_preserve_order(self) -> None:
        agent_id = self._create_agent(name="stage5-ordering-agent")
        skill_a_id = self._create_active_skill(name="stage5-order-a")
        skill_b_id = self._create_active_skill(name="stage5-order-b")
        skill_c_id = self._create_active_skill(name="stage5-order-c")

        attach_a = self.client.post(
            f"/agents/{agent_id}/skills",
            data={"skill_id": str(skill_a_id)},
            follow_redirects=False,
        )
        self.assertEqual(302, attach_a.status_code)
        attach_b = self.client.post(
            f"/agents/{agent_id}/skills",
            data={"skill_id": str(skill_b_id)},
            follow_redirects=False,
        )
        self.assertEqual(302, attach_b.status_code)
        attach_c = self.client.post(
            f"/agents/{agent_id}/skills",
            data={"skill_id": str(skill_c_id)},
            follow_redirects=False,
        )
        self.assertEqual(302, attach_c.status_code)

        duplicate = self.client.post(
            f"/agents/{agent_id}/skills",
            data={"skill_id": str(skill_b_id)},
            follow_redirects=False,
        )
        self.assertEqual(302, duplicate.status_code)

        move_b_up = self.client.post(
            f"/agents/{agent_id}/skills/{skill_b_id}/move",
            data={"direction": "up"},
            follow_redirects=False,
        )
        self.assertEqual(302, move_b_up.status_code)
        move_c_up = self.client.post(
            f"/agents/{agent_id}/skills/{skill_c_id}/move",
            data={"direction": "up"},
            follow_redirects=False,
        )
        self.assertEqual(302, move_c_up.status_code)

        with session_scope() as session:
            ordered_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(agent_skill_bindings.c.skill_id)
                    .where(agent_skill_bindings.c.agent_id == agent_id)
                    .order_by(agent_skill_bindings.c.position.asc())
                ).all()
            ]
        self.assertEqual([skill_b_id, skill_c_id, skill_a_id], ordered_skill_ids)

        detach_b = self.client.post(
            f"/agents/{agent_id}/skills/{skill_b_id}/delete",
            follow_redirects=False,
        )
        self.assertEqual(302, detach_b.status_code)

        with session_scope() as session:
            remaining_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(agent_skill_bindings.c.skill_id)
                    .where(agent_skill_bindings.c.agent_id == agent_id)
                    .order_by(agent_skill_bindings.c.position.asc())
                ).all()
            ]
        self.assertEqual([skill_c_id, skill_a_id], remaining_skill_ids)

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

    def test_skill_create_with_upload_path_mapping_and_blocked_extension_rejected(self) -> None:
        create_response = self.client.post(
            "/skills",
            data={
                "name": "upload-skill",
                "display_name": "Upload Skill",
                "description": "Skill with uploaded files.",
                "version": "1.0.0",
                "status": "active",
                "skill_md": (
                    "---\n"
                    "name: upload-skill\n"
                    "display_name: Upload Skill\n"
                    "description: Skill with uploaded files.\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# Upload Skill\n"
                ),
                "upload_specs_json": json.dumps(
                    [{"index": 0, "path": "scripts/run.sh", "conflict": "replace"}]
                ),
                "upload_files": (BytesIO(b"echo uploaded\n"), "run.sh"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(302, create_response.status_code)
        skill_location = str(create_response.headers.get("Location") or "")
        skill_id = int(skill_location.rstrip("/").split("/")[-1])

        with session_scope() as session:
            latest_version = (
                session.execute(
                    select(SkillVersion)
                    .where(SkillVersion.skill_id == skill_id)
                    .order_by(SkillVersion.id.desc())
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(latest_version)
            assert latest_version is not None
            files = (
                session.execute(
                    select(SkillFile)
                    .where(SkillFile.skill_version_id == latest_version.id)
                    .order_by(SkillFile.path.asc())
                )
                .scalars()
                .all()
            )
            file_paths = [item.path for item in files]
            self.assertIn("scripts/run.sh", file_paths)
            uploaded = next(item for item in files if item.path == "scripts/run.sh")
            self.assertEqual("echo uploaded\n", uploaded.content)

        blocked_response = self.client.post(
            "/skills",
            data={
                "name": "blocked-upload-skill",
                "display_name": "Blocked Upload Skill",
                "description": "Should fail for blocked extension.",
                "version": "1.0.0",
                "status": "active",
                "skill_md": (
                    "---\n"
                    "name: blocked-upload-skill\n"
                    "display_name: Blocked Upload Skill\n"
                    "description: Should fail for blocked extension.\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# Blocked Upload Skill\n"
                ),
                "upload_specs_json": json.dumps(
                    [{"index": 0, "path": "scripts/malware.exe", "conflict": "replace"}]
                ),
                "upload_files": (BytesIO(b"MZ"), "malware.exe"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(302, blocked_response.status_code)
        self.assertIn("/skills/new", str(blocked_response.headers.get("Location") or ""))
        with session_scope() as session:
            blocked = (
                session.execute(select(Skill).where(Skill.name == "blocked-upload-skill"))
                .scalars()
                .first()
            )
            self.assertIsNone(blocked)

    def test_skill_update_supports_rename_delete_replace_and_conflict_modes(self) -> None:
        skill_id = self._create_active_skill(
            name="stage5-draft-skill",
            extra_files=[
                ("scripts/old.sh", "echo old\n"),
                ("references/keep.md", "keep this\n"),
            ],
        )

        rename_delete_replace = self.client.post(
            f"/skills/{skill_id}",
            data={
                "display_name": "Stage 5 Skill",
                "description": "Skill for stage 5 web tests.",
                "status": "active",
                "new_version": "1.1.0",
                "new_skill_md": (
                    "---\n"
                    "name: stage5-draft-skill\n"
                    "display_name: Stage 5 Skill\n"
                    "description: Skill for stage 5 web tests.\n"
                    "version: 1.1.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# Stage 5 Skill\n"
                ),
                "existing_files_json": json.dumps(
                    [
                        {
                            "original_path": "scripts/old.sh",
                            "path": "scripts/new.sh",
                            "delete": False,
                        },
                        {
                            "original_path": "references/keep.md",
                            "path": "references/keep.md",
                            "delete": True,
                        },
                    ]
                ),
                "upload_specs_json": json.dumps(
                    [{"index": 0, "path": "scripts/new.sh", "conflict": "replace"}]
                ),
                "upload_files": (BytesIO(b"echo replaced\n"), "new.sh"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(302, rename_delete_replace.status_code)

        keep_both = self.client.post(
            f"/skills/{skill_id}",
            data={
                "display_name": "Stage 5 Skill",
                "description": "Skill for stage 5 web tests.",
                "status": "active",
                "new_version": "1.2.0",
                "new_skill_md": (
                    "---\n"
                    "name: stage5-draft-skill\n"
                    "display_name: Stage 5 Skill\n"
                    "description: Skill for stage 5 web tests.\n"
                    "version: 1.2.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# Stage 5 Skill\n"
                ),
                "existing_files_json": json.dumps(
                    [
                        {
                            "original_path": "scripts/new.sh",
                            "path": "scripts/new.sh",
                            "delete": False,
                        }
                    ]
                ),
                "upload_specs_json": json.dumps(
                    [{"index": 0, "path": "scripts/new.sh", "conflict": "keep_both"}]
                ),
                "upload_files": (BytesIO(b"echo keep-both\n"), "new.sh"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(302, keep_both.status_code)

        skip_conflict = self.client.post(
            f"/skills/{skill_id}",
            data={
                "display_name": "Stage 5 Skill",
                "description": "Skill for stage 5 web tests.",
                "status": "active",
                "new_version": "1.3.0",
                "new_skill_md": (
                    "---\n"
                    "name: stage5-draft-skill\n"
                    "display_name: Stage 5 Skill\n"
                    "description: Skill for stage 5 web tests.\n"
                    "version: 1.3.0\n"
                    "status: active\n"
                    "---\n\n"
                    "# Stage 5 Skill\n"
                ),
                "existing_files_json": json.dumps(
                    [
                        {
                            "original_path": "scripts/new.sh",
                            "path": "scripts/new.sh",
                            "delete": False,
                        },
                        {
                            "original_path": "scripts/new (1).sh",
                            "path": "scripts/new (1).sh",
                            "delete": False,
                        },
                    ]
                ),
                "upload_specs_json": json.dumps(
                    [{"index": 0, "path": "scripts/new.sh", "conflict": "skip"}]
                ),
                "upload_files": (BytesIO(b"echo skip\n"), "new.sh"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(302, skip_conflict.status_code)

        with session_scope() as session:
            latest_version = (
                session.execute(
                    select(SkillVersion)
                    .where(SkillVersion.skill_id == skill_id)
                    .order_by(SkillVersion.id.desc())
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(latest_version)
            assert latest_version is not None
            files = (
                session.execute(
                    select(SkillFile)
                    .where(SkillFile.skill_version_id == latest_version.id)
                    .order_by(SkillFile.path.asc())
                )
                .scalars()
                .all()
            )
            file_map = {item.path: item.content for item in files}
            self.assertIn("SKILL.md", file_map)
            self.assertIn("scripts/new.sh", file_map)
            self.assertIn("scripts/new (1).sh", file_map)
            self.assertNotIn("references/keep.md", file_map)
            self.assertEqual("echo replaced\n", file_map["scripts/new.sh"])
            self.assertEqual("echo keep-both\n", file_map["scripts/new (1).sh"])

    def test_git_based_skills_are_read_only(self) -> None:
        skill_id = self._create_active_skill(name="stage5-git-skill", source_type="git")

        edit_response = self.client.get(f"/skills/{skill_id}/edit", follow_redirects=False)
        self.assertEqual(302, edit_response.status_code)
        self.assertIn(f"/skills/{skill_id}", str(edit_response.headers.get("Location") or ""))

        update_response = self.client.post(
            f"/skills/{skill_id}",
            data={
                "display_name": "Should Not Update",
                "description": "Should remain unchanged.",
                "status": "active",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, update_response.status_code)
        self.assertIn(f"/skills/{skill_id}", str(update_response.headers.get("Location") or ""))

        delete_response = self.client.post(
            f"/skills/{skill_id}/delete",
            data={"next": "/skills"},
            follow_redirects=False,
        )
        self.assertEqual(302, delete_response.status_code)

        with session_scope() as session:
            skill = session.get(Skill, skill_id)
            self.assertIsNotNone(skill)
            assert skill is not None
            self.assertEqual("stage5-git-skill", skill.name)
            self.assertNotEqual("Should Not Update", skill.display_name)

    def test_flowchart_node_skill_routes_warn_then_reject_modes(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="stage5-model",
                provider="codex",
                config_json="{}",
            )
            model_id = int(model.id)

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
                        "model_id": model_id,
                        "config": {"task_prompt": "hello"},
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
        attach_a_payload = attach_a.get_json() or {}
        self.assertTrue(attach_a_payload.get("deprecated"))
        self.assertTrue(attach_a_payload.get("ignored"))
        self.assertEqual("warn", attach_a_payload.get("node_skill_binding_mode"))
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
        reorder_payload = reorder.get_json() or {}
        self.assertTrue(reorder_payload.get("deprecated"))
        self.assertTrue(reorder_payload.get("ignored"))
        self.assertEqual("warn", reorder_payload.get("node_skill_binding_mode"))
        self.assertIsInstance((reorder_payload.get("node") or {}).get("id"), int)

        with session_scope() as session:
            ordered_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_skills.c.skill_id)
                    .where(flowchart_node_skills.c.flowchart_node_id == task_node_id)
                    .order_by(flowchart_node_skills.c.position.asc())
                ).all()
            ]
        self.assertEqual([], ordered_skill_ids)

        detach = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills/{skill_b_id}/delete",
        )
        self.assertEqual(200, detach.status_code)
        detach_payload = detach.get_json() or {}
        self.assertTrue(detach_payload.get("deprecated"))
        self.assertTrue(detach_payload.get("ignored"))
        self.assertEqual("warn", detach_payload.get("node_skill_binding_mode"))
        with session_scope() as session:
            remaining_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_skills.c.skill_id)
                    .where(flowchart_node_skills.c.flowchart_node_id == task_node_id)
                    .order_by(flowchart_node_skills.c.position.asc())
                ).all()
            ]
        self.assertEqual([], remaining_skill_ids)

        graph_warn = self.client.post(
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
                        "id": task_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "ref_id": template_id,
                        "skill_ids": [skill_a_id, skill_b_id],
                        "x": 140,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": task_node_id,
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(200, graph_warn.status_code)
        graph_warn_payload = graph_warn.get_json() or {}
        self.assertTrue(graph_warn_payload.get("deprecated"))
        self.assertTrue(graph_warn_payload.get("ignored"))
        self.assertEqual("warn", graph_warn_payload.get("node_skill_binding_mode"))
        self.assertTrue(any("skill_ids was ignored" in item for item in (graph_warn_payload.get("warnings") or [])))

        set_reject = self.client.post(
            "/settings/runtime/node-skill-binding",
            data={"node_skill_binding_mode": "reject"},
            follow_redirects=False,
        )
        self.assertEqual(302, set_reject.status_code)

        reject_attach = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills",
            json={"skill_id": skill_a_id},
        )
        self.assertEqual(400, reject_attach.status_code)
        reject_attach_payload = reject_attach.get_json() or {}
        self.assertTrue(reject_attach_payload.get("deprecated"))
        self.assertEqual("reject", reject_attach_payload.get("node_skill_binding_mode"))

        reject_reorder = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills/reorder",
            json={"skill_ids": [skill_a_id, skill_b_id]},
        )
        self.assertEqual(400, reject_reorder.status_code)
        reject_reorder_payload = reject_reorder.get_json() or {}
        self.assertTrue(reject_reorder_payload.get("deprecated"))
        self.assertEqual("reject", reject_reorder_payload.get("node_skill_binding_mode"))

        reject_detach = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{task_node_id}/skills/{skill_b_id}/delete",
        )
        self.assertEqual(400, reject_detach.status_code)
        reject_detach_payload = reject_detach.get_json() or {}
        self.assertTrue(reject_detach_payload.get("deprecated"))
        self.assertEqual("reject", reject_detach_payload.get("node_skill_binding_mode"))

        reject_graph = self.client.post(
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
                        "id": task_node_id,
                        "node_type": FLOWCHART_NODE_TYPE_TASK,
                        "ref_id": template_id,
                        "skill_ids": [skill_a_id],
                        "x": 140,
                        "y": 0,
                    },
                ],
                "edges": [
                    {
                        "source_node_id": start_node_id,
                        "target_node_id": task_node_id,
                        "edge_mode": "solid",
                    }
                ],
            },
        )
        self.assertEqual(400, reject_graph.status_code)
        self.assertIn(
            "nodes[1].skill_ids is no longer writable",
            str((reject_graph.get_json() or {}).get("error") or ""),
        )


if __name__ == "__main__":
    unittest.main()
