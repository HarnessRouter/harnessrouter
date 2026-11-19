from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)


class AppWorkspace(Base):
    __tablename__ = "app_workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    gateway_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    selected: Mapped[bool] = mapped_column(Boolean, default=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    previous_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str] = mapped_column(String(255), default='')
    model: Mapped[str] = mapped_column(String(255), default='')
    response_status: Mapped[str] = mapped_column(String(32), default="idle")
    response_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


class IdempotencyRequest(Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(255), index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_status: Mapped[int] = mapped_column(Integer, default=200)
    response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    partial_text: Mapped[str] = mapped_column(Text, default='')
    execution_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConversationFile(Base):
    __tablename__ = 'conversation_files'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    gateway_id: Mapped[str] = mapped_column(String(255))
    container_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(255), default='application/octet-stream')
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    direction: Mapped[str] = mapped_column(String(16), default='input')


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="未命名任务")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    current_result_json: Mapped[str] = mapped_column(Text, default="{}")
    input_text: Mapped[str] = mapped_column(Text, default="")
    archived_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_template_id: Mapped[int | None] = mapped_column(ForeignKey('task_templates.id'), nullable=True)
    source_template_version_id: Mapped[int | None] = mapped_column(ForeignKey('template_versions.id'), nullable=True)
    source_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_revision_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_revisions.id'), nullable=True, index=True)


class WorkflowRevision(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (UniqueConstraint("task_id", "revision", name="uq_workflow_revision_task_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    definition_json: Mapped[str] = mapped_column(Text)


class Run(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "idempotency_key", name="uq_task_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    workflow_revision: Mapped[int] = mapped_column(Integer)
    workflow_revision_id: Mapped[int | None] = mapped_column(ForeignKey('workflow_revisions.id'), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    kind: Mapped[str] = mapped_column(String(32), default="normal")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    request_hash: Mapped[str] = mapped_column(String(64), default="")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    target_node: Mapped[str | None] = mapped_column(String(255), nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class NodeRun(Base):
    __tablename__ = "node_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('task_runs.id'), index=True)
    node_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = "task_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    node_run_id: Mapped[int] = mapped_column(Integer, index=True)
    gateway_file_id: Mapped[str] = mapped_column(String(255))
    gateway_container_id: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    cleanup_status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RunDecision(Base):
    __tablename__ = "run_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('task_runs.id'), index=True)
    node_id: Mapped[str] = mapped_column(String(255))
    input_refs_json: Mapped[str] = mapped_column(Text)


class TaskCommand(Base):
    __tablename__ = "task_commands"
    __table_args__ = (UniqueConstraint("task_id", "key", name="uq_task_command_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    key: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)


class AgentTemplate(Base):
    __tablename__ = 'agent_templates'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default='')
    base: Mapped[str] = mapped_column(String(255))
    default_model: Mapped[str] = mapped_column(String(255))
    system_prompt: Mapped[str] = mapped_column(Text, default='')


class TaskTemplate(Base):
    __tablename__ = "task_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    workspace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255))


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version", name="uq_template_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey('task_templates.id'), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition_json: Mapped[str] = mapped_column(Text)


def create_session_factory(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    # The application currently uses checked-in SQL migrations for PostgreSQL,
    # while SQLite is the isolated development/test database. Agent templates
    # were added after the initial app release, so create their independent
    # table on startup as well; this makes an existing local database recover
    # after an upgrade without changing any existing records.
    if database_url.startswith('sqlite'):
        Base.metadata.create_all(engine)
        columns = {column['name'] for column in inspect(engine).get_columns('tasks')}
        with engine.begin() as connection:
            for column in ('source_template_id', 'source_template_version_id', 'source_template_version'):
                if column not in columns:
                    connection.execute(text(f'ALTER TABLE tasks ADD COLUMN {column} INTEGER'))
            if 'current_revision_id' not in columns:
                connection.execute(text('ALTER TABLE tasks ADD COLUMN current_revision_id INTEGER'))
            run_columns = {column['name'] for column in inspect(connection).get_columns('task_runs')}
            if 'workflow_revision_id' not in run_columns:
                connection.execute(text('ALTER TABLE task_runs ADD COLUMN workflow_revision_id INTEGER'))
            if 'current_revision' in columns:
                connection.execute(text('''
                    UPDATE tasks
                    SET current_revision_id = (
                        SELECT id FROM workflow_revisions
                        WHERE workflow_revisions.task_id = tasks.id
                          AND workflow_revisions.revision = tasks.current_revision
                    )
                    WHERE current_revision_id IS NULL
                '''))
            if 'workflow_revision' in run_columns:
                connection.execute(text('''
                    UPDATE task_runs
                    SET workflow_revision_id = (
                        SELECT id FROM workflow_revisions
                        WHERE workflow_revisions.task_id = task_runs.task_id
                          AND workflow_revisions.revision = task_runs.workflow_revision
                    )
                    WHERE workflow_revision_id IS NULL
                '''))
            request_columns = {column['name'] for column in inspect(connection).get_columns('idempotency_requests')}
            if 'execution_json' not in request_columns:
                connection.execute(text('ALTER TABLE idempotency_requests ADD COLUMN execution_json TEXT'))
    else:
        # PostgreSQL schema changes are deployment-owned migrations. The API must
        # fail clearly when 005_task_artifacts.sql has not been applied rather
        # than silently creating part of the production schema at startup.
        AgentTemplate.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
