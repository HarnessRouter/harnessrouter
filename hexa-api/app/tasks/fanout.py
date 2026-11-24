"""Persisted fanout control shared by collections and restricted plan items.

Each item is an immutable execution record. Aggregate records never replace
an item's business output, even when that output has a field named `items`.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.db.models import NodeRun, Run
from app.tasks.dynamic_graph import graph_valid, graph_ready
from app.tasks.execution_binding import execution_binding


def _run_binding(run, item):
    """Freeze the parent node's execution identity in every derived item."""
    return execution_binding(json.loads(run.snapshot_json), item.get('agent_id'), item.get('model'))


def node_record_usage(db, run_id):
    """Include the aggregate slot reserved by every running fanout control."""
    db.flush()
    run = db.get(Run, run_id)
    fanouts = [item['id'] for item in json.loads(run.snapshot_json).get('workflow', {}).get('nodes', [])
               if item.get('foreach') or item.get('dynamic_plan')]
    count = db.scalar(select(func.count()).select_from(NodeRun).where(NodeRun.run_id == run_id))
    controls = db.scalars(select(NodeRun).where(
        NodeRun.run_id == run_id, NodeRun.node_id.in_(fanouts),
        NodeRun.execution_kind == 'node', NodeRun.status.in_(('idle', 'running')),
    )).all() if fanouts else []
    reserved = sum(row.status == 'running' or 'item_node_run_ids' in json.loads(row.input_json) for row in controls)
    outer_controls = db.scalars(select(NodeRun).where(
        NodeRun.run_id == run_id, NodeRun.execution_kind == 'foreach_item',
        NodeRun.status.in_(('idle', 'running')),
    )).all()
    reserved += sum('nested_item_node_run_ids' in json.loads(row.input_json)
                    and 'nested_aggregate_node_run_id' not in json.loads(row.input_json)
                    for row in outer_controls)
    return count + reserved


def dynamic_items_valid(values):
    if not isinstance(values, list):
        return False
    identities = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {'id', 'prompt'}:
            return False
        identity, prompt = value['id'], value['prompt']
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 255 or identity in identities:
            return False
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            return False
        identities.add(identity)
    return True


def fanout_items(db, control, prefix):
    state = json.loads(control.input_json)
    if 'item_node_run_ids' in state:
        children = [db.get(NodeRun, identity) for identity in state['item_node_run_ids']]
        if any(child is None or child.run_id != control.run_id or child.node_id != control.node_id
               or child.iteration != control.iteration or child.execution_kind != f'{prefix}_item'
               for child in children):
            raise ValueError('invalid persisted fanout manifest')
        return children
    # Compatibility with runs expanded before explicit manifests were stored.
    return db.scalars(select(NodeRun).where(
        NodeRun.run_id == control.run_id, NodeRun.node_id == control.node_id,
        NodeRun.execution_kind == f'{prefix}_item', NodeRun.iteration == control.iteration,
    ).order_by(NodeRun.foreach_index, NodeRun.id)).all()


def nested_fanout_items(db, outer):
    state = json.loads(outer.input_json)
    identities = state.get('nested_item_node_run_ids')
    if identities is None:
        return []
    rows = [db.get(NodeRun, identity) for identity in identities]
    if any(row is None or row.run_id != outer.run_id or row.node_id != outer.node_id
           or row.iteration != outer.iteration or row.execution_kind != 'foreach_nested_item'
           for row in rows):
        raise ValueError('invalid persisted nested fanout manifest')
    return rows


