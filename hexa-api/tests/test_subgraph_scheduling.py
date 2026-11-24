"""Nested scopes respect local readiness, capacity, and shared storage limits."""
import json
from types import SimpleNamespace

import pytest

from app.db.models import NodeRun, Run
from app.tasks.fanout import node_record_usage
from app.tasks.service import TaskError, condition_matches, encoded, latest_nodes, value_at_path
from app.tasks.subgraph import _static_ready, advance_subgraphs, retry_subgraph
from tests.test_task_concurrency import seed_run
from tests.test_task_workflows import node


def nested(identity, **kwargs):
    return node(identity, subgraph={'max_concurrency': 2, 'nodes': [node('a'), node('b')]}, **kwargs)


def test_static_readiness_counts_running_scopes_and_waits_for_dependencies():
    def row(identity, status='idle', deps=()):
        return SimpleNamespace(status=status, input_json=encoded({
            'subgraph_node_id': identity, 'deps': list(deps),
        }))

    active, blocked, ready = row('active', 'running'), row('blocked', deps=['active']), row('ready')
    assert _static_ready([active, blocked, ready], 1) == []
    assert _static_ready([active, blocked, ready], 2) == [ready]
    active.status = 'succeeded'
    assert _static_ready([active, blocked, ready], 2) == [blocked, ready]
    active.status = 'skipped'
    assert _static_ready([active, blocked, ready], 2) == [ready]


def materialize(app, children, *, limit=1):
    definition = {'nodes': [node('source'), node('group', deps=['source'], subgraph={
        'max_concurrency': limit, 'nodes': children,
    })]}
    identity = seed_run(app, definition)
    with app.state.session_factory() as db:
        source = latest_nodes(db, identity)['source']
        source.status, source.output_json = 'succeeded', '{}'
        advance(db, identity, definition)
        db.commit()
    return identity, definition


def advance(db, identity, definition):
    return advance_subgraphs(db, db.get(Run, identity), definition, latest_nodes(db, identity),
                             encoded=encoded, value_at_path=value_at_path, condition_matches=condition_matches)


def children_of(db, control):
    state = json.loads(control.input_json)
    identities = state.get('subgraph_node_run_ids', state.get('nested_subgraph_node_run_ids', []))
    return [db.get(NodeRun, identity) for identity in identities]


def test_nested_scope_waits_for_local_dependency_and_free_parent_slot(client, app):
    identity, definition = materialize(app, [node('before'), nested('inner', deps=['before'], inputRefs=['before'])])
    with app.state.session_factory() as db:
        control = latest_nodes(db, identity)['group']
        before, inner = children_of(db, control)
        assert inner.status == 'idle'
        assert 'nested_subgraph_node_run_ids' not in json.loads(inner.input_json)
        calls, _ = advance(db, identity, definition)
        assert [row.id for _, _, row in calls] == [before.id]
        before.status, before.output_json = 'succeeded', '{}'
        advance(db, identity, definition)
        assert inner.status == 'running'
        assert all(json.loads(leaf.input_json)['parent_refs'] == [
            {'id': 'before', 'node_run_id': before.id, 'output': {}}
        ] for leaf in children_of(db, inner))
        calls, _ = advance(db, identity, definition)
        assert {row.id for _, _, row in calls} == {row.id for row in children_of(db, inner)}


def test_nested_sibling_scopes_consume_parent_slots(client, app):
    identity, definition = materialize(app, [nested('first'), nested('second')])
    with app.state.session_factory() as db:
        control = latest_nodes(db, identity)['group']
        first, second = children_of(db, control)
        assert first.status == 'running'
        assert second.status == 'idle'
        assert children_of(db, second) == []
        calls, _ = advance(db, identity, definition)
        assert {row.id for _, _, row in calls} == {row.id for row in children_of(db, first)}
        for leaf in children_of(db, first):
            leaf.status, leaf.output_json = 'succeeded', '{}'
        advance(db, identity, definition)
        advance(db, identity, definition)
        assert first.status == 'succeeded'
        assert second.status == 'running'


@pytest.mark.parametrize('record_count', [497, 498])
def test_nested_expansion_reserves_complete_manifest_and_parent_aggregate(client, app, record_count):
    identity, definition = materialize(app, [node('before'), nested('inner', deps=['before'])])
    with app.state.session_factory() as db:
        control = latest_nodes(db, identity)['group']
        before, inner = children_of(db, control)
        before.status, before.output_json = 'succeeded', '{}'
        count = db.query(NodeRun).filter_by(run_id=identity).count()
        db.add_all(NodeRun(run_id=identity, node_id='source', iteration=0, status='succeeded')
                   for _ in range(record_count - count))
        db.flush()
        assert node_record_usage(db, identity) == record_count + 1
        advance(db, identity, definition)
        if record_count == 498:
            assert inner.status == 'failed'
            assert inner.error_code == 'storage_limit_exceeded'
            assert children_of(db, inner) == []
            assert db.query(NodeRun).filter_by(run_id=identity).count() == record_count
        else:
            assert inner.status == 'running'
            assert len(children_of(db, inner)) == 2
            assert node_record_usage(db, identity) == 500


@pytest.mark.parametrize('nested_scope', [False, True])
def test_subgraph_aggregate_output_is_bounded(client, app, nested_scope):
    identity, definition = materialize(app, [nested('inner')] if nested_scope else [node('a'), node('b')], limit=2)
    with app.state.session_factory() as db:
        control = latest_nodes(db, identity)['group']
        scope = children_of(db, control)[0] if nested_scope else control
        for leaf in children_of(db, scope):
            leaf.status, leaf.output_json = 'succeeded', encoded({'text': 'x' * 600000})
        advance(db, identity, definition)
        assert scope.status == 'failed'
        assert scope.error_code == 'storage_limit_exceeded'
        assert scope.output_json is None
        assert db.query(NodeRun).filter_by(run_id=identity, execution_kind='subgraph_aggregate').count() == 0


@pytest.mark.parametrize('record_count', [496, 497])
def test_subgraph_retry_budget_counts_successful_copies_and_aggregate(client, app, record_count):
    identity, definition = materialize(app, [node('a'), node('b')], limit=2)
    with app.state.session_factory() as db:
        run = db.get(Run, identity)
        control = latest_nodes(db, identity)['group']
        first, second = children_of(db, control)
        first.status, first.output_json = 'succeeded', '{}'
        second.status, second.error_code = 'failed', 'agent_failed'
        control.status = 'failed'
        count = db.query(NodeRun).filter_by(run_id=identity).count()
        db.add_all(NodeRun(run_id=identity, node_id='source', iteration=0, status='succeeded')
                   for _ in range(record_count - count))
        db.flush()
        if record_count == 497:
            with pytest.raises(TaskError) as failure:
                retry_subgraph(db, run, definition['nodes'][1], control, second.id, encoded=encoded, error=TaskError)
            assert failure.value.code == 'storage_limit_exceeded'
            assert db.query(NodeRun).filter_by(run_id=identity).count() == record_count
        else:
            retry = retry_subgraph(db, run, definition['nodes'][1], control, second.id, encoded=encoded, error=TaskError)
            assert [child.status for child in children_of(db, retry)] == ['succeeded', 'idle']
            assert node_record_usage(db, identity) == 500
