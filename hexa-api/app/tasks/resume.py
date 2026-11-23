"""Explicit terminal collection recovery; all writes share prepare_run's transaction."""
import json

from app.db.models import NodeRun, Run
from app.tasks.fanout import fanout_items, retry_fanout, node_record_usage


def validate_resume(db, task, revision, definition, body, *, latest_nodes, error):
    source_id = body.get('resume_from_run_id')
    if source_id is None:
        if body.get('item_node_run_id') is not None:
            raise error('invalid_resume', '指定恢复项时必须提供来源 Run。', 422)
        return None
    if body.get('kind') != 'rerun' or not body.get('target_node') or body.get('reuse_refs'):
        raise error('invalid_resume', '集合恢复必须指定重跑节点且不能混合复用列表。', 422)
    source = db.get(Run, source_id)
    if not source or source.task_id != task.id:
        raise error('not_found', '来源运行不存在。', 404)
    if source.status not in ('failed', 'canceled'):
        raise error('invalid_resume', '只能从失败或取消的终态运行恢复。', 422)
    snapshot = json.loads(source.snapshot_json)
    if source.workflow_revision_id != revision.id or snapshot.get('workflow') != definition or snapshot.get('input') != task.input_text:
        raise error('resume_revision_conflict', '工作流或输入已经改变，请整节点重跑。', 409)
    item = next((node for node in definition['nodes'] if node['id'] == body['target_node']), None)
    if not item or not (item.get('foreach') or item.get('dynamic_plan')):
        raise error('invalid_resume', '恢复目标必须是集合展开节点。', 422)
    rows = latest_nodes(db, source.id)
    control = rows[item['id']]
    if control.status not in ('failed', 'canceled'):
        raise error('invalid_resume', '只能恢复失败或取消的集合。', 422)
    children = fanout_items(db, control, 'dynamic' if item.get('dynamic_plan') else 'foreach')
    if not children:
        raise error('invalid_resume', '来源集合未展开，请整节点重跑。', 422)
    selected_id = body.get('item_node_run_id')
    if selected_id is not None and not any(child.id == selected_id and child.status in ('failed', 'canceled') for child in children):
        raise error('invalid_retry_item', '只能选择当前清单中失败或取消的项。', 422)
    return source, rows, item, control, children


