from __future__ import annotations

import pytest

from app.tasks.domain import (
    InvalidTransition,
    NodeSpec,
    RunStatus,
    TaskStatus,
    WorkflowSpec,
    derive_stale_nodes,
    derive_task_status,
    redact,
    transition_run,
    validate_input_refs,
    validate_workflow,
)


def test_workflow_accepts_parallel_fan_in_and_limits_input_refs():
    workflow = WorkflowSpec(
        nodes=(
            NodeSpec("a"),
            NodeSpec("b"),
            NodeSpec("summary", deps=("a", "b"), input_refs=("a",)),
        )
    )

    validate_workflow(workflow)
    validate_input_refs(workflow, "summary", ("a",), succeeded_nodes={"a", "b"})


def test_workflow_rejects_cycles_and_unknown_dependencies():
    with pytest.raises(ValueError, match="cycle"):
        validate_workflow(WorkflowSpec(nodes=(NodeSpec("a", deps=("b",)), NodeSpec("b", deps=("a",)))))

    with pytest.raises(ValueError, match="unknown dependency"):
        validate_workflow(WorkflowSpec(nodes=(NodeSpec("a", deps=("missing",)),)))


def test_run_transition_requires_waiting_human_decision():
    assert transition_run(RunStatus.PENDING, "start") is RunStatus.RUNNING
    assert transition_run(RunStatus.RUNNING, "wait_human") is RunStatus.WAITING_HUMAN
    assert transition_run(RunStatus.WAITING_HUMAN, "continue") is RunStatus.RUNNING

    with pytest.raises(InvalidTransition):
        transition_run(RunStatus.COMPLETED, "continue")


def test_task_status_is_derived_from_active_run_and_final_report():
    assert derive_task_status([], final_report_succeeded=False) is TaskStatus.DRAFT
    assert derive_task_status([RunStatus.RUNNING], final_report_succeeded=False) is TaskStatus.RUNNING
    assert derive_task_status([RunStatus.WAITING_HUMAN], final_report_succeeded=False) is TaskStatus.WAITING
    assert derive_task_status([RunStatus.COMPLETED], final_report_succeeded=True) is TaskStatus.COMPLETED
    assert derive_task_status([RunStatus.FAILED], final_report_succeeded=False) is TaskStatus.FAILED


def test_stale_only_propagates_to_consumers_of_replaced_results():
    current_results = {"a": "run-2-output", "b": "run-1-output"}
    node_inputs = {
        "summary": ("a", "b"),
        "report": ("summary",),
        "unrelated": ("b",),
    }
    consumed_versions = {
        "summary": ("run-1-output", "run-1-output"),
        "report": ("summary-output",),
        "unrelated": ("run-1-output",),
    }

    assert derive_stale_nodes(current_results, node_inputs, consumed_versions) == {"summary", "report"}


def test_redaction_masks_secrets_without_corrupting_short_identifiers():
    value = {"node_id": "summary", "authorization": "Bearer long-secret-value"}
    assert redact(value, ("long-secret-value", "short")) == {"node_id": "summary", "authorization": "[REDACTED]"}
