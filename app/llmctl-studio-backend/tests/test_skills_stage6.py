from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask
import psycopg
from sqlalchemy import insert, select

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_SRC = REPO_ROOT / "app" / "llmctl-studio-backend" / "src"
if str(STUDIO_SRC) not in sys.path:
    sys.path.insert(0, str(STUDIO_SRC))

os.environ.setdefault(
    "LLMCTL_STUDIO_DATABASE_URI",
    "postgresql+psycopg://llmctl:llmctl@127.0.0.1:15432/llmctl_studio",
)

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
    Skill,
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
        self._base_db_uri = os.environ["LLMCTL_STUDIO_DATABASE_URI"]
        self._schema_name = f"skills_stage6_{uuid.uuid4().hex}"
        self._data_dir = tmp_dir / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._orig_db_uri = Config.SQLALCHEMY_DATABASE_URI
        self._orig_workspaces_dir = Config.WORKSPACES_DIR
        self._orig_data_dir = Config.DATA_DIR

        self._create_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._with_search_path(
            self._base_db_uri,
            self._schema_name,
        )
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
        self._drop_schema(self._schema_name)
        Config.SQLALCHEMY_DATABASE_URI = self._orig_db_uri
        Config.WORKSPACES_DIR = self._orig_workspaces_dir
        Config.DATA_DIR = self._orig_data_dir
        self._tmp.cleanup()

    def _dispose_engine(self) -> None:
        if core_db._engine is not None:
            core_db._engine.dispose()
        core_db._engine = None
        core_db.SessionLocal = None

    @staticmethod
    def _as_psycopg_uri(database_uri: str) -> str:
        if database_uri.startswith("postgresql+psycopg://"):
            return "postgresql://" + database_uri.split("://", 1)[1]
        return database_uri

    @staticmethod
    def _with_search_path(database_uri: str, schema_name: str) -> str:
        parts = urlsplit(database_uri)
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        updated_items: list[tuple[str, str]] = []
        options_value = f"-csearch_path={schema_name}"
        options_updated = False
        for key, value in query_items:
            if key == "options":
                merged = value.strip()
                if options_value not in merged:
                    merged = f"{merged} {options_value}".strip()
                updated_items.append((key, merged))
                options_updated = True
            else:
                updated_items.append((key, value))
        if not options_updated:
            updated_items.append(("options", options_value))
        query = urlencode(updated_items, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _create_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

    def _drop_schema(self, schema_name: str) -> None:
        with psycopg.connect(self._as_psycopg_uri(self._base_db_uri), autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')


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
        env["LLMCTL_STUDIO_DATABASE_URI"] = Config.SQLALCHEMY_DATABASE_URI
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

    def test_legacy_node_skill_migration_helper_removed(self) -> None:
        self.assertFalse(
            hasattr(core_db, "_migrate_flowchart_node_skills_to_agent_bindings")
        )

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
