from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import tomllib

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from storage.script_storage import write_script_file

_engine = None
SessionLocal = None
NODE_EXECUTOR_PROVIDER_ALLOWED_VALUES = ("kubernetes",)
NODE_EXECUTOR_DISPATCH_STATUS_ALLOWED_VALUES = (
    "dispatch_pending",
    "dispatch_submitted",
    "dispatch_confirmed",
    "dispatch_failed",
)
NODE_EXECUTOR_FALLBACK_REASON_ALLOWED_VALUES = (
    "provider_unavailable",
    "preflight_failed",
    "dispatch_timeout",
    "create_failed",
    "image_pull_failed",
    "config_error",
    "unknown",
)
NODE_EXECUTOR_API_FAILURE_CATEGORY_ALLOWED_VALUES = (
    "socket_missing",
    "socket_unreachable",
    "api_unreachable",
    "auth_error",
    "tls_error",
    "timeout",
    "preflight_failed",
    "unknown",
)
DB_HEALTHCHECK_REQUIRED_TABLES: tuple[str, ...] = (
    "roles",
    "agents",
    "mcp_servers",
    "integration_settings",
    "llm_models",
)
NODE_EXECUTOR_AGENT_TASK_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "ck_node_runs_selected_provider_allowed",
        "selected_provider IN ('kubernetes')",
    ),
    (
        "ck_node_runs_final_provider_allowed",
        "final_provider IN ('kubernetes')",
    ),
    (
        "ck_node_runs_dispatch_status_allowed",
        "dispatch_status IN ('dispatch_pending','dispatch_submitted','dispatch_confirmed','dispatch_failed')",
    ),
    (
        "ck_node_runs_provider_dispatch_required",
        "dispatch_status NOT IN ('dispatch_submitted','dispatch_confirmed') OR provider_dispatch_id IS NOT NULL",
    ),
    (
        "ck_node_runs_provider_dispatch_namespace",
        "provider_dispatch_id IS NULL "
        "OR provider_dispatch_id LIKE 'kubernetes:%'",
    ),
    (
        "ck_node_runs_cli_preflight_requires_fallback",
        "cli_fallback_used = 1 OR cli_preflight_passed IS NULL",
    ),
    (
        "ck_node_runs_fallback_reason_required",
        "dispatch_status != 'dispatch_failed' OR fallback_reason IS NULL OR TRIM(fallback_reason) != ''",
    ),
    (
        "ck_node_runs_fallback_reason_consistency",
        "fallback_attempted = 1 OR fallback_reason IS NULL",
    ),
    (
        "ck_node_runs_uncertain_no_fallback",
        "dispatch_uncertain = 0 OR (fallback_attempted = 0 AND fallback_reason IS NULL)",
    ),
    (
        "ck_node_runs_fallback_terminal_provider",
        "fallback_attempted = 0",
    ),
    (
        "ck_node_runs_fallback_reason_allowed",
        "fallback_reason IS NULL OR fallback_reason IN ('provider_unavailable','preflight_failed','dispatch_timeout','create_failed','image_pull_failed','config_error','unknown')",
    ),
    (
        "ck_node_runs_api_failure_category_allowed",
        "api_failure_category IS NULL OR api_failure_category IN ('socket_missing','socket_unreachable','api_unreachable','auth_error','tls_error','timeout','preflight_failed','unknown')",
    ),
    (
        "ck_node_runs_workspace_identity_format",
        "workspace_identity IS NOT NULL AND TRIM(workspace_identity) != '' "
        "AND workspace_identity NOT LIKE '%/%' "
        "AND workspace_identity NOT LIKE '%\\\\%' "
        "AND workspace_identity NOT LIKE '%://%'",
    ),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class BaseModel(Base):
    __abstract__ = True

    @classmethod
    def get(cls, session: Session, item_id):
        return session.get(cls, item_id)

    @classmethod
    def list(cls, session: Session, limit: int | None = None, offset: int = 0):
        stmt = select(cls).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return session.execute(stmt).scalars().all()

    @classmethod
    def create(cls, session: Session, **kwargs):
        instance = cls(**kwargs)
        session.add(instance)
        session.flush()
        return instance

    def save(self, session: Session):
        session.add(self)
        session.flush()
        return self

    def delete(self, session: Session) -> None:
        session.delete(self)


def init_engine(database_uri: str):
    global _engine, SessionLocal
    if _engine is None:
        if database_uri.lower().startswith("sqlite:"):
            raise RuntimeError(
                "SQLite is no longer supported. Configure a PostgreSQL database URI."
            )
        _engine = create_engine(database_uri, pool_pre_ping=True, future=True)
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def _ensure_model_metadata_loaded() -> None:
    # Import side effect: registers ORM models on Base.metadata.
    import core.models  # noqa: F401


def init_db() -> None:
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")
    _ensure_model_metadata_loaded()
    Base.metadata.create_all(bind=_engine)
    _ensure_schema()


def create_session() -> Session:
    if SessionLocal is None:
        raise RuntimeError("Database session is not initialized")
    return SessionLocal()