def manifest_records(db, anchor):
    """Select a fixed two-level manifest before applying presentation paging.

    Validate the complete manifest first: a broken later page must not allow
    disclosure of a partial or foreign execution on an earlier page.
    """
    selected = {}

    def members(identities, kinds):
        if not isinstance(identities, list) or len(identities) > 500:
            raise ValueError('invalid manifest')
        result = []
        for identity in identities:
            if type(identity) is not int or identity in selected:
                raise ValueError('invalid manifest identity')
            row = db.get(NodeRun, identity)
            if (row is None or row.run_id != anchor.run_id or row.node_id != anchor.node_id
                    or row.iteration != anchor.iteration or row.execution_kind not in kinds):
                raise ValueError('manifest ownership mismatch')
            selected[identity] = row
            result.append(row)
        return result

    state = json.loads(anchor.input_json)
    if not isinstance(state, dict):
        raise ValueError('invalid anchor input')
    if 'subgraph_node_run_ids' in state:
        outer_rows = members(state.get('subgraph_node_run_ids', []), {'subgraph_node'})
        # A static nested subgraph is represented by the outer child NodeRun
        # plus its own explicit child manifest.  Keep both levels in one
        # paged result, while validating the complete tree before returning
        # any page so a malformed later entry cannot leak an earlier one.
        for outer in outer_rows:
            outer_state = json.loads(outer.input_json)
            if not isinstance(outer_state, dict):
                raise ValueError('invalid subgraph child input')
            nested_ids = outer_state.get('nested_subgraph_node_run_ids', [])
            nested_rows = members(nested_ids, {'subgraph_node'})
            for nested in nested_rows:
                nested_state = json.loads(nested.input_json)
                if not isinstance(nested_state, dict) or nested_state.get('subgraph_parent_node_run_id') != outer.id:
                    raise ValueError('nested subgraph ownership mismatch')
        if state.get('subgraph_aggregate_node_run_id') is not None:
            members([state['subgraph_aggregate_node_run_id']], {'subgraph_aggregate'})
        if len(selected) > 500:
            raise ValueError('manifest exceeds run limit')
        return sorted(selected.values(), key=lambda row: row.id)
    outers = members(state.get('item_node_run_ids', []), {'foreach_item', 'dynamic_item'})
    for outer in outers:
        outer_state = json.loads(outer.input_json)
        if not isinstance(outer_state, dict):
            raise ValueError('invalid outer input')
        members(outer_state.get('nested_item_node_run_ids', []), {'foreach_nested_item'})
        if 'nested_aggregate_node_run_id' in outer_state:
            members([outer_state['nested_aggregate_node_run_id']], {'foreach_nested_aggregate'})
    if len(selected) > 500:
        raise ValueError('manifest exceeds run limit')
    return sorted(selected.values(), key=lambda row: row.id)


def advance_nested_foreach(db, run, item, control, outer, *, nested, encoded, value_at_path, now):
    """Advance one outer item in the bounded two-level foreach contract."""
    if outer.status not in ('idle', 'running'):
        return [], False
    state = json.loads(outer.input_json)
    children = nested_fanout_items(db, outer)
    changed = False
    if 'nested_item_node_run_ids' not in state:
        values = value_at_path(state.get('foreach_item'), nested['path'])
        if not isinstance(values, list):
            outer.status, outer.error_code, outer.finished_at = 'failed', 'nested_foreach_input_invalid', now
            return [], True
        if len(values) > nested['max_items']:
            outer.status, outer.error_code, outer.finished_at = 'failed', 'nested_foreach_limit_exceeded', now
            return [], True
        if node_record_usage(db, run.id) + len(values) + 1 > 500:
            outer.status, outer.error_code, outer.finished_at = 'failed', 'storage_limit_exceeded', now
            return [], True
        for index, value in enumerate(values):
            child = NodeRun(
                run_id=run.id, node_id=item['id'], iteration=outer.iteration,
                attempt=1, execution_kind='foreach_nested_item', foreach_index=index,
                input_json=encoded({
                    '_orchestration_role': 'foreach_nested_item',
                    'foreach_nested_item': value,
                    'outer_item_node_run_id': outer.id,
                    'outer_foreach_index': outer.foreach_index,
                    'foreach_index': index,
                    'refs': state.get('refs', []),
                    'execution_binding': _run_binding(run, item),
                    **({'loop_previous': state['loop_previous']} if state.get('loop_previous') else {}),
                }),
            )
            db.add(child)
            children.append(child)
        db.flush()
        state['nested_item_node_run_ids'] = [child.id for child in children]
        outer.input_json = encoded(state)
        outer.status, outer.started_at = 'running', outer.started_at or now
        changed = True
    if outer.status not in ('idle', 'running'):
        return [], changed
    failed = next((child for child in children if child.status in ('failed', 'canceled')), None)
    if failed:
        for child in children:
            if child.status == 'idle':
                child.status, child.error_code, child.finished_at = 'canceled', 'nested_foreach_sibling_failed', now
        outer.status, outer.error_code, outer.finished_at = 'failed', failed.error_code or 'nested_foreach_item_failed', now
        return [], True
    if all(child.status == 'succeeded' for child in children):
        aggregate_id = state.get('nested_aggregate_node_run_id')
        aggregate = db.get(NodeRun, aggregate_id) if aggregate_id else None
        if aggregate is None:
            nested_output = encoded({'items': [json.loads(child.output_json) for child in children]})
            if len(nested_output.encode()) > 1024 * 1024:
                outer.status, outer.error_code, outer.finished_at = 'failed', 'storage_limit_exceeded', now
                return [], True
            aggregate = NodeRun(
                run_id=run.id, node_id=item['id'], iteration=outer.iteration,
                attempt=outer.attempt, execution_kind='foreach_nested_aggregate',
                foreach_index=outer.foreach_index,
                input_json=encoded({
                    '_orchestration_role': 'foreach_nested_aggregate',
                    'outer_item_node_run_id': outer.id,
                    'item_node_run_ids': [child.id for child in children],
                    'item_count': len(children),
                }),
                output_json=nested_output,
                status='succeeded', started_at=outer.started_at or now, finished_at=now,
            )
            db.add(aggregate)
            db.flush()
            state['nested_aggregate_node_run_id'] = aggregate.id
            outer.input_json = encoded(state)
        outer.output_json = aggregate.output_json
        outer.status, outer.finished_at = 'succeeded', now
        return [], True
    idle = [child for child in children if child.status == 'idle']
    units = idle if nested.get('mode', 'serial') == 'parallel' else idle[:1]
    return [('foreach_nested_item', item, child) for child in units], changed


