from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, create_engine
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


class WorkflowRevision(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (UniqueConstraint("task_id", "revision", name="uq_workflow_revision_task_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    definition_json: Mapped[str] = mapped_column(Text)


class Run(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "idempotency_key", name="uq_task_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    workflow_revision: Mapped[int] = mapped_column(Integer)
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
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    node_id: Mapped[str] = mapped_column(String(255), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunDecision(Base):
    __tablename__ = "run_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    node_id: Mapped[str] = mapped_column(String(255))
    input_refs_json: Mapped[str] = mapped_column(Text)


class TaskCommand(Base):
    __tablename__ = "task_commands"
    __table_args__ = (UniqueConstraint("task_id", "key", name="uq_task_command_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)


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
    template_id: Mapped[int] = mapped_column(Integer, index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition_json: Mapped[str] = mapped_column(Text)


def create_session_factory(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith('sqlite'):
        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
