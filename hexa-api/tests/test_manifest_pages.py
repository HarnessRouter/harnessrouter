"""Current-manifest pages are independent of chronological debug pages."""
import json

import pytest

from app.db.models import NodeRun, Run
from app.tasks.service import encoded, latest_nodes
from tests.test_task_concurrency import seed_run
from tests.test_task_workflows import authenticated, node


@pytest.fixture
def manifest(client, app):
    authenticated(client)
    run_id = seed_run(app, {'nodes': [node('worker')]})
    with app.state.session_factory() as db:
        db.get(Run, run_id).status = 'failed'
        control = latest_nodes(db, run_id)['worker']
        control.status = 'failed'
        # Older attempts must not occupy the first current-manifest page.
        db.add_all(NodeRun(run_id=run_id, node_id='worker', iteration=0,
                           execution_kind='foreach_item', status='failed') for _ in range(70))
        outers = [NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_item',
                          foreach_index=index, status='failed') for index in range(10)]
        db.add_all(outers)
        db.flush()
        leaves = []
        for outer in outers:
            group = [NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_nested_item',
                             foreach_index=index, status='succeeded',
                             input_json=encoded({'outer_item_node_run_id': outer.id}), output_json='{"result":"kept"}')
                     for index in range(10)]
            db.add_all(group)
            db.flush()
            outer.input_json = encoded({'nested_item_node_run_ids': [row.id for row in group]})
            leaves.extend(group)
        control.input_json = encoded({'item_node_run_ids': [row.id for row in outers]})
        db.commit()
        return run_id, control.id, sorted(row.id for row in [*outers, *leaves]), outers[0].id, leaves[0].id


def test_items_pages_exclude_old_attempts_and_do_not_execute_or_write(client, app, manifest):
    run_id, anchor, identities, _, _ = manifest
    with app.state.session_factory() as db:
        before = [(row.id, row.input_json, row.status) for row in db.query(NodeRun).filter_by(run_id=run_id)]
    received = []
    for offset in (0, 50, 100):
        response = client.get(f'/api/hexa/node-runs/{anchor}/items?offset={offset}&limit=50')
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body['anchor_node_run_id'] == anchor
        assert body['pagination'] == {'offset': offset, 'limit': 50, 'has_more': offset < 100}
        received.extend(row['id'] for row in body['items'])
    assert received == identities
    with app.state.session_factory() as db:
        assert [(row.id, row.input_json, row.status) for row in db.query(NodeRun).filter_by(run_id=run_id)] == before
    assert app.state.gateway.calls == []


@pytest.mark.parametrize('broken', ['other_run', 'other_node', 'other_iteration', 'wrong_kind', 'duplicate', 'missing', 'wrong_nested_aggregate', 'non_object', 'invalid_json', 'boolean_id'])
def test_broken_manifest_returns_no_partial_data(client, app, manifest, broken):
    run_id, anchor, _, outer_id, leaf_id = manifest
    with app.state.session_factory() as db:
        outer, leaf = db.get(NodeRun, outer_id), db.get(NodeRun, leaf_id)
        if broken == 'other_run':
            other = seed_run(app, {'nodes': [node('worker')]})
            leaf.run_id = other
        elif broken == 'other_node':
            leaf.node_id = 'foreign'
        elif broken == 'other_iteration':
            leaf.iteration = 2
        elif broken == 'wrong_kind':
            leaf.execution_kind = 'node'
        else:
            state = json.loads(outer.input_json)
            if broken == 'duplicate':
                state['nested_item_node_run_ids'].append(leaf_id)
            elif broken == 'missing':
                state['nested_item_node_run_ids'].append(999999)
            elif broken == 'boolean_id':
                state['nested_item_node_run_ids'].append(True)
            elif broken in ('non_object', 'invalid_json'):
                outer.input_json = '[]' if broken == 'non_object' else '{'
            else:
                state['nested_aggregate_node_run_id'] = leaf_id
            if broken not in ('non_object', 'invalid_json'):
                outer.input_json = encoded(state)
        db.commit()
    response = client.get(f'/api/hexa/node-runs/{anchor}/items')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'fanout_manifest_unavailable'
    assert 'items' not in response.json()


def test_old_anchor_is_not_silently_replaced_by_new_control(client, app, manifest):
    run_id, anchor, identities, _, _ = manifest
    with app.state.session_factory() as db:
        db.add(NodeRun(run_id=run_id, node_id='worker', attempt=2, input_json='{"item_node_run_ids":[]}'))
        db.commit()
    response = client.get(f'/api/hexa/node-runs/{anchor}/items?limit=100')
    assert [row['id'] for row in response.json()['items']] == identities[:100]


def test_items_endpoint_checks_task_ownership_and_bounds(client, app, manifest):
    from app.db.models import Task
    run_id, anchor, _, _, _ = manifest
    assert client.get(f'/api/hexa/node-runs/{anchor}/items?offset=-1').status_code == 422
    assert client.get(f'/api/hexa/node-runs/{anchor}/items?limit=101').status_code == 422
    assert client.get('/api/hexa/node-runs/999999/items').status_code == 404
    with app.state.session_factory() as db:
        task = db.get(Task, db.get(Run, run_id).task_id)
        task.user_id = 999
        db.commit()
    assert client.get(f'/api/hexa/node-runs/{anchor}/items').status_code == 404


def test_unexpanded_node_returns_empty_page(client, app):
    authenticated(client)
    run_id = seed_run(app, {'nodes': [node('worker')]})
    with app.state.session_factory() as db:
        anchor = latest_nodes(db, run_id)['worker'].id
    response = client.get(f'/api/hexa/node-runs/{anchor}/items')
    assert response.status_code == 200
    assert response.json()['items'] == []
    assert response.json()['pagination']['has_more'] is False


def test_manifest_selection_includes_nested_aggregate_and_reused_leaf(client, app, manifest):
    from app.tasks.fanout import manifest_records
    run_id, anchor, identities, outer_id, leaf_id = manifest
    with app.state.session_factory() as db:
        outer = db.get(NodeRun, outer_id)
        aggregate = NodeRun(run_id=run_id, node_id='worker', execution_kind='foreach_nested_aggregate',
                            foreach_index=0, status='succeeded', input_json='{}', output_json='{"items":[]}')
        db.add(aggregate)
        db.flush()
        state = json.loads(outer.input_json)
        state['nested_aggregate_node_run_id'] = aggregate.id
        outer.input_json = encoded(state)
        assert [row.id for row in manifest_records(db, db.get(NodeRun, anchor))] == [*identities, aggregate.id]
