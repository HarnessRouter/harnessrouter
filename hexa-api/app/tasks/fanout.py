"""Persisted fanout control shared by collections and restricted plan items.

Each item is an immutable execution record. Aggregate records never replace
an item's business output, even when that output has a field named `items`.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.db.models import NodeRun


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


def advance_fanouts(db, run, definition, rows, *, encoded, value_at_path, condition_matches):
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
        children = db.scalars(select(NodeRun).where(
            NodeRun.run_id == run.id, NodeRun.node_id == item['id'],
            NodeRun.execution_kind == f'{prefix}_item',
        ).order_by(NodeRun.foreach_index, NodeRun.id)).all()
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
            values = value_at_path(json.loads(rows[config['source']].output_json or 'null'), config['path'])
            if not isinstance(values, list) or (dynamic and not dynamic_items_valid(values)):
                control.status, control.error_code = 'failed', invalid
            elif len(values) > config['max_items']:
                control.status, control.error_code = 'failed', limit
            else:
                # Reserve space for every item and the final aggregate, atomically
                # with expansion. No partially persisted plan can be dispatched.
                count = db.scalar(select(func.count()).select_from(NodeRun).where(NodeRun.run_id == run.id))
                if count + len(values) + 1 > 500:
                    control.status, control.error_code = 'failed', 'storage_limit_exceeded'
                else:
                    control.status = 'running'
                    control.started_at = control.started_at or now
                    for index, value in enumerate(values):
                        child = NodeRun(
                            run_id=run.id, node_id=item['id'], attempt=1,
                            execution_kind=f'{prefix}_item', foreach_index=index,
                            input_json=encoded({'_orchestration_role': f'{prefix}_item',
                                                f'{prefix}_item': value, 'foreach_index': index}),
                        )
                        db.add(child)
                        children.append(child)
                    # Empty collection takes the same explicit aggregation path.
                    db.flush()
            changed = True
            if control.status == 'failed':
                control.finished_at = now
                continue
        if control.status != 'running':
            continue
        failed = next((child for child in children if child.status in ('failed', 'canceled')), None)
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
                               'item_node_run_ids': [child.id for child in children],
                               'item_count': len(children)}
            output = encoded({'items': [json.loads(child.output_json) for child in children]})
            aggregate = NodeRun(
                # Keep the historical node-level attempt contract: the visible
                # aggregate records how many collection items were dispatched.
                # Item attempts remain independent and start at one for every
                # item, while foreach_index preserves the collection position.
                run_id=run.id, node_id=item['id'], attempt=len(children),
                execution_kind=f'{prefix}_aggregate', input_json=encoded(aggregate_input),
                output_json=output if len(output.encode()) <= 1024 * 1024 else None,
                status='succeeded' if len(output.encode()) <= 1024 * 1024 else 'failed',
                error_code=None if len(output.encode()) <= 1024 * 1024 else 'storage_limit_exceeded',
                started_at=control.started_at or now, finished_at=now,
            )
            db.add(aggregate)
            control.status, control.finished_at = aggregate.status, now
            changed = True
        else:
            idle = [child for child in children if child.status == 'idle']
            candidates.extend((f'{prefix}_item', item, child) for child in (
                idle if config.get('mode', 'serial') == 'parallel' else idle[:1]
            ))
    return candidates, changed