def retry_fanout(db, run, item, control, selected_id, *, encoded, error):
    prefix = 'dynamic' if item.get('dynamic_plan') else 'foreach'
    children = fanout_items(db, control, prefix)
    state = json.loads(control.input_json)
    selected = next((child for child in children if child.id == selected_id), None)
    if selected_id is not None and (selected is None or selected.status not in ('failed', 'canceled')):
        raise error('invalid_retry_item', '只能重试当前清单中失败或取消的集合项。', 422)
    replacing = [child for child in children if child.status in ('failed', 'canceled') and (
        selected_id is None or child.id == selected_id or child.error_code == f'{prefix}_sibling_failed'
    )]
    nested_replacements = {child.id: nested_fanout_items(db, child) for child in replacing
                           if 'nested_item_node_run_ids' in json.loads(child.input_json)}
    extra = sum(sum(leaf.status in ('failed', 'canceled') for leaf in leaves) + 1
                for leaves in nested_replacements.values())
    if node_record_usage(db, run.id) + len(replacing) + extra + 2 > 500:
        raise error('storage_limit_exceeded', '运行超过 500 次尝试限制。', 422)
    manifest = []
    retried = []
    for child in children:
        if child in replacing:
            child_state = json.loads(child.input_json)
            replacement = NodeRun(
                run_id=run.id, node_id=control.node_id, iteration=control.iteration,
                attempt=child.attempt + 1, execution_kind=f'{prefix}_item',
                foreach_index=child.foreach_index,
                input_json=encoded({'_orchestration_role': f'{prefix}_item',
                                    f'{prefix}_item': child_state[f'{prefix}_item'],
                                    'foreach_index': child.foreach_index,
                                    'execution_binding': child_state.get('execution_binding') or _run_binding(run, item),
                                    'retry_of': child.id,
                                    **({'loop_previous': state['loop_previous']} if state.get('loop_previous') else {})}),
            )
            db.add(replacement)
            db.flush()
            if child.id in nested_replacements:
                leaf_ids = []
                for leaf in nested_replacements[child.id]:
                    if leaf.status in ('failed', 'canceled'):
                        leaf_state = json.loads(leaf.input_json)
                        new_leaf = NodeRun(
                            run_id=run.id, node_id=control.node_id, iteration=control.iteration,
                            attempt=leaf.attempt + 1, execution_kind='foreach_nested_item',
                            foreach_index=leaf.foreach_index,
                            input_json=encoded({**leaf_state, 'retry_of': leaf.id,
                                                'outer_item_node_run_id': replacement.id,
                                                'execution_binding': leaf_state.get('execution_binding') or _run_binding(run, item),
                                                **({'loop_previous': state['loop_previous']} if state.get('loop_previous') else {})}),
                        )
                        db.add(new_leaf)
                        db.flush()
                        leaf_ids.append(new_leaf.id)
                    else:
                        leaf_ids.append(leaf.id)
                replacement.input_json = encoded({**json.loads(replacement.input_json),
                                                   'nested_item_node_run_ids': leaf_ids})
            manifest.append(replacement.id)
            retried.append(replacement.id)
        else:
            manifest.append(child.id)
    retry_state = {**state, 'retry_of': control.id, 'retry_item_node_run_ids': retried}
    if children or 'item_node_run_ids' in state:
        retry_state['item_node_run_ids'] = manifest
    retry = NodeRun(run_id=run.id, node_id=control.node_id, iteration=control.iteration,
                    attempt=control.attempt + 1, input_json=encoded(retry_state),
                    status='running' if 'item_node_run_ids' in retry_state else 'idle')
    db.add(retry)
    return retry


