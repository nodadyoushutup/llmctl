from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from storage.script_storage import write_script_file

_engine = None
SessionLocal = None


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
        _engine = create_engine(
            database_uri,
            connect_args={"check_same_thread": False},
            future=True,
        )
        SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
    return _engine


def init_db() -> None:
    if _engine is None:
        raise RuntimeError("Database engine is not initialized")
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
            "is_system": "BOOLEAN NOT NULL DEFAULT 0",
        }
        _ensure_columns(connection, "roles", role_columns)
        _migrate_role_payloads(connection)
        _drop_role_prompt_columns(connection)
        agent_columns = {
            "description": "TEXT",
            "autonomous_prompt": "TEXT",
            "role_id": "INTEGER",
            "is_system": "BOOLEAN NOT NULL DEFAULT 0",
            "last_run_task_id": "TEXT",
            "run_max_loops": "INTEGER",
            "run_end_requested": "BOOLEAN NOT NULL DEFAULT 0",
        }
        _ensure_columns(connection, "agents", agent_columns)
        _migrate_agent_descriptions(connection)
        _migrate_agent_status_column(connection)
        _drop_agent_is_active_column(connection)
        _drop_run_is_active_column(connection)
        run_columns = {
            "name": "TEXT",
        }
        _ensure_columns(connection, "runs", run_columns)

        script_columns = {
            "file_path": "TEXT",
        }
        _ensure_columns(connection, "scripts", script_columns)
        _ensure_columns(connection, "agent_scripts", {"position": "INTEGER"})
        _ensure_columns(connection, "agent_task_scripts", {"position": "INTEGER"})
        _migrate_script_storage(connection)
        _migrate_script_positions(connection)

        task_template_columns = {
            "agent_id": "INTEGER",
        }
        _ensure_columns(connection, "task_templates", task_template_columns)

        pipeline_columns = {
            "loop_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        }
        _ensure_columns(connection, "pipelines", pipeline_columns)

        pipeline_step_columns = {
            "additional_prompt": "TEXT",
        }
        _ensure_columns(connection, "pipeline_steps", pipeline_step_columns)

        task_columns = {
            "run_id": "INTEGER",
            "pipeline_id": "INTEGER",
            "pipeline_run_id": "INTEGER",
            "pipeline_step_id": "INTEGER",
            "task_template_id": "INTEGER",
            "kind": "TEXT",
            "current_stage": "TEXT",
            "stage_logs": "TEXT",
        }
        _ensure_columns(connection, "agent_tasks", task_columns)
        _migrate_agent_task_agent_nullable(connection)
        _migrate_pipeline_agent_columns(connection)


def _ensure_columns(connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        row[1]
        for row in connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
    }
    for name, col_type in columns.items():
        if name in existing:
            continue
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")
        )


def _table_columns(connection, table: str) -> set[str]:
    if connection.dialect.name != "sqlite":
        return set()
    rows = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _table_names(connection) -> set[str]:
    if connection.dialect.name != "sqlite":
        return set()
    rows = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()
    return {row[0] for row in rows}


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
    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
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
    agent_columns = _table_columns(connection, "agent_scripts")
    task_columns = _table_columns(connection, "agent_task_scripts")
    if "position" in agent_columns:
        _assign_missing_script_positions(
            connection,
            table="agent_scripts",
            owner_id_column="agent_id",
        )
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


