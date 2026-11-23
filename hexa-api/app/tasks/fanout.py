"""Persisted fanout control shared by collections and restricted plan items.

Each item is an immutable execution record. Aggregate records never replace
an item's business output, even when that output has a field named `items`.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.db.models import NodeRun, Run


def node_record_usage(db, run_id):
    """Include the aggregate slot reserved by every running fanout control."""
    db.flush()
    run = db.get(Run, run_id)
    fanouts = [item['id'] for item in json.loads(run.snapshot_json).get('workflow', {}).get('nodes', [])
               if item.get('foreach') or item.get('dynamic_plan')]
    count = db.scalar(select(func.count()).select_from(NodeRun).where(NodeRun.run_id == run_id))
    reserved = db.scalar(select(func.count()).select_from(NodeRun).where(
        NodeRun.run_id == run_id, NodeRun.node_id.in_(fanouts),
        NodeRun.execution_kind == 'node', NodeRun.status == 'running',
    )) if fanouts else 0
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


def retry_fanout(db, run, item, control, selected_id, *, encoded, error):
    prefix = 'dynamic' if item.get('dynamic_plan') else 'foreach'
    children = fanout_items(db, control, prefix)
    selected = next((child for child in children if child.id == selected_id), None)
    if selected_id is not None and (selected is None or selected.status not in ('failed', 'canceled')):
        raise error('invalid_retry_item', '只能重试当前清单中失败或取消的集合项。', 422)
    replacing = [child for child in children if child.status in ('failed', 'canceled') and (
        selected_id is None or child.id == selected_id or child.error_code == f'{prefix}_sibling_failed'
    )]
    if node_record_usage(db, run.id) + len(replacing) + 2 > 500:
        raise error('storage_limit_exceeded', '运行超过 500 次尝试限制。', 422)
    state = json.loads(control.input_json)
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
                                    'retry_of': child.id,
                                    **({'loop_previous': state['loop_previous']} if state.get('loop_previous') else {})}),
            )
            db.add(replacement)
            db.flush()
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
        prefix = 'dynamic' if dynamic else 'foreach'
        invalid = 'dynamic_plan_invalid' if dynamic else 'foreach_input_invalid'
        limit = 'dynamic_plan_limit_exceeded' if dynamic else 'foreach_limit_exceeded'
        control = rows[item['id']]
        if control.status not in ('idle', 'running'):
            continue
        children = fanout_items(db, control, prefix)
        now = datetime.now(timezone.utc)
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
            if not isinstance(values, list) or (dynamic and not dynamic_items_valid(values)):
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
        elif all(child.status == 'succeeded' for child in children):
            aggregate_input = {'_orchestration_role': f'{prefix}_aggregate',
                               'control_node_run_id': control.id,
                               'refs': json.loads(control.input_json).get('refs', []),
                               'item_node_run_ids': [child.id for child in children],
                               'item_count': len(children)}
            output = encoded({'items': [json.loads(child.output_json) for child in children]})
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
            candidates.extend((f'{prefix}_item', item, child) for child in (
                idle if config.get('mode', 'serial') == 'parallel' else idle[:1]
            ))
    return candidates, changed