def advance_fanouts(db, run, definition, rows, *, encoded, value_at_path, condition_matches, decisions):
    """Return dispatch candidates and whether a durable transition was made."""
    candidates, changed = [], False
    for item in definition['nodes']:
        config = item.get('foreach') or item.get('dynamic_plan')
        if not config:
            continue
        dynamic = bool(item.get('dynamic_plan'))
        dag = dynamic and config.get('topology') == 'dag'
        prefix = 'dynamic' if dynamic else 'foreach'
        invalid = 'dynamic_plan_invalid' if dynamic else 'foreach_input_invalid'
        limit = 'dynamic_plan_limit_exceeded' if dynamic else 'foreach_limit_exceeded'
        control = rows[item['id']]
        if control.status not in ('idle', 'running'):
            continue
        children = fanout_items(db, control, prefix)
        now = datetime.now(timezone.utc)
        if control.status == 'idle' and children:
            if any(rows[dep].status != 'succeeded' for dep in item.get('deps', [])):
                continue
            if item.get('requires_human') and item['id'] not in decisions:
                continue
            control.status = 'running'
            changed = True
        if control.status == 'idle' and not children:
            if any(rows[dep].status != 'succeeded' and not (
                rows[dep].status == 'skipped' and item.get('allow_missing_inputs')
            ) for dep in item.get('deps', [])):
                continue
            condition = item.get('condition')
            if condition and not condition_matches(condition, json.loads(rows[condition['source']].output_json or 'null')):
                control.status, control.error_code = 'skipped', 'condition_not_matched'
                control.finished_at = now
                changed = True
                continue
            if item.get('requires_human') and item['id'] not in decisions:
                continue
            values = value_at_path(json.loads(rows[config['source']].output_json or 'null'), config['path'])
            if dynamic and isinstance(values, str):
                try:
                    values = json.loads(values)
                except ValueError:
                    values = None
            if not isinstance(values, list) or (dynamic and not (graph_valid(values) if dag else dynamic_items_valid(values))):
                control.status, control.error_code = 'failed', invalid
            elif len(values) > config['max_items']:
                control.status, control.error_code = 'failed', limit
            else:
                # Reserve space for every item and the final aggregate, atomically
                # with expansion. No partially persisted plan can be dispatched.
                count = node_record_usage(db, run.id)
                if count + len(values) + 1 > 500:
                    control.status, control.error_code = 'failed', 'storage_limit_exceeded'
                else:
                    control.status = 'running'
                    control.started_at = control.started_at or now
                    previous = json.loads(control.input_json).get('loop_previous')
                    for index, value in enumerate(values):
                        child = NodeRun(
                            run_id=run.id, node_id=item['id'], attempt=1, iteration=control.iteration,
                            execution_kind=f'{prefix}_item', foreach_index=index,
                            input_json=encoded({'_orchestration_role': f'{prefix}_item',
                                                f'{prefix}_item': value, 'foreach_index': index,
                                                'execution_binding': _run_binding(run, item),
                                                **({'loop_previous': previous} if previous else {})}),
                        )
                        db.add(child)
                        children.append(child)
                    # Empty collection takes the same explicit aggregation path.
                    db.flush()
                    refs = [{'node_id': ref, 'node_run_id': rows[ref].id,
                             'output': json.loads(rows[ref].output_json)}
                            for ref in decisions.get(item['id'], item.get('inputRefs', [])) if rows[ref].status == 'succeeded']
                    control.input_json = encoded({**json.loads(control.input_json),
                                                  'item_node_run_ids': [child.id for child in children],
                                                  'refs': refs})
            changed = True
            if control.status == 'failed':
                control.finished_at = now
                continue
        if control.status != 'running':
            continue
        nested = config.get('nested') if not dynamic else None
        if nested:
            nested_calls = []
            nested_changed = False
            retry_ids = set(json.loads(control.input_json).get('retry_item_node_run_ids', []))
            retry_pending = any(outer.id in retry_ids and outer.status in ('idle', 'running') for outer in children)
            failed_outer = next((outer for outer in children if outer.status in ('failed', 'canceled')
                                 and (not retry_pending or outer.id in retry_ids)), None)
            if failed_outer:
                for outer in children:
                    if outer.status in ('idle', 'running'):
                        for leaf in nested_fanout_items(db, outer):
                            if leaf.status == 'idle':
                                leaf.status, leaf.error_code, leaf.finished_at = 'canceled', 'nested_foreach_sibling_failed', now
                        outer.status, outer.error_code, outer.finished_at = 'canceled', 'foreach_sibling_failed', now
                control.status, control.error_code, control.finished_at = 'failed', failed_outer.error_code or 'nested_foreach_item_failed', now
                return candidates, True
            pending = [outer for outer in children if outer.status in ('idle', 'running')]
            for outer in (pending if config.get('mode', 'serial') == 'parallel' else pending[:1]):
                calls, item_changed = advance_nested_foreach(
                    db, run, item, control, outer, nested=nested, encoded=encoded,
                    value_at_path=value_at_path, now=now,
                )
                nested_calls.extend(calls)
                nested_changed = nested_changed or item_changed
            if nested_changed:
                return candidates, True
            if all(outer.status == 'succeeded' for outer in children):
                aggregate_input = {'_orchestration_role': 'foreach_aggregate',
                                   'control_node_run_id': control.id,
                                   'refs': json.loads(control.input_json).get('refs', []),
                                   'item_node_run_ids': [outer.id for outer in children],
                                   'item_count': len(children)}
                output = encoded({'items': [json.loads(outer.output_json) for outer in children]})
                aggregate = NodeRun(
                    run_id=run.id, node_id=item['id'], attempt=control.attempt, iteration=control.iteration,
                    execution_kind='foreach_aggregate', input_json=encoded(aggregate_input),
                    output_json=output if len(output.encode()) <= 1024 * 1024 else None,
                    status='succeeded' if len(output.encode()) <= 1024 * 1024 else 'failed',
                    error_code=None if len(output.encode()) <= 1024 * 1024 else 'storage_limit_exceeded',
                    started_at=control.started_at or now, finished_at=now,
                )
                db.add(aggregate)
                control.status, control.finished_at = aggregate.status, now
                return candidates, True
            candidates.extend(nested_calls)
            continue
        retry_ids = set(json.loads(control.input_json).get('retry_item_node_run_ids', []))
        retry_pending = any(child.id in retry_ids and child.status in ('idle', 'running') for child in children)
        failed = next((child for child in children if child.status in ('failed', 'canceled')
                       and (not retry_pending or child.id in retry_ids)), None)
        if failed:
            for child in children:
                if child.status == 'idle':
                    child.status, child.error_code, child.finished_at = 'canceled', f'{prefix}_sibling_failed', now
            control.status = 'failed'
            control.error_code = failed.error_code or f'{prefix}_item_failed'
            control.finished_at = now
            changed = True
        elif all(child.status in (('succeeded', 'skipped') if dag else ('succeeded',)) for child in children):
            aggregate_input = {'_orchestration_role': f'{prefix}_aggregate',
                               'control_node_run_id': control.id,
                               'refs': json.loads(control.input_json).get('refs', []),
                               'item_node_run_ids': [child.id for child in children],
                               'item_count': len(children)}
            output = encoded({'items': [
                {'id': json.loads(child.input_json)['dynamic_item']['id'], 'status': child.status,
                 'output': json.loads(child.output_json) if child.output_json else None}
                if dag else json.loads(child.output_json) for child in children
            ]})
            aggregate = NodeRun(
                run_id=run.id, node_id=item['id'], attempt=control.attempt, iteration=control.iteration,
                execution_kind=f'{prefix}_aggregate', input_json=encoded(aggregate_input),
                output_json=output if len(output.encode()) <= 1024 * 1024 else None,
                status='succeeded' if len(output.encode()) <= 1024 * 1024 else 'failed',
                error_code=None if len(output.encode()) <= 1024 * 1024 else 'storage_limit_exceeded',
                started_at=control.started_at or now, finished_at=now,
            )
            db.add(aggregate)
            control.status, control.finished_at = aggregate.status, now
            # Dependencies must observe the persisted aggregate, never the
            # now-succeeded control record whose output is intentionally empty.
            return candidates, True
        else:
            idle = [child for child in children if child.status == 'idle']
            if dag:
                idle, graph_changed = graph_ready(children, condition_matches, now)
                if graph_changed:
                    return candidates, True
                if not idle and not any(child.status == 'running' for child in children):
                    control.status, control.error_code, control.finished_at = 'failed', 'dynamic_dependency_unavailable', now
                    return candidates, True
            candidates.extend((f'{prefix}_item', item, child) for child in (
                idle if config.get('mode', 'serial') == 'parallel' else idle[:1]
            ))
    return candidates, changed