def _ensure_schema() -> None:
    if _engine is None:
        return
    with _engine.begin() as connection:
        _migrate_roles_schema(connection)
        role_columns = {
            "description": "TEXT",
            "details_json": "TEXT",
            "is_system": "BOOLEAN NOT NULL DEFAULT FALSE",
        }
        _ensure_columns(connection, "roles", role_columns)
        _migrate_role_payloads(connection)
        _drop_role_prompt_columns(connection)
        agent_columns = {
            "description": "TEXT",
            "autonomous_prompt": "TEXT",
            "role_id": "INTEGER",
            "is_system": "BOOLEAN NOT NULL DEFAULT FALSE",
            "last_run_task_id": "TEXT",
            "run_max_loops": "INTEGER",
            "run_end_requested": "BOOLEAN NOT NULL DEFAULT FALSE",
        }
        _ensure_columns(connection, "agents", agent_columns)
        _migrate_agent_descriptions(connection)
        _migrate_agent_status_column(connection)
        _drop_agent_is_active_column(connection)
        _ensure_agent_priority_schema(connection)
        _drop_run_is_active_column(connection)
        run_columns = {
            "name": "TEXT",
        }
        _ensure_columns(connection, "runs", run_columns)

        script_columns = {
            "file_path": "TEXT",
        }
        _ensure_columns(connection, "scripts", script_columns)
        _ensure_columns(connection, "agent_task_scripts", {"position": "INTEGER"})
        _migrate_script_storage(connection)
        _migrate_script_positions(connection)

        task_template_columns = {
            "agent_id": "INTEGER",
            "model_id": "INTEGER",
        }
        _ensure_columns(connection, "task_templates", task_template_columns)

        mcp_server_columns = {
            "server_type": "TEXT NOT NULL DEFAULT 'custom'",
        }
        _ensure_columns(connection, "mcp_servers", mcp_server_columns)
        _migrate_mcp_server_configs_to_jsonb(connection)

        flowchart_columns = {
            "description": "VARCHAR(512)",
            "max_node_executions": "INTEGER",
            "max_runtime_minutes": "INTEGER",
            "max_parallel_nodes": "INTEGER NOT NULL DEFAULT 1",
        }
        _ensure_columns(connection, "flowcharts", flowchart_columns)

        flowchart_node_columns = {
            "node_type": "TEXT NOT NULL DEFAULT 'task'",
            "ref_id": "INTEGER",
            "title": "VARCHAR(255)",
            "x": "FLOAT NOT NULL DEFAULT 0",
            "y": "FLOAT NOT NULL DEFAULT 0",
            "config_json": "TEXT",
            "model_id": "INTEGER",
        }
        _ensure_columns(connection, "flowchart_nodes", flowchart_node_columns)

        flowchart_edge_columns = {
            "source_handle_id": "VARCHAR(32)",
            "target_handle_id": "VARCHAR(32)",
            "edge_mode": "VARCHAR(16) NOT NULL DEFAULT 'solid'",
            "condition_key": "VARCHAR(128)",
            "label": "VARCHAR(255)",
        }
        _ensure_columns(connection, "flowchart_edges", flowchart_edge_columns)
        _migrate_flowchart_edge_modes(connection)

        flowchart_run_columns = {
            "celery_task_id": "VARCHAR(255)",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'queued'",
            "started_at": "DATETIME",
            "finished_at": "DATETIME",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        _ensure_columns(connection, "flowchart_runs", flowchart_run_columns)

        flowchart_run_node_columns = {
            "execution_index": "INTEGER NOT NULL DEFAULT 1",
            "agent_task_id": "INTEGER",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'queued'",
            "input_context_json": "TEXT",
            "output_state_json": "TEXT",
            "routing_state_json": "TEXT",
            "resolved_skill_ids_json": "TEXT",
            "resolved_skill_versions_json": "TEXT",
            "resolved_skill_manifest_hash": "VARCHAR(128)",
            "skill_adapter_mode": "VARCHAR(32)",
            "resolved_role_id": "INTEGER",
            "resolved_role_version": "VARCHAR(128)",
            "resolved_agent_id": "INTEGER",
            "resolved_agent_version": "VARCHAR(128)",
            "resolved_instruction_manifest_hash": "VARCHAR(128)",
            "instruction_adapter_mode": "VARCHAR(32)",
            "instruction_materialized_paths_json": "TEXT",
            "error": "TEXT",
            "started_at": "DATETIME",
            "finished_at": "DATETIME",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        _ensure_columns(connection, "flowchart_run_nodes", flowchart_run_node_columns)

        _ensure_columns(connection, "task_template_scripts", {"position": "INTEGER"})
        _ensure_columns(connection, "flowchart_node_scripts", {"position": "INTEGER"})
        _ensure_columns(connection, "flowchart_node_skills", {"position": "INTEGER"})
        _ensure_flowchart_node_attachment_schema(connection)
        _ensure_agent_skill_binding_schema(connection)
        _migrate_flowchart_node_skills_to_agent_bindings(connection)

        milestone_columns = {
            "status": "TEXT NOT NULL DEFAULT 'planned'",
            "priority": "TEXT NOT NULL DEFAULT 'medium'",
            "owner": "TEXT",
            "start_date": "DATETIME",
            "progress_percent": "INTEGER NOT NULL DEFAULT 0",
            "health": "TEXT NOT NULL DEFAULT 'green'",
            "success_criteria": "TEXT",
            "dependencies": "TEXT",
            "links": "TEXT",
            "latest_update": "TEXT",
        }
        _ensure_columns(connection, "milestones", milestone_columns)
        _migrate_milestone_status(connection)

        existing_agent_task_columns = _table_columns(connection, "agent_tasks")
        task_columns = {
            "run_id": "INTEGER",
            "task_template_id": "INTEGER",
            "model_id": "INTEGER",
            "flowchart_id": "INTEGER",
            "flowchart_run_id": "INTEGER",
            "flowchart_node_id": "INTEGER",
            "kind": "TEXT",
            "integration_keys_json": "TEXT",
            "current_stage": "TEXT",
            "stage_logs": "TEXT",
            "resolved_role_id": "INTEGER",
            "resolved_role_version": "VARCHAR(128)",
            "resolved_agent_id": "INTEGER",
            "resolved_agent_version": "VARCHAR(128)",
            "resolved_skill_ids_json": "TEXT",
            "resolved_skill_versions_json": "TEXT",
            "resolved_skill_manifest_hash": "VARCHAR(128)",
            "skill_adapter_mode": "VARCHAR(32)",
            "resolved_instruction_manifest_hash": "VARCHAR(128)",
            "instruction_adapter_mode": "VARCHAR(32)",
            "instruction_materialized_paths_json": "TEXT",
            "selected_provider": "TEXT NOT NULL DEFAULT 'kubernetes'",
            "final_provider": "TEXT NOT NULL DEFAULT 'kubernetes'",
            "provider_dispatch_id": "TEXT",
            "workspace_identity": "TEXT NOT NULL DEFAULT 'default'",
            "dispatch_status": "TEXT NOT NULL DEFAULT 'dispatch_pending'",
            "fallback_attempted": "BOOLEAN NOT NULL DEFAULT FALSE",
            "fallback_reason": "TEXT",
            "dispatch_uncertain": "BOOLEAN NOT NULL DEFAULT FALSE",
            "api_failure_category": "TEXT",
            "cli_fallback_used": "BOOLEAN NOT NULL DEFAULT FALSE",
            "cli_preflight_passed": "BOOLEAN",
        }
        _ensure_columns(connection, "agent_tasks", task_columns)
        _migrate_agent_task_node_executor_fields(connection, existing_agent_task_columns)
        _ensure_agent_tasks_node_executor_checks_sqlite(connection)
        _migrate_agent_task_agent_nullable(connection)
        _migrate_agent_task_kind_values(connection)
        _drop_pipeline_schema(connection)
        _ensure_flowchart_indexes(connection)
        _ensure_rag_schema(connection)
        _ensure_rag_indexes(connection)
        _ensure_chat_schema(connection)
        _ensure_chat_indexes(connection)
        _drop_agent_utility_ownership(connection)
        _ensure_canonical_workflow_views(connection)


def _ensure_columns(connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(connection, table)
    for name, col_type in columns.items():
        if name in existing:
            continue
        if connection.dialect.name == "postgresql":
            col_type = _normalize_postgres_sql(col_type)
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")
        )


def _migrate_mcp_server_configs_to_jsonb(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    tables = _table_names(connection)
    if "mcp_servers" not in tables:
        return

    columns = inspect(connection).get_columns("mcp_servers")
    config_column = next(
        (column for column in columns if str(column.get("name")) == "config_json"),
        None,
    )
    if config_column is None:
        connection.execute(
            text(
                "ALTER TABLE mcp_servers "
                "ADD COLUMN config_json JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        return

    visit_name = str(
        getattr(config_column.get("type"), "__visit_name__", "")
    ).lower()
    if visit_name == "jsonb":
        return

    rows = connection.execute(
        text("SELECT id, server_key, config_json FROM mcp_servers ORDER BY id ASC")
    ).all()
    normalized_payloads: dict[int, str] = {}
    for row in rows:
        row_id = int(row[0])
        server_key = str(row[1] or "").strip()
        raw_config = row[2]
        try:
            normalized = _parse_legacy_mcp_config_for_jsonb_migration(
                raw_config,
                server_key=server_key,
            )
        except ValueError as exc:
            raise RuntimeError(
                "Failed to migrate mcp_servers.config_json to JSONB for "
                f"row id={row_id}, server_key='{server_key}': {exc}"
            ) from exc
        normalized_payloads[row_id] = json.dumps(normalized, sort_keys=True)

    for row_id, payload in normalized_payloads.items():
        connection.execute(
            text(
                "UPDATE mcp_servers "
                "SET config_json = :config_json "
                "WHERE id = :id"
            ),
            {"id": row_id, "config_json": payload},
        )

    connection.execute(
        text(
            "ALTER TABLE mcp_servers "
            "ALTER COLUMN config_json TYPE JSONB "
            "USING config_json::jsonb"
        )
    )
    connection.execute(
        text("ALTER TABLE mcp_servers ALTER COLUMN config_json SET NOT NULL")
    )


def _parse_legacy_mcp_config_for_jsonb_migration(
    raw_config: object,
    *,
    server_key: str,
) -> dict[str, object]:
    from core.mcp_config import parse_mcp_config, validate_server_key

    validate_server_key(server_key)
    if isinstance(raw_config, dict):
        return parse_mcp_config(raw_config, server_key=server_key)
    if not isinstance(raw_config, str):
        raise ValueError("config_json must be text or JSON object.")

    stripped = raw_config.strip()
    if not stripped:
        raise ValueError("config_json is empty.")

    try:
        parsed_payload = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            parsed_payload = tomllib.loads(stripped)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(
                "config_json is neither valid JSON nor valid legacy TOML."
            ) from exc
    return parse_mcp_config(parsed_payload, server_key=server_key)


def _normalize_postgres_sql(sql: str) -> str:
    return (
        sql.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
        .replace("datetime", "timestamp with time zone")
        .replace("DEFAULT 0", "DEFAULT FALSE")
        .replace("default 0", "default false")
        .replace("DEFAULT 1", "DEFAULT TRUE")
        .replace("default 1", "default true")
    )


def _execute_ddl(connection, ddl_sql: str) -> None:
    if connection.dialect.name == "postgresql":
        ddl_sql = _normalize_postgres_sql(ddl_sql)
    connection.execute(text(ddl_sql))


def _bool_sql_literal(connection, value: bool) -> str:
    if connection.dialect.name == "postgresql":
        return "TRUE" if value else "FALSE"
    return "1" if value else "0"


def _quote_sqlite_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _in_list_sql(values: tuple[str, ...]) -> str:
    return ", ".join(_quote_sqlite_literal(value) for value in values)


def _sqlite_table_sql(connection, table: str) -> str:
    if connection.dialect.name != "sqlite":
        return ""
    row = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = :name"
        ),
        {"name": table},
    ).fetchone()
    if row is None:
        return ""
    return str(row[0] or "")


def _sqlite_table_has_named_check(
    connection,
    table: str,
    constraint_name: str,
) -> bool:
    table_sql = _sqlite_table_sql(connection, table)
    if not table_sql:
        return False
    return f"constraint {constraint_name.lower()} check" in table_sql.lower()


def _migrate_agent_task_node_executor_fields(
    connection,
    existing_columns_before_add: set[str],
) -> None:
    tables = _table_names(connection)
    if "agent_tasks" not in tables:
        return

    provider_values = _in_list_sql(NODE_EXECUTOR_PROVIDER_ALLOWED_VALUES)
    dispatch_values = _in_list_sql(NODE_EXECUTOR_DISPATCH_STATUS_ALLOWED_VALUES)
    fallback_reason_values = _in_list_sql(NODE_EXECUTOR_FALLBACK_REASON_ALLOWED_VALUES)
    api_failure_values = _in_list_sql(NODE_EXECUTOR_API_FAILURE_CATEGORY_ALLOWED_VALUES)
    false_literal = _bool_sql_literal(connection, False)
    true_literal = _bool_sql_literal(connection, True)

    connection.execute(
        text(
            "UPDATE agent_tasks SET selected_provider = 'kubernetes' "
            "WHERE selected_provider IS NULL OR selected_provider NOT IN "
            f"({provider_values})"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET final_provider = 'kubernetes' "
            "WHERE final_provider IS NULL OR final_provider NOT IN "
            f"({provider_values})"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks "
            "SET provider_dispatch_id = "
            "(CASE "
            "WHEN selected_provider IN ('kubernetes') "
            "THEN selected_provider "
            "ELSE 'kubernetes' "
            "END) || :legacy_prefix || id "
            "WHERE provider_dispatch_id IS NOT NULL "
            "AND provider_dispatch_id NOT LIKE 'kubernetes:%'"
        ),
        {"legacy_prefix": ":legacy-"},
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET workspace_identity = 'default' "
            "WHERE workspace_identity IS NULL OR TRIM(workspace_identity) = ''"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET workspace_identity = 'default' "
            "WHERE workspace_identity LIKE '%/%' "
            "OR workspace_identity LIKE '%\\\\%' "
            "OR workspace_identity LIKE '%://%'"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET dispatch_status = 'dispatch_pending' "
            "WHERE dispatch_status IS NULL OR dispatch_status NOT IN "
            f"({dispatch_values})"
        )
    )
    connection.execute(
        text(
            f"UPDATE agent_tasks SET fallback_attempted = {false_literal} "
            "WHERE fallback_attempted IS NULL"
        )
    )
    connection.execute(
        text(
            f"UPDATE agent_tasks SET dispatch_uncertain = {false_literal} "
            "WHERE dispatch_uncertain IS NULL"
        )
    )
    connection.execute(
        text(
            f"UPDATE agent_tasks SET cli_fallback_used = {false_literal} "
            "WHERE cli_fallback_used IS NULL"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET fallback_reason = NULL "
            "WHERE fallback_reason IS NOT NULL AND fallback_reason NOT IN "
            f"({fallback_reason_values})"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET api_failure_category = NULL "
            "WHERE api_failure_category IS NOT NULL AND api_failure_category NOT IN "
            f"({api_failure_values})"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET cli_preflight_passed = NULL "
            f"WHERE cli_fallback_used = {false_literal}"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET fallback_reason = NULL "
            f"WHERE fallback_attempted = {false_literal}"
        )
    )
    connection.execute(
        text(
            f"UPDATE agent_tasks SET fallback_attempted = {false_literal}, fallback_reason = NULL "
            f"WHERE fallback_attempted = {true_literal}"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks SET final_provider = 'kubernetes' "
            "WHERE final_provider IS NULL OR TRIM(final_provider) = ''"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks "
            f"SET fallback_attempted = {false_literal}, fallback_reason = NULL "
            f"WHERE dispatch_uncertain = {true_literal}"
        )
    )
    connection.execute(
        text(
            "UPDATE agent_tasks "
            "SET provider_dispatch_id = "
            "(CASE "
            "WHEN selected_provider IN ('kubernetes') "
            "THEN selected_provider "
            "ELSE 'kubernetes' "
            "END) || :legacy_prefix || id "
            "WHERE dispatch_status IN ('dispatch_submitted','dispatch_confirmed') "
            "AND provider_dispatch_id IS NULL"
        ),
        {"legacy_prefix": ":legacy-"},
    )

    # One-time legacy baseline backfill when new columns first land.
    if "provider_dispatch_id" not in existing_columns_before_add:
        connection.execute(
            text(
                "UPDATE agent_tasks "
                "SET provider_dispatch_id = :legacy_kubernetes_prefix || id "
                "WHERE provider_dispatch_id IS NULL"
            ),
            {"legacy_kubernetes_prefix": "kubernetes:legacy-kubernetes-"},
        )
    if "dispatch_status" not in existing_columns_before_add:
        connection.execute(
            text(
                "UPDATE agent_tasks SET dispatch_status = 'dispatch_confirmed' "
                "WHERE dispatch_status = 'dispatch_pending'"
            )
        )
    if "selected_provider" not in existing_columns_before_add:
        connection.execute(
            text(
                "UPDATE agent_tasks SET selected_provider = 'kubernetes' "
                "WHERE selected_provider IS NULL OR selected_provider = ''"
            )
        )
    if "final_provider" not in existing_columns_before_add:
        connection.execute(
            text(
                "UPDATE agent_tasks SET final_provider = 'kubernetes' "
                "WHERE final_provider IS NULL OR final_provider = ''"
            )
        )
    if "workspace_identity" not in existing_columns_before_add:
        connection.execute(
            text(
                "UPDATE agent_tasks SET workspace_identity = 'default' "
                "WHERE workspace_identity IS NULL OR workspace_identity = ''"
            )
        )


def _ensure_agent_tasks_node_executor_checks_sqlite(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    if "agent_tasks" not in _table_names(connection):
        return
    if all(
        _sqlite_table_has_named_check(connection, "agent_tasks", name)
        for name, _expr in NODE_EXECUTOR_AGENT_TASK_CHECKS
    ):
        return

    dependent_views = _capture_sqlite_views_for_table(connection, "agent_tasks")
    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        _drop_sqlite_views(connection, dependent_views)
        info_rows = connection.execute(
            text("PRAGMA table_info(agent_tasks)")
        ).fetchall()
        column_info = []
        pk_columns = []
        insert_columns = []
        for row in info_rows:
            name = row[1]
            col_type = row[2] or ""
            notnull = bool(row[3])
            default = row[4]
            pk = row[5]
            column_info.append(
                {
                    "name": name,
                    "type": col_type,
                    "notnull": notnull,
                    "default": default,
                    "pk": pk,
                }
            )
            insert_columns.append(name)
            if pk:
                pk_columns.append(name)
        if not column_info:
            return

        column_defs = []
        for col in column_info:
            col_def = f"{col['name']} {col['type']}".strip()
            if col["notnull"]:
                col_def += " NOT NULL"
            if col["default"] is not None:
                col_def += f" DEFAULT {col['default']}"
            if len(pk_columns) == 1 and col["name"] in pk_columns:
                col_def += " PRIMARY KEY"
            column_defs.append(col_def)

        if len(pk_columns) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        foreign_keys = connection.execute(
            text("PRAGMA foreign_key_list(agent_tasks)")
        ).fetchall()
        for row in foreign_keys:
            from_col = row[3]
            to_table = row[2]
            to_col = row[4]
            column_defs.append(
                f"FOREIGN KEY({from_col}) REFERENCES {to_table} ({to_col})"
            )

        for name, expr in NODE_EXECUTOR_AGENT_TASK_CHECKS:
            column_defs.append(f"CONSTRAINT {name} CHECK ({expr})")

        connection.execute(text("DROP TABLE IF EXISTS agent_tasks_new"))
        connection.execute(
            text("CREATE TABLE agent_tasks_new (" + ", ".join(column_defs) + ")")
        )
        connection.execute(
            text(
                "INSERT INTO agent_tasks_new ("
                + ", ".join(insert_columns)
                + ") SELECT "
                + ", ".join(insert_columns)
                + " FROM agent_tasks"
            )
        )
        connection.execute(text("DROP TABLE agent_tasks"))
        connection.execute(text("ALTER TABLE agent_tasks_new RENAME TO agent_tasks"))
    finally:
        _restore_sqlite_views(connection, dependent_views)
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _table_columns(connection, table: str) -> set[str]:
    table_names = _table_names(connection)
    if table not in table_names:
        return set()
    return {
        str(column.get("name"))
        for column in inspect(connection).get_columns(table)
        if column.get("name")
    }


def _table_names(connection) -> set[str]:
    return {str(name) for name in inspect(connection).get_table_names()}


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _capture_sqlite_views_for_table(
    connection, table: str
) -> list[tuple[str, str]]:
    if connection.dialect.name != "sqlite":
        return []
    rows = connection.execute(
        text(
            "SELECT name, sql "
            "FROM sqlite_master "
            "WHERE type='view' "
            "ORDER BY rowid"
        )
    ).fetchall()
    normalized_table = str(table).strip().lower()
    views: list[tuple[str, str]] = []
    for row in rows:
        name = row[0]
        create_sql = row[1]
        if not name or not create_sql:
            continue
        if normalized_table in str(create_sql).lower():
            views.append((str(name), str(create_sql)))
    return views


def _drop_sqlite_views(connection, views: list[tuple[str, str]]) -> None:
    if connection.dialect.name != "sqlite":
        return
    for name, _ in views:
        connection.execute(text(f"DROP VIEW IF EXISTS {_quote_identifier(name)}"))


def _restore_sqlite_views(connection, views: list[tuple[str, str]]) -> None:
    if connection.dialect.name != "sqlite":
        return
    for _, create_sql in views:
        connection.execute(text(create_sql))


def _migrate_roles_schema(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    tables = _table_names(connection)
    has_agent_types = "agent_types" in tables
    has_roles = "roles" in tables

    if has_agent_types and not has_roles:
        connection.execute(text("ALTER TABLE agent_types RENAME TO roles"))
        has_roles = True
        has_agent_types = False

    if has_agent_types and has_roles:
        roles_count = connection.execute(text("SELECT COUNT(*) FROM roles")).scalar()
        if roles_count == 0:
            role_columns = _table_columns(connection, "roles")
            if "prompt_json" in role_columns or "prompt_text" in role_columns:
                connection.execute(
                    text(
                        "INSERT INTO roles (id, name, prompt_json, prompt_text, created_at, updated_at) "
                        "SELECT id, name, prompt_json, prompt_text, created_at, updated_at FROM agent_types"
                    )
                )
            else:
                rows = connection.execute(
                    text(
                        "SELECT id, name, prompt_json, prompt_text, created_at, updated_at "
                        "FROM agent_types"
                    )
                ).fetchall()
                for row in rows:
                    data = row._mapping
                    description = None
                    details_payload = None
                    prompt_json = data["prompt_json"]
                    prompt_text = data["prompt_text"]
                    if prompt_json:
                        try:
                            payload = json.loads(prompt_json)
                        except json.JSONDecodeError:
                            payload = None
                        if isinstance(payload, dict):
                            details_payload = dict(payload)
                            prompt_value = details_payload.pop("prompt", None)
                            if isinstance(prompt_value, str):
                                description = prompt_value.strip() or None
                            details_payload.pop("name", None)
                            details_payload.pop("title", None)
                        elif isinstance(payload, str):
                            description = payload.strip() or None
                    if description is None and prompt_text:
                        description = prompt_text.strip() or None
                    if details_payload is None:
                        details_payload = {}
                    connection.execute(
                        text(
                            "INSERT INTO roles "
                            "(id, name, description, details_json, created_at, updated_at) "
                            "VALUES (:id, :name, :description, :details_json, :created_at, :updated_at)"
                        ),
                        {
                            "id": data["id"],
                            "name": data["name"],
                            "description": description,
                            "details_json": json.dumps(
                                details_payload, indent=2, sort_keys=True
                            ),
                            "created_at": data["created_at"],
                            "updated_at": data["updated_at"],
                        },
                    )
        connection.execute(text("DROP TABLE agent_types"))

    agent_columns = _table_columns(connection, "agents")
    if "agent_type_id" in agent_columns and "role_id" not in agent_columns:
        _migrate_agent_role_column(connection, agent_columns)


def _migrate_role_payloads(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    role_columns = _table_columns(connection, "roles")
    if "description" not in role_columns or "details_json" not in role_columns:
        return
    has_prompt_json = "prompt_json" in role_columns
    has_prompt_text = "prompt_text" in role_columns
    if not has_prompt_json and not has_prompt_text:
        return
    select_columns = [
        "id",
        "name",
        "description",
        "details_json",
        "prompt_json" if has_prompt_json else "NULL as prompt_json",
        "prompt_text" if has_prompt_text else "NULL as prompt_text",
    ]
    rows = connection.execute(
        text(f"SELECT {', '.join(select_columns)} FROM roles")
    ).fetchall()
    for row in rows:
        data = row._mapping
        description = data["description"]
        details_json = data["details_json"]
        prompt_json = data["prompt_json"]
        prompt_text = data["prompt_text"]

        updated_fields = {}

        details_payload = None
        if (description is None or details_json is None) and prompt_json:
            try:
                payload = json.loads(prompt_json)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                details_payload = dict(payload)
                prompt_value = details_payload.pop("prompt", None)
                if description is None and isinstance(prompt_value, str):
                    description = prompt_value.strip() or None
                details_payload.pop("name", None)
                details_payload.pop("title", None)
            elif isinstance(payload, str) and description is None:
                description = payload.strip() or None

        if description is None and prompt_text:
            description = prompt_text.strip() or None

        if details_json is None:
            if details_payload is None:
                details_payload = {}
            details_json = json.dumps(details_payload, indent=2, sort_keys=True)

        if data["description"] != description or data["details_json"] != details_json:
            connection.execute(
                text(
                    "UPDATE roles "
                    "SET description = :description, details_json = :details_json "
                    "WHERE id = :id"
                ),
                {
                    "description": description,
                    "details_json": details_json,
                    "id": data["id"],
                },
            )


def _drop_role_prompt_columns(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    role_columns = _table_columns(connection, "roles")
    drop_columns = [
        name for name in ("prompt_json", "prompt_text") if name in role_columns
    ]
    if not drop_columns:
        return

    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        info_rows = connection.execute(text("PRAGMA table_info(roles)")).fetchall()
        column_info = []
        pk_columns = []
        insert_columns = []
        for row in info_rows:
            name = row[1]
            if name in drop_columns:
                continue
            col_type = row[2] or ""
            notnull = bool(row[3])
            default = row[4]
            pk = row[5]
            column_info.append(
                {
                    "name": name,
                    "type": col_type,
                    "notnull": notnull,
                    "default": default,
                    "pk": pk,
                }
            )
            insert_columns.append(name)
            if pk:
                pk_columns.append(name)
        if not column_info:
            return

        column_defs = []
        for col in column_info:
            col_def = f"{col['name']} {col['type']}".strip()
            if col["notnull"]:
                col_def += " NOT NULL"
            if col["default"] is not None:
                col_def += f" DEFAULT {col['default']}"
            if len(pk_columns) == 1 and col["name"] in pk_columns:
                col_def += " PRIMARY KEY"
            column_defs.append(col_def)

        if len(pk_columns) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        foreign_keys = connection.execute(
            text("PRAGMA foreign_key_list(roles)")
        ).fetchall()
        for row in foreign_keys:
            from_col = row[3]
            to_table = row[2]
            to_col = row[4]
            column_defs.append(
                f"FOREIGN KEY({from_col}) REFERENCES {to_table} ({to_col})"
            )

        connection.execute(text("DROP TABLE IF EXISTS roles_new"))
        connection.execute(
            text("CREATE TABLE roles_new (" + ", ".join(column_defs) + ")")
        )
        connection.execute(
            text(
                "INSERT INTO roles_new ("
                + ", ".join(insert_columns)
                + ") SELECT "
                + ", ".join(insert_columns)
                + " FROM roles"
            )
        )
        connection.execute(text("DROP TABLE roles"))
        connection.execute(text("ALTER TABLE roles_new RENAME TO roles"))
    finally:
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _migrate_agent_descriptions(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    agent_columns = _table_columns(connection, "agents")
    if "description" not in agent_columns:
        return
    has_prompt_json = "prompt_json" in agent_columns
    has_prompt_text = "prompt_text" in agent_columns
    if not has_prompt_json and not has_prompt_text:
        return
    select_columns = [
        "id",
        "name",
        "description",
        "prompt_json" if has_prompt_json else "NULL as prompt_json",
        "prompt_text" if has_prompt_text else "NULL as prompt_text",
    ]
    rows = connection.execute(
        text(f"SELECT {', '.join(select_columns)} FROM agents")
    ).fetchall()
    for row in rows:
        data = row._mapping
        if data["description"]:
            continue
        description = None
        prompt_json = data["prompt_json"]
        prompt_text = data["prompt_text"]
        if prompt_json:
            try:
                payload = json.loads(prompt_json)
            except json.JSONDecodeError:
                payload = prompt_json
            if isinstance(payload, dict):
                description_value = payload.get("description") or payload.get("prompt")
                if isinstance(description_value, str):
                    description = description_value.strip() or None
            elif isinstance(payload, str):
                description = payload.strip() or None
        if description is None and prompt_text:
            description = prompt_text.strip() or None
        if description is None and data["name"]:
            description = data["name"]
        if description is None:
            continue
        connection.execute(
            text("UPDATE agents SET description = :description WHERE id = :id"),
            {"description": description, "id": data["id"]},
        )


def _migrate_agent_status_column(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    agent_columns = _table_columns(connection, "agents")
    if "status" not in agent_columns:
        return
    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        info_rows = connection.execute(text("PRAGMA table_info(agents)")).fetchall()
        column_info = []
        pk_columns = []
        insert_columns = []
        for row in info_rows:
            name = row[1]
            if name == "status":
                continue
            col_type = row[2] or ""
            notnull = bool(row[3])
            default = row[4]
            pk = row[5]
            column_info.append(
                {
                    "name": name,
                    "type": col_type,
                    "notnull": notnull,
                    "default": default,
                    "pk": pk,
                }
            )
            insert_columns.append(name)
            if pk:
                pk_columns.append(name)
        if not column_info:
            return

        column_defs = []
        for col in column_info:
            col_def = f"{col['name']} {col['type']}".strip()
            if col["notnull"]:
                col_def += " NOT NULL"
            if col["default"] is not None:
                col_def += f" DEFAULT {col['default']}"
            if len(pk_columns) == 1 and col["name"] in pk_columns:
                col_def += " PRIMARY KEY"
            column_defs.append(col_def)

        if len(pk_columns) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        foreign_keys = connection.execute(
            text("PRAGMA foreign_key_list(agents)")
        ).fetchall()
        for row in foreign_keys:
            from_col = row[3]
            to_table = row[2]
            to_col = row[4]
            column_defs.append(
                f"FOREIGN KEY({from_col}) REFERENCES {to_table} ({to_col})"
            )

        connection.execute(text("DROP TABLE IF EXISTS agents_new"))
        connection.execute(
            text("CREATE TABLE agents_new (" + ", ".join(column_defs) + ")")
        )
        connection.execute(
            text(
                "INSERT INTO agents_new ("
                + ", ".join(insert_columns)
                + ") SELECT "
                + ", ".join(insert_columns)
                + " FROM agents"
            )
        )
        connection.execute(text("DROP TABLE agents"))
        connection.execute(text("ALTER TABLE agents_new RENAME TO agents"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agents_role_id ON agents (role_id)")
        )
    finally:
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _drop_columns_sqlite(
    connection,
    table: str,
    drop_columns: set[str],
    index_statements: list[str] | None = None,
) -> None:
    if connection.dialect.name != "sqlite":
        return
    table_columns = _table_columns(connection, table)
    if not table_columns or not (drop_columns & table_columns):
        return
    dependent_views = _capture_sqlite_views_for_table(connection, table)
    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        _drop_sqlite_views(connection, dependent_views)
        info_rows = connection.execute(
            text(f"PRAGMA table_info({table})")
        ).fetchall()
        column_info = []
        pk_columns = []
        insert_columns = []
        for row in info_rows:
            name = row[1]
            if name in drop_columns:
                continue
            col_type = row[2] or ""
            notnull = bool(row[3])
            default = row[4]
            pk = row[5]
            column_info.append(
                {
                    "name": name,
                    "type": col_type,
                    "notnull": notnull,
                    "default": default,
                    "pk": pk,
                }
            )
            insert_columns.append(name)
            if pk:
                pk_columns.append(name)
        if not column_info:
            return

        column_defs = []
        for col in column_info:
            col_def = f"{col['name']} {col['type']}".strip()
            if col["notnull"]:
                col_def += " NOT NULL"
            if col["default"] is not None:
                col_def += f" DEFAULT {col['default']}"
            if len(pk_columns) == 1 and col["name"] in pk_columns:
                col_def += " PRIMARY KEY"
            column_defs.append(col_def)

        if len(pk_columns) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        foreign_keys = connection.execute(
            text(f"PRAGMA foreign_key_list({table})")
        ).fetchall()
        for row in foreign_keys:
            from_col = row[3]
            to_table = row[2]
            to_col = row[4]
            if from_col in drop_columns:
                continue
            column_defs.append(
                f"FOREIGN KEY({from_col}) REFERENCES {to_table} ({to_col})"
            )

        connection.execute(text(f"DROP TABLE IF EXISTS {table}_new"))
        connection.execute(
            text(f"CREATE TABLE {table}_new (" + ", ".join(column_defs) + ")")
        )
        connection.execute(
            text(
                f"INSERT INTO {table}_new ("
                + ", ".join(insert_columns)
                + ") SELECT "
                + ", ".join(insert_columns)
                + f" FROM {table}"
            )
        )
        connection.execute(text(f"DROP TABLE {table}"))
        connection.execute(text(f"ALTER TABLE {table}_new RENAME TO {table}"))
        if index_statements:
            for statement in index_statements:
                connection.execute(text(statement))
    finally:
        _restore_sqlite_views(connection, dependent_views)
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _drop_agent_is_active_column(connection) -> None:
    _drop_columns_sqlite(
        connection,
        "agents",
        {"is_active"},
        index_statements=[
            "CREATE INDEX IF NOT EXISTS ix_agents_role_id ON agents (role_id)"
        ],
    )


def _drop_run_is_active_column(connection) -> None:
    _drop_columns_sqlite(
        connection,
        "runs",
        {"is_active"},
        index_statements=[
            "CREATE INDEX IF NOT EXISTS ix_runs_agent_id ON runs (agent_id)"
        ],
    )


def _migrate_script_storage(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    columns = _table_columns(connection, "scripts")
    if "file_path" not in columns:
        return
    rows = connection.execute(
        text("SELECT id, file_name, content, file_path FROM scripts")
    ).fetchall()
    for row in rows:
        data = row._mapping
        script_id = data["id"]
        file_name = data["file_name"] or f"script-{script_id}"
        content = data["content"] or ""
        existing_path = data["file_path"]
        if existing_path and Path(existing_path).is_file():
            continue
        path = write_script_file(script_id, file_name, content)
        connection.execute(
            text("UPDATE scripts SET file_path = :file_path WHERE id = :id"),
            {"file_path": str(path), "id": script_id},
        )


def _migrate_script_positions(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    task_columns = _table_columns(connection, "agent_task_scripts")
    if "position" in task_columns:
        _assign_missing_script_positions(
            connection,
            table="agent_task_scripts",
            owner_id_column="agent_task_id",
        )


def _assign_missing_script_positions(
    connection,
    table: str,
    owner_id_column: str,
) -> None:
    existing_rows = connection.execute(
        text(
            "SELECT "
            f"{owner_id_column} as owner_id, scripts.script_type, MAX(position) as max_pos "
            f"FROM {table} "
            f"JOIN scripts ON scripts.id = {table}.script_id "
            "WHERE position IS NOT NULL "
            f"GROUP BY {owner_id_column}, scripts.script_type"
        )
    ).fetchall()
    next_positions: dict[tuple[int, str], int] = {}
    for row in existing_rows:
        data = row._mapping
        key = (data["owner_id"], data["script_type"])
        next_positions[key] = int(data["max_pos"] or 0)

    rows = connection.execute(
        text(
            "SELECT "
            f"{owner_id_column} as owner_id, {table}.script_id, scripts.script_type "
            f"FROM {table} "
            f"JOIN scripts ON scripts.id = {table}.script_id "
            "WHERE position IS NULL "
            f"ORDER BY {owner_id_column}, scripts.script_type, {table}.script_id"
        )
    ).fetchall()
    for row in rows:
        data = row._mapping
        owner_id = data["owner_id"]
        script_id = data["script_id"]
        script_type = data["script_type"]
        key = (owner_id, script_type)
        next_positions[key] = next_positions.get(key, 0) + 1
        connection.execute(
            text(
                f"UPDATE {table} SET position = :position "
                f"WHERE {owner_id_column} = :owner_id AND script_id = :script_id"
            ),
            {
                "position": next_positions[key],
                "owner_id": owner_id,
                "script_id": script_id,
            },
        )


def _migrate_agent_role_column(connection, agent_columns: set[str]) -> None:
    if connection.dialect.name != "sqlite":
        return
    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        connection.execute(text("DROP TABLE IF EXISTS agents_new"))
        connection.execute(
            text(
                "CREATE TABLE agents_new ("
                "id INTEGER NOT NULL, "
                "name VARCHAR(255) NOT NULL, "
                "role_id INTEGER, "
                "prompt_json TEXT NOT NULL, "
                "prompt_text TEXT, "
                "autonomous_prompt TEXT, "
                "task_id VARCHAR(255), "
                "last_output TEXT, "
                "last_error TEXT, "
                "last_started_at DATETIME, "
                "last_stopped_at DATETIME, "
                "last_run_at DATETIME, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(role_id) REFERENCES roles (id)"
                ")"
            )
        )

        insert_columns = [
            "id",
            "name",
            "role_id",
            "prompt_json",
            "prompt_text",
            "autonomous_prompt",
            "task_id",
            "last_output",
            "last_error",
            "last_started_at",
            "last_stopped_at",
            "last_run_at",
            "created_at",
            "updated_at",
        ]
        defaults = {
            "name": "''",
            "prompt_json": "''",
            "created_at": "CURRENT_TIMESTAMP",
            "updated_at": "CURRENT_TIMESTAMP",
        }
        select_exprs = []
        for column in insert_columns:
            if column == "role_id":
                if "role_id" in agent_columns:
                    select_exprs.append("role_id")
                elif "agent_type_id" in agent_columns:
                    select_exprs.append("agent_type_id")
                else:
                    select_exprs.append("NULL")
                continue
            if column in agent_columns:
                select_exprs.append(column)
                continue
            select_exprs.append(defaults.get(column, "NULL"))

        connection.execute(
            text(
                "INSERT INTO agents_new ("
                + ", ".join(insert_columns)
                + ") SELECT "
                + ", ".join(select_exprs)
                + " FROM agents"
            )
        )
        connection.execute(text("DROP TABLE agents"))
        connection.execute(text("ALTER TABLE agents_new RENAME TO agents"))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_agents_role_id ON agents (role_id)")
        )
    finally:
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _drop_pipeline_schema(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    _drop_columns_sqlite(
        connection,
        "agent_tasks",
        {"pipeline_id", "pipeline_run_id", "pipeline_step_id"},
        index_statements=[
            "CREATE INDEX IF NOT EXISTS ix_agent_tasks_agent_id ON agent_tasks (agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_agent_tasks_run_id ON agent_tasks (run_id)",
            "CREATE INDEX IF NOT EXISTS ix_agent_tasks_task_template_id ON agent_tasks (task_template_id)",
            "CREATE INDEX IF NOT EXISTS ix_agent_tasks_flowchart_id ON agent_tasks (flowchart_id)",
            "CREATE INDEX IF NOT EXISTS ix_agent_tasks_flowchart_run_id ON agent_tasks (flowchart_run_id)",
            "CREATE INDEX IF NOT EXISTS ix_agent_tasks_flowchart_node_id ON agent_tasks (flowchart_node_id)",
        ],
    )
    connection.execute(text("DROP TABLE IF EXISTS pipeline_step_attachments"))
    connection.execute(text("DROP TABLE IF EXISTS pipeline_steps"))
    connection.execute(text("DROP TABLE IF EXISTS pipeline_runs"))
    connection.execute(text("DROP TABLE IF EXISTS pipelines"))


def _migrate_agent_task_agent_nullable(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    info_rows = connection.execute(text("PRAGMA table_info(agent_tasks)")).fetchall()
    if not info_rows:
        return
    agent_row = next((row for row in info_rows if row[1] == "agent_id"), None)
    if agent_row is None:
        return
    if agent_row[3] == 0:
        return

    dependent_views = _capture_sqlite_views_for_table(connection, "agent_tasks")
    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        _drop_sqlite_views(connection, dependent_views)
        column_info = []
        pk_columns = []
        insert_columns = []
        for row in info_rows:
            name = row[1]
            col_type = row[2] or ""
            notnull = bool(row[3])
            default = row[4]
            pk = row[5]
            column_info.append(
                {
                    "name": name,
                    "type": col_type,
                    "notnull": notnull,
                    "default": default,
                    "pk": pk,
                }
            )
            insert_columns.append(name)
            if pk:
                pk_columns.append(name)

        if not column_info:
            return

        column_defs = []
        for col in column_info:
            col_def = f"{col['name']} {col['type']}".strip()
            # This migration only relaxes agent_id nullability.
            if col["name"] != "agent_id" and col["notnull"]:
                col_def += " NOT NULL"
            if col["default"] is not None:
                col_def += f" DEFAULT {col['default']}"
            if len(pk_columns) == 1 and col["name"] in pk_columns:
                col_def += " PRIMARY KEY"
            column_defs.append(col_def)

        if len(pk_columns) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        foreign_keys = connection.execute(
            text("PRAGMA foreign_key_list(agent_tasks)")
        ).fetchall()
        for row in foreign_keys:
            from_col = row[3]
            to_table = row[2]
            to_col = row[4]
            column_defs.append(
                f"FOREIGN KEY({from_col}) REFERENCES {to_table} ({to_col})"
            )

        connection.execute(text("DROP TABLE IF EXISTS agent_tasks_new"))
        connection.execute(
            text("CREATE TABLE agent_tasks_new (" + ", ".join(column_defs) + ")")
        )
        connection.execute(
            text(
                "INSERT INTO agent_tasks_new "
                "("
                + ", ".join(insert_columns)
                + ") SELECT "
                + ", ".join(insert_columns)
                + " FROM agent_tasks"
            )
        )
        connection.execute(text("DROP TABLE agent_tasks"))
        connection.execute(text("ALTER TABLE agent_tasks_new RENAME TO agent_tasks"))
    finally:
        _restore_sqlite_views(connection, dependent_views)
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _migrate_agent_task_kind_values(connection) -> None:
    task_columns = _table_columns(connection, "agent_tasks")
    if "kind" not in task_columns or "flowchart_node_id" not in task_columns:
        return

    flowchart_node_columns = _table_columns(connection, "flowchart_nodes")
    if "node_type" in flowchart_node_columns:
        connection.execute(
            text(
                "UPDATE agent_tasks "
                "SET kind = ("
                "  SELECT 'flowchart_' || lower(trim(flowchart_nodes.node_type)) "
                "  FROM flowchart_nodes "
                "  WHERE flowchart_nodes.id = agent_tasks.flowchart_node_id"
                ") "
                "WHERE flowchart_node_id IS NOT NULL "
                "AND EXISTS ("
                "  SELECT 1 FROM flowchart_nodes "
                "  WHERE flowchart_nodes.id = agent_tasks.flowchart_node_id"
                ") "
                "AND (kind IS NULL OR trim(kind) = '' OR lower(trim(kind)) != ("
                "  SELECT 'flowchart_' || lower(trim(flowchart_nodes.node_type)) "
                "  FROM flowchart_nodes "
                "  WHERE flowchart_nodes.id = agent_tasks.flowchart_node_id"
                "))"
            )
        )

    connection.execute(
        text(
            "UPDATE agent_tasks "
            "SET kind = NULL "
            "WHERE flowchart_node_id IS NULL "
            "AND kind IS NOT NULL "
            "AND ("
            "  lower(trim(kind)) IN ('task', 'node', 'flowchart', 'flowchart_node') "
            "  OR lower(trim(kind)) LIKE 'flowchart_%'"
            ")"
        )
    )


def _migrate_milestone_status(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    milestone_columns = _table_columns(connection, "milestones")
    if "status" not in milestone_columns or "completed" not in milestone_columns:
        return
    connection.execute(
        text(
            "UPDATE milestones "
            "SET status = 'done' "
            "WHERE completed = 1 AND (status IS NULL OR status != 'done')"
        )
    )
    connection.execute(
        text(
            "UPDATE milestones "
            "SET completed = 1 "
            "WHERE status = 'done' AND (completed IS NULL OR completed = 0)"
        )
    )


def _migrate_flowchart_edge_modes(connection) -> None:
    tables = _table_names(connection)
    if "flowchart_edges" not in tables:
        return
    columns = _table_columns(connection, "flowchart_edges")
    if "edge_mode" not in columns:
        return
    connection.execute(
        text(
            "UPDATE flowchart_edges "
            "SET edge_mode = 'solid' "
            "WHERE edge_mode IS NULL "
            "OR trim(edge_mode) = '' "
            "OR lower(trim(edge_mode)) NOT IN ('solid', 'dotted')"
        )
    )


def _ensure_agent_priority_schema(connection) -> None:
    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS agent_priorities ("
            "id INTEGER PRIMARY KEY, "
            "agent_id INTEGER NOT NULL, "
            "position INTEGER NOT NULL DEFAULT 1, "
            "content TEXT NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(agent_id) REFERENCES agents (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "agent_priorities",
        {
            "agent_id": "INTEGER NOT NULL",
            "position": "INTEGER NOT NULL DEFAULT 1",
            "content": "TEXT NOT NULL",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_priorities_agent_id "
            "ON agent_priorities (agent_id)"
        )
    )


def _parse_optional_positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            parsed = int(cleaned)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _extract_agent_id_from_node_config(raw_config_json: str | None) -> int | None:
    if not raw_config_json:
        return None
    try:
        payload = json.loads(raw_config_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_optional_positive_int(payload.get("agent_id"))


def _ensure_agent_skill_binding_schema(connection) -> None:
    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS agent_skill_bindings ("
            "agent_id INTEGER NOT NULL, "
            "skill_id INTEGER NOT NULL, "
            "position INTEGER NOT NULL DEFAULT 1, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (agent_id, skill_id), "
            "FOREIGN KEY(agent_id) REFERENCES agents (id), "
            "FOREIGN KEY(skill_id) REFERENCES skills (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "agent_skill_bindings",
        {
            "agent_id": "INTEGER NOT NULL",
            "skill_id": "INTEGER NOT NULL",
            "position": "INTEGER NOT NULL DEFAULT 1",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_skill_bindings_agent_id "
            "ON agent_skill_bindings (agent_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_agent_skill_bindings_skill_id "
            "ON agent_skill_bindings (skill_id)"
        )
    )
    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS legacy_unmapped_node_skills ("
            "id INTEGER PRIMARY KEY, "
            "flowchart_node_id INTEGER NOT NULL, "
            "skill_id INTEGER NOT NULL, "
            "legacy_position INTEGER, "
            "node_ref_id INTEGER, "
            "node_config_json TEXT, "
            "reason TEXT NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE(flowchart_node_id, skill_id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "legacy_unmapped_node_skills",
        {
            "flowchart_node_id": "INTEGER NOT NULL",
            "skill_id": "INTEGER NOT NULL",
            "legacy_position": "INTEGER",
            "node_ref_id": "INTEGER",
            "node_config_json": "TEXT",
            "reason": "TEXT NOT NULL",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_legacy_unmapped_node_skills_flowchart_node_id "
            "ON legacy_unmapped_node_skills (flowchart_node_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_legacy_unmapped_node_skills_skill_id "
            "ON legacy_unmapped_node_skills (skill_id)"
        )
    )
    _ensure_node_skill_binding_deprecation_triggers(connection)


def _ensure_flowchart_node_attachment_schema(connection) -> None:
    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS flowchart_node_attachments ("
            "flowchart_node_id INTEGER NOT NULL, "
            "attachment_id INTEGER NOT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY (flowchart_node_id, attachment_id), "
            "FOREIGN KEY(flowchart_node_id) REFERENCES flowchart_nodes (id), "
            "FOREIGN KEY(attachment_id) REFERENCES attachments (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "flowchart_node_attachments",
        {
            "flowchart_node_id": "INTEGER NOT NULL",
            "attachment_id": "INTEGER NOT NULL",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_flowchart_node_attachments_flowchart_node_id "
            "ON flowchart_node_attachments (flowchart_node_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_flowchart_node_attachments_attachment_id "
            "ON flowchart_node_attachments (attachment_id)"
        )
    )


def _ensure_node_skill_binding_deprecation_triggers(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS trg_flowchart_node_skills_reject_insert "
            "BEFORE INSERT ON flowchart_node_skills "
            "WHEN EXISTS ("
            "  SELECT 1 FROM integration_settings "
            "  WHERE provider = 'llm' "
            "    AND key = 'node_skill_binding_mode' "
            "    AND lower(trim(value)) = 'reject'"
            ") "
            "BEGIN "
            "  SELECT RAISE(ABORT, 'Node-level skill bindings are deprecated. Assign skills to the Agent.'); "
            "END"
        )
    )
    connection.execute(
        text(
            "CREATE TRIGGER IF NOT EXISTS trg_flowchart_node_skills_reject_update "
            "BEFORE UPDATE ON flowchart_node_skills "
            "WHEN EXISTS ("
            "  SELECT 1 FROM integration_settings "
            "  WHERE provider = 'llm' "
            "    AND key = 'node_skill_binding_mode' "
            "    AND lower(trim(value)) = 'reject'"
            ") "
            "BEGIN "
            "  SELECT RAISE(ABORT, 'Node-level skill bindings are deprecated. Assign skills to the Agent.'); "
            "END"
        )
    )


def _migrate_flowchart_node_skills_to_agent_bindings(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    tables = _table_names(connection)
    required_tables = {
        "flowchart_node_skills",
        "flowchart_nodes",
        "task_templates",
        "agents",
        "skills",
        "agent_skill_bindings",
        "legacy_unmapped_node_skills",
    }
    if not required_tables.issubset(tables):
        return

    valid_agent_ids = {
        int(row[0])
        for row in connection.execute(text("SELECT id FROM agents")).fetchall()
        if row[0] is not None
    }
    valid_skill_ids = {
        int(row[0])
        for row in connection.execute(text("SELECT id FROM skills")).fetchall()
        if row[0] is not None
    }
    template_agent_by_id = {
        int(row[0]): int(row[1])
        for row in connection.execute(
            text(
                "SELECT id, agent_id "
                "FROM task_templates "
                "WHERE agent_id IS NOT NULL"
            )
        ).fetchall()
        if row[0] is not None and row[1] is not None
    }

    existing_pairs: set[tuple[int, int]] = set()
    max_position_by_agent: dict[int, int] = {}
    existing_rows = connection.execute(
        text(
            "SELECT agent_id, skill_id, position "
            "FROM agent_skill_bindings "
            "ORDER BY agent_id ASC, position ASC, skill_id ASC"
        )
    ).fetchall()
    for row in existing_rows:
        agent_id = _parse_optional_positive_int(row[0])
        skill_id = _parse_optional_positive_int(row[1])
        if agent_id is None or skill_id is None:
            continue
        existing_pairs.add((agent_id, skill_id))
        position = _parse_optional_positive_int(row[2]) or 0
        max_position_by_agent[agent_id] = max(
            max_position_by_agent.get(agent_id, 0), position
        )

    legacy_rows = connection.execute(
        text(
            "SELECT "
            "  fns.flowchart_node_id, "
            "  fns.skill_id, "
            "  fns.position, "
            "  fn.ref_id, "
            "  fn.config_json "
            "FROM flowchart_node_skills AS fns "
            "JOIN flowchart_nodes AS fn "
            "  ON fn.id = fns.flowchart_node_id "
            "ORDER BY "
            "  fns.flowchart_node_id ASC, "
            "  CASE WHEN fns.position IS NULL THEN 1 ELSE 0 END ASC, "
            "  fns.position ASC, "
            "  fns.skill_id ASC"
        )
    ).fetchall()

    for row in legacy_rows:
        flowchart_node_id = _parse_optional_positive_int(row[0])
        skill_id = _parse_optional_positive_int(row[1])
        legacy_position = _parse_optional_positive_int(row[2])
        node_ref_id = _parse_optional_positive_int(row[3])
        node_config_json = row[4] if isinstance(row[4], str) else None
        if flowchart_node_id is None or skill_id is None:
            continue

        if skill_id not in valid_skill_ids:
            connection.execute(
                text(
                    "INSERT OR IGNORE INTO legacy_unmapped_node_skills ("
                    "flowchart_node_id, skill_id, legacy_position, node_ref_id, node_config_json, reason"
                    ") VALUES ("
                    ":flowchart_node_id, :skill_id, :legacy_position, :node_ref_id, :node_config_json, :reason"
                    ")"
                ),
                {
                    "flowchart_node_id": flowchart_node_id,
                    "skill_id": skill_id,
                    "legacy_position": legacy_position,
                    "node_ref_id": node_ref_id,
                    "node_config_json": node_config_json,
                    "reason": "skill_not_found",
                },
            )
            continue

        resolved_agent_id = None
        config_agent_id = _extract_agent_id_from_node_config(node_config_json)
        if config_agent_id is not None and config_agent_id in valid_agent_ids:
            resolved_agent_id = config_agent_id
        elif node_ref_id is not None:
            template_agent_id = template_agent_by_id.get(node_ref_id)
            if template_agent_id is not None and template_agent_id in valid_agent_ids:
                resolved_agent_id = template_agent_id

        if resolved_agent_id is None:
            reason = "missing_agent_mapping"
            if config_agent_id is not None and config_agent_id not in valid_agent_ids:
                reason = "node_config_agent_not_found"
            elif node_ref_id is not None and node_ref_id in template_agent_by_id:
                reason = "task_template_agent_not_found"
            connection.execute(
                text(
                    "INSERT OR IGNORE INTO legacy_unmapped_node_skills ("
                    "flowchart_node_id, skill_id, legacy_position, node_ref_id, node_config_json, reason"
                    ") VALUES ("
                    ":flowchart_node_id, :skill_id, :legacy_position, :node_ref_id, :node_config_json, :reason"
                    ")"
                ),
                {
                    "flowchart_node_id": flowchart_node_id,
                    "skill_id": skill_id,
                    "legacy_position": legacy_position,
                    "node_ref_id": node_ref_id,
                    "node_config_json": node_config_json,
                    "reason": reason,
                },
            )
            continue

        pair = (resolved_agent_id, skill_id)
        if pair in existing_pairs:
            continue

        next_position = max_position_by_agent.get(resolved_agent_id, 0) + 1
        connection.execute(
            text(
                "INSERT OR IGNORE INTO agent_skill_bindings ("
                "agent_id, skill_id, position"
                ") VALUES ("
                ":agent_id, :skill_id, :position"
                ")"
            ),
            {
                "agent_id": resolved_agent_id,
                "skill_id": skill_id,
                "position": next_position,
            },
        )
        existing_pairs.add(pair)
        max_position_by_agent[resolved_agent_id] = next_position


def _ensure_rag_schema(connection) -> None:
    tables = _table_names(connection)

    rag_source_columns = {
        "name": "VARCHAR(128) NOT NULL DEFAULT ''",
        "kind": "VARCHAR(16) NOT NULL DEFAULT 'local'",
        "local_path": "TEXT",
        "git_repo": "VARCHAR(255)",
        "git_branch": "VARCHAR(128)",
        "git_dir": "TEXT",
        "drive_folder_id": "VARCHAR(255)",
        "collection": "VARCHAR(128) NOT NULL DEFAULT ''",
        "last_indexed_at": "DATETIME",
        "last_error": "TEXT",
        "indexed_file_count": "INTEGER",
        "indexed_chunk_count": "INTEGER",
        "indexed_file_types": "TEXT",
        "index_schedule_value": "INTEGER",
        "index_schedule_unit": "VARCHAR(16)",
        "index_schedule_mode": "VARCHAR(16) NOT NULL DEFAULT 'fresh'",
        "next_index_at": "DATETIME",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    if "rag_sources" in tables:
        _ensure_columns(connection, "rag_sources", rag_source_columns)

    rag_file_state_columns = {
        "source_id": "INTEGER",
        "path": "TEXT",
        "fingerprint": "VARCHAR(80)",
        "indexed": "INTEGER NOT NULL DEFAULT 0",
        "doc_type": "VARCHAR(32)",
        "chunk_count": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    if "rag_source_file_states" in tables:
        _ensure_columns(connection, "rag_source_file_states", rag_file_state_columns)

    rag_settings_columns = {
        "provider": "VARCHAR(32)",
        "key": "VARCHAR(64)",
        "value": "TEXT",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    if "rag_settings" in tables:
        _ensure_columns(connection, "rag_settings", rag_settings_columns)

    rag_retrieval_audit_columns = {
        "request_id": "VARCHAR(128)",
        "runtime_kind": "VARCHAR(32) NOT NULL DEFAULT 'unknown'",
        "flowchart_run_id": "INTEGER",
        "flowchart_node_run_id": "INTEGER",
        "provider": "VARCHAR(32) NOT NULL DEFAULT 'chroma'",
        "collection": "VARCHAR(255)",
        "source_id": "VARCHAR(255)",
        "path": "TEXT",
        "chunk_id": "VARCHAR(255)",
        "score": "FLOAT",
        "snippet": "TEXT",
        "retrieval_rank": "INTEGER",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    if "rag_retrieval_audits" in tables:
        _ensure_columns(connection, "rag_retrieval_audits", rag_retrieval_audit_columns)

    _migrate_rag_source_schedule_modes(connection)
    _drop_rag_index_job_schema(connection)


def _migrate_rag_source_schedule_modes(connection) -> None:
    tables = _table_names(connection)
    if "rag_sources" not in tables:
        return
    columns = _table_columns(connection, "rag_sources")
    if "index_schedule_mode" not in columns:
        return
    connection.execute(
        text(
            "UPDATE rag_sources "
            "SET index_schedule_mode = 'fresh' "
            "WHERE index_schedule_mode IS NULL "
            "OR trim(index_schedule_mode) = '' "
            "OR lower(trim(index_schedule_mode)) NOT IN ('fresh', 'delta')"
        )
    )


def _migrate_rag_index_job_modes(connection) -> None:
    tables = _table_names(connection)
    if "rag_index_jobs" not in tables:
        return
    columns = _table_columns(connection, "rag_index_jobs")
    if "mode" not in columns:
        return
    connection.execute(
        text(
            "UPDATE rag_index_jobs "
            "SET mode = 'fresh' "
            "WHERE mode IS NULL "
            "OR trim(mode) = '' "
            "OR lower(trim(mode)) NOT IN ('fresh', 'delta')"
        )
    )


def _migrate_rag_index_job_trigger_modes(connection) -> None:
    tables = _table_names(connection)
    if "rag_index_jobs" not in tables:
        return
    columns = _table_columns(connection, "rag_index_jobs")
    if "trigger_mode" not in columns:
        return
    connection.execute(
        text(
            "UPDATE rag_index_jobs "
            "SET trigger_mode = 'manual' "
            "WHERE trigger_mode IS NULL "
            "OR trim(trigger_mode) = '' "
            "OR lower(trim(trigger_mode)) NOT IN ('manual', 'scheduled')"
        )
    )


def _migrate_rag_index_job_statuses(connection) -> None:
    tables = _table_names(connection)
    if "rag_index_jobs" not in tables:
        return
    columns = _table_columns(connection, "rag_index_jobs")
    if "status" not in columns:
        return
    connection.execute(
        text(
            "UPDATE rag_index_jobs "
            "SET status = 'queued' "
            "WHERE status IS NULL "
            "OR trim(status) = '' "
            "OR lower(trim(status)) NOT IN "
            "('queued', 'running', 'pausing', 'paused', 'succeeded', 'failed', 'cancelled')"
        )
    )


def _drop_rag_index_job_schema(connection) -> None:
    # Stage 6 cutover: Index Jobs are fully decommissioned in favor of flowchart RAG nodes.
    connection.execute(text("DROP INDEX IF EXISTS ix_rag_index_jobs_source_id"))
    connection.execute(text("DROP INDEX IF EXISTS ix_rag_index_jobs_status"))
    connection.execute(text("DROP INDEX IF EXISTS ix_rag_index_jobs_created_at"))
    connection.execute(text("DROP TABLE IF EXISTS rag_index_jobs"))


def _ensure_rag_indexes(connection) -> None:
    tables = _table_names(connection)
    if "rag_sources" in tables:
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_rag_sources_kind ON rag_sources (kind)")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_sources_next_index_at ON rag_sources (next_index_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_sources_schedule_mode ON rag_sources (index_schedule_mode)"
            )
        )

    if "rag_source_file_states" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_source_file_states_source_id ON rag_source_file_states (source_id)"
            )
        )

    if "rag_settings" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_settings_provider ON rag_settings (provider)"
            )
        )
    if "rag_retrieval_audits" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_retrieval_audits_request_id ON rag_retrieval_audits (request_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_retrieval_audits_runtime_kind ON rag_retrieval_audits (runtime_kind)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_retrieval_audits_flowchart_run_id ON rag_retrieval_audits (flowchart_run_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_rag_retrieval_audits_flowchart_node_run_id ON rag_retrieval_audits (flowchart_node_run_id)"
            )
        )


def _ensure_chat_schema(connection) -> None:
    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS chat_threads ("
            "id INTEGER PRIMARY KEY, "
            "title VARCHAR(255) NOT NULL DEFAULT 'New Chat', "
            "status VARCHAR(32) NOT NULL DEFAULT 'active', "
            "model_id INTEGER, "
            "response_complexity VARCHAR(32) NOT NULL DEFAULT 'medium', "
            "selected_rag_collections_json TEXT, "
            "compaction_summary_json TEXT, "
            "last_activity_at DATETIME, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(model_id) REFERENCES llm_models (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "chat_threads",
        {
            "title": "VARCHAR(255) NOT NULL DEFAULT 'New Chat'",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'active'",
            "model_id": "INTEGER",
            "response_complexity": "VARCHAR(32) NOT NULL DEFAULT 'medium'",
            "selected_rag_collections_json": "TEXT",
            "compaction_summary_json": "TEXT",
            "last_activity_at": "DATETIME",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )

    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            "id INTEGER PRIMARY KEY, "
            "thread_id INTEGER NOT NULL, "
            "role VARCHAR(32) NOT NULL, "
            "content TEXT NOT NULL, "
            "token_estimate INTEGER, "
            "metadata_json TEXT, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(thread_id) REFERENCES chat_threads (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "chat_messages",
        {
            "thread_id": "INTEGER NOT NULL",
            "role": "VARCHAR(32) NOT NULL",
            "content": "TEXT NOT NULL",
            "token_estimate": "INTEGER",
            "metadata_json": "TEXT",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )

    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS chat_turns ("
            "id INTEGER PRIMARY KEY, "
            "thread_id INTEGER NOT NULL, "
            "request_id VARCHAR(64) NOT NULL, "
            "model_id INTEGER, "
            "user_message_id INTEGER, "
            "assistant_message_id INTEGER, "
            "status VARCHAR(32) NOT NULL DEFAULT 'succeeded', "
            "reason_code VARCHAR(128), "
            "error_message TEXT, "
            "selected_rag_collections_json TEXT, "
            "selected_mcp_server_keys_json TEXT, "
            "rag_health_state VARCHAR(64), "
            "context_limit_tokens INTEGER, "
            "context_usage_before INTEGER, "
            "context_usage_after INTEGER, "
            "history_tokens INTEGER, "
            "rag_tokens INTEGER, "
            "mcp_tokens INTEGER, "
            "compaction_applied BOOLEAN NOT NULL DEFAULT FALSE, "
            "compaction_metadata_json TEXT, "
            "citation_metadata_json TEXT, "
            "runtime_metadata_json TEXT, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(thread_id) REFERENCES chat_threads (id), "
            "FOREIGN KEY(model_id) REFERENCES llm_models (id), "
            "FOREIGN KEY(user_message_id) REFERENCES chat_messages (id), "
            "FOREIGN KEY(assistant_message_id) REFERENCES chat_messages (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "chat_turns",
        {
            "thread_id": "INTEGER NOT NULL",
            "request_id": "VARCHAR(64) NOT NULL",
            "model_id": "INTEGER",
            "user_message_id": "INTEGER",
            "assistant_message_id": "INTEGER",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'succeeded'",
            "reason_code": "VARCHAR(128)",
            "error_message": "TEXT",
            "selected_rag_collections_json": "TEXT",
            "selected_mcp_server_keys_json": "TEXT",
            "rag_health_state": "VARCHAR(64)",
            "context_limit_tokens": "INTEGER",
            "context_usage_before": "INTEGER",
            "context_usage_after": "INTEGER",
            "history_tokens": "INTEGER",
            "rag_tokens": "INTEGER",
            "mcp_tokens": "INTEGER",
            "compaction_applied": "BOOLEAN NOT NULL DEFAULT FALSE",
            "compaction_metadata_json": "TEXT",
            "citation_metadata_json": "TEXT",
            "runtime_metadata_json": "TEXT",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )

    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS chat_activity_events ("
            "id INTEGER PRIMARY KEY, "
            "thread_id INTEGER NOT NULL, "
            "turn_id INTEGER, "
            "event_class VARCHAR(64) NOT NULL, "
            "event_type VARCHAR(64) NOT NULL, "
            "reason_code VARCHAR(128), "
            "message TEXT, "
            "metadata_json TEXT, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "FOREIGN KEY(thread_id) REFERENCES chat_threads (id), "
            "FOREIGN KEY(turn_id) REFERENCES chat_turns (id)"
            ")"
        ),
    )
    _ensure_columns(
        connection,
        "chat_activity_events",
        {
            "thread_id": "INTEGER NOT NULL",
            "turn_id": "INTEGER",
            "event_class": "VARCHAR(64) NOT NULL",
            "event_type": "VARCHAR(64) NOT NULL",
            "reason_code": "VARCHAR(128)",
            "message": "TEXT",
            "metadata_json": "TEXT",
            "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        },
    )

    _execute_ddl(
        connection,
        (
            "CREATE TABLE IF NOT EXISTS chat_thread_mcp_servers ("
            "chat_thread_id INTEGER NOT NULL, "
            "mcp_server_id INTEGER NOT NULL, "
            "PRIMARY KEY (chat_thread_id, mcp_server_id), "
            "FOREIGN KEY(chat_thread_id) REFERENCES chat_threads (id), "
            "FOREIGN KEY(mcp_server_id) REFERENCES mcp_servers (id)"
            ")"
        ),
    )


def _ensure_chat_indexes(connection) -> None:
    tables = _table_names(connection)
    if "chat_threads" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_threads_status "
                "ON chat_threads (status)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_threads_model_id "
                "ON chat_threads (model_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_threads_last_activity_at "
                "ON chat_threads (last_activity_at)"
            )
        )
    if "chat_messages" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_messages_thread_id "
                "ON chat_messages (thread_id)"
            )
        )
    if "chat_turns" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_turns_thread_id "
                "ON chat_turns (thread_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_turns_request_id "
                "ON chat_turns (request_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_turns_reason_code "
                "ON chat_turns (reason_code)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_turns_thread_request "
                "ON chat_turns (thread_id, request_id)"
            )
        )
    if "chat_activity_events" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_activity_events_thread_id "
                "ON chat_activity_events (thread_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_activity_events_turn_id "
                "ON chat_activity_events (turn_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_activity_events_event_class "
                "ON chat_activity_events (event_class)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_activity_events_event_type "
                "ON chat_activity_events (event_type)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_chat_activity_events_reason_code "
                "ON chat_activity_events (reason_code)"
            )
        )


def _ensure_flowchart_indexes(connection) -> None:
    tables = _table_names(connection)
    required_tables = {
        "flowchart_nodes",
        "flowchart_edges",
        "flowchart_runs",
        "flowchart_run_nodes",
        "agent_tasks",
    }
    if not required_tables.issubset(tables):
        return

    statements = [
        "CREATE INDEX IF NOT EXISTS ix_flowchart_nodes_flowchart_id ON flowchart_nodes (flowchart_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_edges_flowchart_id ON flowchart_edges (flowchart_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_edges_source_node_id ON flowchart_edges (source_node_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_edges_target_node_id ON flowchart_edges (target_node_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_runs_flowchart_id ON flowchart_runs (flowchart_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_run_nodes_flowchart_run_id ON flowchart_run_nodes (flowchart_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_run_nodes_flowchart_node_id ON flowchart_run_nodes (flowchart_node_id)",
        "CREATE INDEX IF NOT EXISTS ix_flowchart_run_nodes_agent_task_id ON flowchart_run_nodes (agent_task_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_flowchart_id ON agent_tasks (flowchart_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_flowchart_run_id ON agent_tasks (flowchart_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_flowchart_node_id ON agent_tasks (flowchart_node_id)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_workspace_identity_created_at ON agent_tasks (workspace_identity, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_fallback_attempted_created_at ON agent_tasks (fallback_attempted, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_cli_fallback_used_created_at ON agent_tasks (cli_fallback_used, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_api_failure_category_created_at ON agent_tasks (api_failure_category, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_dispatch_status_created_at ON agent_tasks (dispatch_status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_final_provider_created_at ON agent_tasks (final_provider, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_dispatch_uncertain_created_at ON agent_tasks (dispatch_uncertain, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_agent_tasks_fallback_reason_created_at ON agent_tasks (fallback_reason, created_at DESC)",
    ]
    for statement in statements:
        connection.execute(text(statement))
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_tasks_provider_dispatch_id "
            "ON agent_tasks (provider_dispatch_id) "
            "WHERE provider_dispatch_id IS NOT NULL"
        )
    )

    if "flowchart_node_skills" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_flowchart_node_skills_skill_id ON flowchart_node_skills (skill_id)"
            )
        )
    if "flowchart_node_attachments" in tables:
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_flowchart_node_attachments_attachment_id "
                "ON flowchart_node_attachments (attachment_id)"
            )
        )

    # SQLite supports partial indexes; this enforces exactly one start node per flowchart.
    if connection.dialect.name == "sqlite":
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_flowchart_nodes_start_per_flowchart "
                "ON flowchart_nodes (flowchart_id) WHERE node_type = 'start'"
            )
        )