def _migrate_pipeline_agent_columns(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    pipeline_columns = _table_columns(connection, "pipelines")
    run_columns = _table_columns(connection, "pipeline_runs")
    needs_pipeline = "agent_id" in pipeline_columns
    needs_runs = "agent_id" in run_columns
    if not needs_pipeline and not needs_runs:
        return

    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        connection.execute(text("DROP TABLE IF EXISTS pipelines_new"))
        connection.execute(text("DROP TABLE IF EXISTS pipeline_runs_new"))

        if needs_pipeline:
            connection.execute(
                text(
                    "CREATE TABLE pipelines_new ("
                    "id INTEGER NOT NULL, "
                    "name VARCHAR(255) NOT NULL, "
                    "description VARCHAR(512), "
                    "created_at DATETIME NOT NULL, "
                    "updated_at DATETIME NOT NULL, "
                    "PRIMARY KEY (id)"
                    ")"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO pipelines_new "
                    "(id, name, description, created_at, updated_at) "
                    "SELECT id, name, description, created_at, updated_at FROM pipelines"
                )
            )
            connection.execute(text("DROP TABLE pipelines"))
            connection.execute(text("ALTER TABLE pipelines_new RENAME TO pipelines"))

        if needs_runs:
            connection.execute(
                text(
                    "CREATE TABLE pipeline_runs_new ("
                    "id INTEGER NOT NULL, "
                    "pipeline_id INTEGER NOT NULL, "
                    "celery_task_id VARCHAR(255), "
                    "status VARCHAR(32) NOT NULL, "
                    "started_at DATETIME, "
                    "finished_at DATETIME, "
                    "created_at DATETIME NOT NULL, "
                    "updated_at DATETIME NOT NULL, "
                    "PRIMARY KEY (id), "
                    "FOREIGN KEY(pipeline_id) REFERENCES pipelines (id)"
                    ")"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO pipeline_runs_new "
                    "(id, pipeline_id, celery_task_id, status, started_at, "
                    "finished_at, created_at, updated_at) "
                    "SELECT id, pipeline_id, celery_task_id, status, started_at, "
                    "finished_at, created_at, updated_at FROM pipeline_runs"
                )
            )
            connection.execute(text("DROP TABLE pipeline_runs"))
            connection.execute(
                text("ALTER TABLE pipeline_runs_new RENAME TO pipeline_runs")
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_pipeline_runs_pipeline_id ON pipeline_runs (pipeline_id)"
                )
            )
    finally:
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


def _migrate_agent_task_agent_nullable(connection) -> None:
    if connection.dialect.name != "sqlite":
        return
    rows = connection.execute(text("PRAGMA table_info(agent_tasks)")).fetchall()
    if not rows:
        return
    agent_row = next((row for row in rows if row[1] == "agent_id"), None)
    if agent_row is None:
        return
    if agent_row[3] == 0:
        return

    foreign_keys_on = connection.execute(text("PRAGMA foreign_keys")).scalar()
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        connection.execute(text("DROP TABLE IF EXISTS agent_tasks_new"))
        connection.execute(
            text(
                "CREATE TABLE agent_tasks_new ("
                "id INTEGER NOT NULL, "
                "agent_id INTEGER, "
                "run_task_id VARCHAR(255), "
                "celery_task_id VARCHAR(255), "
                "pipeline_id INTEGER, "
                "pipeline_run_id INTEGER, "
                "pipeline_step_id INTEGER, "
                "task_template_id INTEGER, "
                "status VARCHAR(32) NOT NULL, "
                "kind VARCHAR(32), "
                "prompt TEXT, "
                "output TEXT, "
                "error TEXT, "
                "started_at DATETIME, "
                "finished_at DATETIME, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(agent_id) REFERENCES agents (id), "
                "FOREIGN KEY(pipeline_id) REFERENCES pipelines (id), "
                "FOREIGN KEY(pipeline_run_id) REFERENCES pipeline_runs (id), "
                "FOREIGN KEY(pipeline_step_id) REFERENCES pipeline_steps (id), "
                "FOREIGN KEY(task_template_id) REFERENCES task_templates (id)"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_tasks_new "
                "(id, agent_id, run_task_id, celery_task_id, pipeline_id, "
                "pipeline_run_id, pipeline_step_id, task_template_id, status, "
                "kind, prompt, output, error, started_at, finished_at, "
                "created_at, updated_at) "
                "SELECT id, agent_id, run_task_id, celery_task_id, pipeline_id, "
                "pipeline_run_id, pipeline_step_id, task_template_id, status, "
                "kind, prompt, output, error, started_at, finished_at, "
                "created_at, updated_at FROM agent_tasks"
            )
        )
        connection.execute(text("DROP TABLE agent_tasks"))
        connection.execute(text("ALTER TABLE agent_tasks_new RENAME TO agent_tasks"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_agent_tasks_agent_id ON agent_tasks (agent_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_agent_tasks_pipeline_id ON agent_tasks (pipeline_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_agent_tasks_pipeline_run_id ON agent_tasks (pipeline_run_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_agent_tasks_pipeline_step_id ON agent_tasks (pipeline_step_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_agent_tasks_task_template_id ON agent_tasks (task_template_id)"
            )
        )
    finally:
        connection.execute(
            text(f"PRAGMA foreign_keys={'ON' if foreign_keys_on else 'OFF'}")
        )


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
