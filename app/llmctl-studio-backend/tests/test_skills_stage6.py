from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask
from sqlalchemy import insert, select, text

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

import core.db as core_db
from core.config import Config
from core.db import session_scope
from core.models import (
    Agent,
    AgentTask,
    FLOWCHART_NODE_TYPE_TASK,
    Flowchart,
    FlowchartNode,
    LLMModel,
    Script,
    Skill,
    SkillFile,
    SkillVersion,
    agent_skill_bindings,
    agent_task_scripts,
    flowchart_node_scripts,
    flowchart_node_skills,
)
from rag.web.views import bp as rag_bp
from services.skill_adapters import (
    ResolvedSkill,
    ResolvedSkillFile,
    ResolvedSkillSet,
    materialize_skill_set,
)
import web.views as studio_views


class StudioDbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._data_dir = tmp_dir / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_name = "skills-stage6.sqlite3"
        self._db_path = self._data_dir / self._db_name

        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_data_dir = Config.DATA_DIR

        Config.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self._db_path}"
        Config.WORKSPACES_DIR = str(tmp_dir / "workspaces")
        Config.DATA_DIR = str(self._data_dir)
        Path(Config.WORKSPACES_DIR).mkdir(parents=True, exist_ok=True)

        self._dispose_engine()
        core_db.init_engine(Config.SQLALCHEMY_DATABASE_URI)
        core_db.init_db()

        template_dir = STUDIO_SRC / "web" / "templates"
        app = Flask("skills-stage6-tests", template_folder=str(template_dir))
        app.config["TESTING"] = True
        app.secret_key = "skills-stage6"
        app.register_blueprint(studio_views.bp)
        app.register_blueprint(rag_bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        self._dispose_engine()
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.DATA_DIR = self._orig_data_dir
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None


class SkillsStage6Tests(StudioDbTestCase):
    def _insert_legacy_skill_script(self, *, file_name: str, content: str) -> int:
        with session_scope() as session:
            result = session.execute(
                insert(Script.__table__).values(
                    file_name=file_name,
                    file_path=None,
                    description="legacy skill script",
                    content=content,
                    script_type="skill",
                )
            )
            return int(result.inserted_primary_key[0])

    def _create_task_node(self) -> tuple[int, int]:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="stage6-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="stage6-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"task_prompt": "hello"}, sort_keys=True),
            )
            return int(flowchart.id), int(node.id)

    def test_model_layer_blocks_legacy_skill_script_create(self) -> None:
        with session_scope() as session:
            with self.assertRaisesRegex(ValueError, "Legacy script_type=skill writes are disabled"):
                Script.create(
                    session,
                    file_name="blocked.sh",
                    content="echo blocked\n",
                    script_type="skill",
                )

    def test_web_routes_block_legacy_skill_script_writes(self) -> None:
        create_response = self.client.post(
            "/scripts",
            data={
                "file_name": "legacy.sh",
                "description": "legacy",
                "script_type": "skill",
                "content": "echo legacy\n",
            },
            follow_redirects=False,
        )
        self.assertEqual(302, create_response.status_code)

        with session_scope() as session:
            count = session.execute(
                select(Script.id).where(Script.file_name == "legacy.sh")
            ).scalars().all()
        self.assertEqual([], count)

        flowchart_id, node_id = self._create_task_node()
        legacy_script_id = self._insert_legacy_skill_script(
            file_name="legacy-node.sh",
            content="echo legacy\n",
        )

        attach_response = self.client.post(
            f"/flowcharts/{flowchart_id}/nodes/{node_id}/scripts",
            json={"script_id": legacy_script_id},
        )
        self.assertEqual(400, attach_response.status_code)
        payload = attach_response.get_json() or {}
        self.assertIn("Legacy script_type=skill", str(payload.get("error") or ""))

    def test_backfill_migrates_and_maps_legacy_references(self) -> None:
        flowchart_id, node_id = self._create_task_node()
        del flowchart_id

        legacy_script_id = self._insert_legacy_skill_script(
            file_name="legacy-map.sh",
            content="echo map\n",
        )

        with session_scope() as session:
            session.execute(
                flowchart_node_scripts.insert().values(
                    flowchart_node_id=node_id,
                    script_id=legacy_script_id,
                    position=1,
                )
            )
            task = AgentTask.create(
                session,
                flowchart_node_id=node_id,
                status="queued",
                prompt="stage6",
            )
            session.execute(
                agent_task_scripts.insert().values(
                    agent_task_id=task.id,
                    script_id=legacy_script_id,
                    position=1,
                )
            )

        report_path = Path(self._tmp.name) / "backfill-report.json"
        env = os.environ.copy()
        env["LLMCTL_STUDIO_DATA_DIR"] = str(self._data_dir)
        env["LLMCTL_STUDIO_DB_NAME"] = self._db_name
        result = subprocess.run(
            [
                sys.executable,
                "app/llmctl-studio-backend/scripts/backfill_legacy_skills.py",
                "--apply",
                "--report-file",
                str(report_path),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        self.assertTrue(report_path.exists())
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("applied"))
        self.assertEqual(1, int(payload["legacy_scripts"]["migrated"]))
        self.assertEqual(1, int(payload["reference_scan"]["flowchart_node_script_refs"]))
        self.assertEqual(1, int(payload["reference_scan"]["agent_task_script_refs"]))

        with session_scope() as session:
            migrated_skill = (
                session.execute(
                    select(Skill).where(
                        Skill.source_type == "legacy_skill_script",
                        Skill.source_ref == str(legacy_script_id),
                    )
                )
                .scalars()
                .first()
            )
            self.assertIsNotNone(migrated_skill)
            attached_skill_ids = [
                int(row[0])
                for row in session.execute(
                    select(flowchart_node_skills.c.skill_id)
                    .where(flowchart_node_skills.c.flowchart_node_id == node_id)
                    .order_by(flowchart_node_skills.c.position.asc())
                ).all()
            ]
        assert migrated_skill is not None
        self.assertEqual([int(migrated_skill.id)], attached_skill_ids)

    def test_node_skill_migration_is_idempotent_and_deterministic(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="stage6-migration-model",
                provider="codex",
                config_json="{}",
            )
            primary_agent = Agent.create(
                session,
                name="stage6-primary-agent",
                prompt_json=json.dumps({"instruction": "stage6"}),
            )
            template_agent = Agent.create(
                session,
                name="stage6-template-agent",
                prompt_json=json.dumps({"instruction": "stage6"}),
            )
            flowchart = Flowchart.create(session, name="stage6-migration-flowchart")
            config_bound_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": primary_agent.id}, sort_keys=True),
            )
            template_bound_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": template_agent.id}, sort_keys=True),
            )
            duplicate_node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": primary_agent.id}, sort_keys=True),
            )

            def _create_skill(name: str) -> int:
                skill = Skill.create(
                    session,
                    name=name,
                    display_name=name.replace("-", " ").title(),
                    description="stage6 migration skill",
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
                    f"display_name: {name.replace('-', ' ').title()}\n"
                    "description: stage6 migration skill\n"
                    "version: 1.0.0\n"
                    "status: active\n"
                    "---\n\n"
                    f"# {name}\n"
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

            skill_alpha_id = _create_skill("stage6-alpha")
            skill_beta_id = _create_skill("stage6-beta")
            skill_gamma_id = _create_skill("stage6-gamma")

            # Existing binding should be preserved; migration must only append new unique pairs.
            session.execute(
                agent_skill_bindings.insert().values(
                    agent_id=primary_agent.id,
                    skill_id=skill_beta_id,
                    position=1,
                )
            )

            session.execute(
                flowchart_node_skills.insert().values(
                    flowchart_node_id=config_bound_node.id,
                    skill_id=skill_beta_id,
                    position=1,
                )
            )
            session.execute(
                flowchart_node_skills.insert().values(
                    flowchart_node_id=config_bound_node.id,
                    skill_id=skill_alpha_id,
                    position=2,
                )
            )
            session.execute(
                flowchart_node_skills.insert().values(
                    flowchart_node_id=template_bound_node.id,
                    skill_id=skill_gamma_id,
                    position=1,
                )
            )
            session.execute(
                flowchart_node_skills.insert().values(
                    flowchart_node_id=duplicate_node.id,
                    skill_id=skill_alpha_id,
                    position=1,
                )
            )
            primary_agent_id = int(primary_agent.id)
            template_agent_id = int(template_agent.id)

        assert core_db._engine is not None
        with core_db._engine.begin() as connection:
            core_db._migrate_flowchart_node_skills_to_agent_bindings(connection)
            core_db._migrate_flowchart_node_skills_to_agent_bindings(connection)

        with session_scope() as session:
            primary_rows = session.execute(
                select(agent_skill_bindings.c.skill_id, agent_skill_bindings.c.position)
                .where(agent_skill_bindings.c.agent_id == primary_agent_id)
                .order_by(agent_skill_bindings.c.position.asc(), agent_skill_bindings.c.skill_id.asc())
            ).all()
            template_rows = session.execute(
                select(agent_skill_bindings.c.skill_id, agent_skill_bindings.c.position)
                .where(agent_skill_bindings.c.agent_id == template_agent_id)
                .order_by(agent_skill_bindings.c.position.asc(), agent_skill_bindings.c.skill_id.asc())
            ).all()

        self.assertEqual(
            [(skill_beta_id, 1), (skill_alpha_id, 2)],
            [(int(skill_id), int(position)) for skill_id, position in primary_rows],
        )
        self.assertEqual(
            [(skill_gamma_id, 1)],
            [(int(skill_id), int(position)) for skill_id, position in template_rows],
        )

    def test_node_skill_migration_archives_unmapped_rows(self) -> None:
        with session_scope() as session:
            model = LLMModel.create(
                session,
                name="stage6-unmapped-model",
                provider="codex",
                config_json="{}",
            )
            flowchart = Flowchart.create(session, name="stage6-unmapped-flowchart")
            node = FlowchartNode.create(
                session,
                flowchart_id=flowchart.id,
                node_type=FLOWCHART_NODE_TYPE_TASK,
                model_id=model.id,
                config_json=json.dumps({"agent_id": 999999}, sort_keys=True),
            )
            skill = Skill.create(
                session,
                name="stage6-unmapped-skill",
                display_name="Stage6 Unmapped Skill",
                description="stage6 unmapped migration skill",
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
                "name: stage6-unmapped-skill\n"
                "display_name: Stage6 Unmapped Skill\n"
                "description: stage6 unmapped migration skill\n"
                "version: 1.0.0\n"
                "status: active\n"
                "---\n\n"
                "# Stage6 Unmapped Skill\n"
            )
            SkillFile.create(
                session,
                skill_version_id=version.id,
                path="SKILL.md",
                content=skill_md,
                checksum="",
                size_bytes=len(skill_md.encode("utf-8")),
            )
            session.execute(
                flowchart_node_skills.insert().values(
                    flowchart_node_id=node.id,
                    skill_id=skill.id,
                    position=1,
                )
            )
            node_id = int(node.id)
            skill_id = int(skill.id)

        assert core_db._engine is not None
        with core_db._engine.begin() as connection:
            core_db._migrate_flowchart_node_skills_to_agent_bindings(connection)
            archive_rows = connection.execute(
                text(
                    "SELECT flowchart_node_id, skill_id, reason "
                    "FROM legacy_unmapped_node_skills "
                    "WHERE flowchart_node_id = :node_id AND skill_id = :skill_id"
                ),
                {"node_id": node_id, "skill_id": skill_id},
            ).fetchall()

        self.assertEqual(1, len(archive_rows))
        archived = archive_rows[0]
        self.assertEqual(node_id, int(archived[0]))
        self.assertEqual(skill_id, int(archived[1]))
        self.assertEqual("node_config_agent_not_found", str(archived[2]))

    def test_concurrency_stress_100_runs_zero_skill_bleed(self) -> None:
        root = Path(self._tmp.name) / "skill-stress"
        workspaces_root = root / "workspaces"
        homes_root = root / "homes"
        workspaces_root.mkdir(parents=True, exist_ok=True)
        homes_root.mkdir(parents=True, exist_ok=True)

        def _worker(index: int) -> tuple[str, list[str], list[str]]:
            skill_name = f"stress-skill-{index}"
            skill_md = (
                "---\n"
                f"name: {skill_name}\n"
                f"display_name: {skill_name}\n"
                "description: stress\n"
                "version: 1.0.0\n"
                "status: active\n"
                "---\n\n"
                f"# {skill_name}\n"
            )
            resolved = ResolvedSkillSet(
                skills=(
                    ResolvedSkill(
                        skill_id=index + 1,
                        name=skill_name,
                        display_name=skill_name,
                        description="stress",
                        version_id=index + 1,
                        version="1.0.0",
                        manifest_hash=f"manifest-{index}",
                        files=(
                            ResolvedSkillFile(
                                path="SKILL.md",
                                content=skill_md,
                                checksum=f"checksum-{index}",
                                size_bytes=len(skill_md.encode("utf-8")),
                            ),
                        ),
                    ),
                ),
                manifest_hash=f"set-{index}",
            )
            workspace = workspaces_root / f"run-{index}-token"
            runtime_home = homes_root / f"run-{index}-token"
            codex_home = runtime_home / ".codex"
            materialize_skill_set(
                resolved,
                provider="codex",
                workspace=workspace,
                runtime_home=runtime_home,
                codex_home=codex_home,
            )
            workspace_names = sorted(
                path.name
                for path in (workspace / ".llmctl" / "skills").iterdir()
                if path.is_dir()
            )
            codex_names = sorted(
                path.name
                for path in (codex_home / "skills").iterdir()
                if path.is_dir()
            )
            return skill_name, workspace_names, codex_names

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(_worker, range(100)))

        self.assertEqual(100, len(results))
        for skill_name, workspace_names, codex_names in results:
            self.assertEqual([skill_name], workspace_names)
            self.assertEqual([skill_name], codex_names)


if __name__ == "__main__":
    unittest.main()