def _drop_agent_utility_ownership(connection) -> None:
    _drop_columns_sqlite(
        connection,
        "agents",
        {"model_id"},
        index_statements=[
            "CREATE INDEX IF NOT EXISTS ix_agents_role_id ON agents (role_id)"
        ],
    )
    connection.execute(text("DROP TABLE IF EXISTS agent_mcp_servers"))
    connection.execute(text("DROP TABLE IF EXISTS agent_scripts"))


def _ensure_canonical_workflow_views(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    tables = _table_names(connection)
    if "task_templates" in tables:
        connection.execute(text("DROP VIEW IF EXISTS tasks"))
        connection.execute(text("CREATE VIEW tasks AS SELECT * FROM task_templates"))
    if "agent_tasks" in tables:
        connection.execute(text("DROP VIEW IF EXISTS node_runs"))
        connection.execute(text("CREATE VIEW node_runs AS SELECT * FROM agent_tasks"))


def _assert_required_tables(connection) -> None:
    existing = _table_names(connection)
    missing = [name for name in DB_HEALTHCHECK_REQUIRED_TABLES if name not in existing]
    if missing:
        raise RuntimeError(
            "Database schema health check failed. Missing required tables: "
            + ", ".join(sorted(missing))
        )


def run_startup_db_healthcheck(
    database_uri: str,
    *,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 2.0,
) -> None:
    if not database_uri:
        raise RuntimeError("Database URI is required for startup health checks.")
    init_engine(database_uri)
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")

    timeout = max(float(timeout_seconds), 0.0)
    interval = max(float(interval_seconds), 0.1)
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while True:
        try:
            with _engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            init_db()
            with _engine.connect() as connection:
                _assert_required_tables(connection)
            return
        except Exception as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(interval)

    raise RuntimeError(
        "Database health check failed after "
        f"{timeout:.1f}s (interval {interval:.1f}s)."
    ) from last_error


@contextmanager
def session_scope():
    if SessionLocal is None:
        raise RuntimeError("Database session is not initialized")
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
