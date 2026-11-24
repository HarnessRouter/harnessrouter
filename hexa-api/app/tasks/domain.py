from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Mapping, Sequence
import re


class InvalidTransition(ValueError):
    pass


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    deps: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    final_report: bool = False
    requires_human: bool = False


@dataclass(frozen=True)
class WorkflowSpec:
    nodes: tuple[NodeSpec, ...]


def validate_workflow(workflow: WorkflowSpec, *, max_nodes: int = 50, max_edges: int = 200) -> None:
    if len(workflow.nodes) > max_nodes:
        raise ValueError(f"workflow exceeds {max_nodes} nodes")

    node_ids = [node.node_id for node in workflow.nodes]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("workflow contains duplicate node id")
    known = set(node_ids)
    edge_count = 0
    graph: dict[str, tuple[str, ...]] = {}
    for node in workflow.nodes:
        if not node.node_id.strip() or len(node.node_id) > 255:
            raise ValueError("invalid node id")
        if len(set(node.deps)) != len(node.deps) or len(set(node.input_refs)) != len(node.input_refs):
            raise ValueError("duplicate dependency or input ref")
        unknown = set(node.deps) - known
        if unknown:
            raise ValueError(f"unknown dependency: {sorted(unknown)[0]}")
        unknown_inputs = set(node.input_refs) - set(node.deps)
        if unknown_inputs:
            raise ValueError(f"input ref is not a dependency: {sorted(unknown_inputs)[0]}")
        edge_count += len(node.deps)
        graph[node.node_id] = node.deps
    if edge_count > max_edges:
        raise ValueError(f"workflow exceeds {max_edges} edges")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("workflow contains cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in graph[node_id]:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in node_ids:
        visit(node_id)


def validate_input_refs(
    workflow: WorkflowSpec,
    node_id: str,
    input_refs: Sequence[str],
    *,
    succeeded_nodes: Iterable[str],
) -> None:
    node = next((item for item in workflow.nodes if item.node_id == node_id), None)
    if node is None:
        raise ValueError(f"unknown node: {node_id}")
    requested = tuple(dict.fromkeys(input_refs))
    if not requested:
        raise ValueError("at least one input ref is required")
    if set(requested) - set(node.deps):
        raise ValueError("input ref is not a dependency")
    missing = set(requested) - set(succeeded_nodes)
    if missing:
        raise ValueError(f"input ref is not succeeded: {sorted(missing)[0]}")


def transition_run(status: RunStatus, action: str) -> RunStatus:
    transitions = {
        (RunStatus.PENDING, "start"): RunStatus.RUNNING,
        (RunStatus.RUNNING, "wait_human"): RunStatus.WAITING_HUMAN,
        (RunStatus.RUNNING, "wait_approval"): RunStatus.WAITING_APPROVAL,
        (RunStatus.WAITING_HUMAN, "continue"): RunStatus.RUNNING,
        (RunStatus.WAITING_APPROVAL, "continue_approval"): RunStatus.RUNNING,
        (RunStatus.RUNNING, "complete"): RunStatus.COMPLETED,
        (RunStatus.RUNNING, "fail"): RunStatus.FAILED,
        (RunStatus.PENDING, "cancel"): RunStatus.CANCELED,
        (RunStatus.RUNNING, "cancel"): RunStatus.CANCELED,
        (RunStatus.WAITING_HUMAN, "cancel"): RunStatus.CANCELED,
    }
    try:
        return transitions[(status, action)]
    except KeyError as exc:
        raise InvalidTransition(f"cannot {action} run in {status} state") from exc


def derive_task_status(run_statuses: Sequence[RunStatus], *, final_report_succeeded: bool) -> TaskStatus:
    if any(status is RunStatus.RUNNING or status is RunStatus.PENDING for status in run_statuses):
        return TaskStatus.RUNNING
    if any(status in {RunStatus.WAITING_HUMAN, RunStatus.WAITING_APPROVAL} for status in run_statuses):
        return TaskStatus.WAITING
    if final_report_succeeded:
        return TaskStatus.COMPLETED
    if run_statuses and run_statuses[-1] is RunStatus.FAILED:
        return TaskStatus.FAILED
    if run_statuses and run_statuses[-1] in {RunStatus.COMPLETED, RunStatus.CANCELED}:
        return TaskStatus.WAITING
    return TaskStatus.DRAFT


def derive_stale_nodes(
    current_results: Mapping[str, str],
    node_inputs: Mapping[str, Sequence[str]],
    consumed_versions: Mapping[str, Sequence[str]],
) -> set[str]:
    stale: set[str] = set()
    for node_id, inputs in node_inputs.items():
        consumed = consumed_versions.get(node_id, ())
        if len(inputs) != len(consumed):
            stale.add(node_id)
            continue
        if any(current_results.get(source) != version for source, version in zip(inputs, consumed)):
            stale.add(node_id)
    changed = True
    while changed:
        changed = False
        for node_id, inputs in node_inputs.items():
            if node_id in stale:
                continue
            if any(source in stale for source in inputs):
                stale.add(node_id)
                changed = True
    return stale


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {key: '[REDACTED]' if re.search(r'(?i)(password|secret|api[_-]?key|authorization|access[_-]?token)', key) else redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if isinstance(secret, str) and len(secret) >= 8:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)Bearer\s+[^\s"\',;]+', 'Bearer [REDACTED]', value)
        return re.sub(r'(?i)((?:api[_ -]?key|password|secret|token)\s*[:=]\s*)[^\s"\',;]+', r'\1[REDACTED]', value)
    return value