def seed_resume(db, run, resume, body, *, encoded, downstream_nodes, error):
    source, rows, item, control, children = resume
    mapping = {}

    def copy_record(prior, *, full_input=True):
        if prior.id in mapping:
            return mapping[prior.id]
        clone = NodeRun(
            run_id=run.id, node_id=prior.node_id, iteration=prior.iteration,
            attempt=prior.attempt, execution_kind=prior.execution_kind,
            foreach_index=prior.foreach_index, status=prior.status,
            input_json=encoded({'reused_from': prior.id}), output_json=prior.output_json,
            error_code=prior.error_code, started_at=prior.started_at, finished_at=prior.finished_at,
        )
        db.add(clone)
        db.flush()
        mapping[prior.id] = clone
        if node_record_usage(db, run.id) > 500:
            raise error('storage_limit_exceeded', '恢复运行超过 500 条记录限制。', 422)
        if full_input:
            state = json.loads(prior.input_json)
            # Source links are explicit provenance; runtime continuation IDs and
            # approval records are never copied into the new execution.
            for key in ('item_node_run_ids', 'retry_item_node_run_ids'):
                if key in state:
                    entries = [db.get(NodeRun, identity) for identity in state[key]]
                    if any(row is None or row.run_id != source.id or row.node_id != prior.node_id for row in entries):
                        raise error('invalid_resume', '来源执行清单不可用。', 422)
                    state[key] = [copy_record(row).id for row in entries]
            if 'nested_item_node_run_ids' in state:
                entries = [db.get(NodeRun, identity) for identity in state['nested_item_node_run_ids']]
                if any(row is None or row.run_id != source.id or row.node_id != prior.node_id
                       or row.execution_kind != 'foreach_nested_item' for row in entries):
                    raise error('invalid_resume', '来源嵌套执行清单不可用。', 422)
                state['nested_item_node_run_ids'] = [copy_record(row).id for row in entries]
            if 'nested_aggregate_node_run_id' in state:
                nested_aggregate = db.get(NodeRun, state['nested_aggregate_node_run_id'])
                if not nested_aggregate or nested_aggregate.run_id != source.id or nested_aggregate.node_id != prior.node_id:
                    raise error('invalid_resume', '来源嵌套聚合记录不可用。', 422)
                state['nested_aggregate_node_run_id'] = copy_record(nested_aggregate).id
            if 'outer_item_node_run_id' in state:
                parent = db.get(NodeRun, state['outer_item_node_run_id'])
                if not parent or parent.run_id != source.id or parent.node_id != prior.node_id or parent.execution_kind != 'foreach_item':
                    raise error('invalid_resume', '来源外层执行记录不可用。', 422)
                state['outer_item_node_run_id'] = copy_record(parent).id
            if 'control_node_run_id' in state:
                old_control = db.get(NodeRun, state['control_node_run_id'])
                if not old_control or old_control.run_id != source.id or old_control.node_id != prior.node_id:
                    raise error('invalid_resume', '来源聚合控制记录不可用。', 422)
                state['control_node_run_id'] = copy_record(old_control).id
            previous = state.get('loop_previous')
            if previous:
                if 'node_run_ids' in previous:
                    previous_ids = previous['node_run_ids']
                else:
                    previous_ids = [ref['node_run_id'] for ref in previous.get('refs', [])]
                previous_rows = [db.get(NodeRun, identity) for identity in previous_ids]
                if any(row is None or row.run_id != source.id or row.status != 'succeeded' for row in previous_rows):
                    raise error('invalid_resume', '上一轮成功结果引用不可用。', 422)
                state['loop_previous'] = {'iteration': previous['iteration'],
                                          'node_run_ids': [copy_record(row).id for row in previous_rows]}
            refs = []
            for ref in state.get('refs', []):
                upstream = db.get(NodeRun, ref['node_run_id'])
                if not upstream or upstream.run_id != source.id or upstream.status != 'succeeded':
                    raise error('invalid_resume', '来源输入引用不可用。', 422)
                refs.append({**ref, 'run_id': run.id, 'node_run_id': copy_record(upstream).id})
            if 'refs' in state:
                state['refs'] = refs
            if 'plan_refs' in state:
                local_refs = []
                for ref in state['plan_refs']:
                    upstream = db.get(NodeRun, ref['node_run_id'])
                    if (not upstream or upstream.run_id != source.id or upstream.node_id != prior.node_id
                            or upstream.iteration != prior.iteration or upstream.execution_kind != 'dynamic_item'
                            or upstream.status != 'succeeded'):
                        raise error('invalid_resume', '来源子图输入引用不可用。', 422)
                    local_refs.append({**ref, 'node_run_id': copy_record(upstream).id})
                state['plan_refs'] = local_refs
            clone.input_json = encoded({**state, 'reused_from': prior.id})
        return clone

    affected = downstream_nodes(json.loads(run.snapshot_json)['workflow'], item['id'])
    # If the target belongs to a loop, continue from that entire loop's round.
    loop_body = set()
    for node in json.loads(run.snapshot_json)['workflow']['nodes']:
        if item['id'] in node.get('loop', {}).get('body', []):
            loop_body.update(node['loop']['body'])
    for node_id, prior in rows.items():
        if node_id == item['id']:
            continue
        if node_id not in affected and prior.status in ('succeeded', 'skipped', 'failed', 'canceled'):
            copy_record(prior)
        else:
            pending = copy_record(prior)
            pending.status, pending.output_json, pending.error_code = 'idle', None, None
            pending.started_at, pending.finished_at = None, None
            pending.execution_kind, pending.attempt = 'node', 1
            pending.iteration = control.iteration if node_id in loop_body else prior.iteration
    copied_control = copy_record(control)
    copied_children = [copy_record(child) for child in children]
    state = json.loads(copied_control.input_json)
    state['item_node_run_ids'] = [child.id for child in copied_children]
    copied_control.input_json = encoded(state)
    retry = retry_fanout(db, run, item, copied_control,
                         mapping[body['item_node_run_id']].id if body.get('item_node_run_id') else None,
                         encoded=encoded, error=error)
    if item.get('requires_human'):
        retry.status = 'idle'
    db.flush()
    if node_record_usage(db, run.id) > 500:
        raise error('storage_limit_exceeded', '恢复运行超过 500 条记录限制。', 422)
