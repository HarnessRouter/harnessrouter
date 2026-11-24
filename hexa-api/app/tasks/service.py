from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, update

from app.db.models import AppWorkspace, Artifact, CommandReceipt, NodeRun, Run, RunDecision, RunEvent, Task, TaskCommand, WorkflowRevision
from app.gateway.client import GatewayError
from app.tasks.domain import NodeSpec, WorkflowSpec, redact, validate_workflow
from app.tasks.fanout import node_record_usage


ACTIVE = ('pending', 'running', 'waiting_human', 'waiting_approval')


def is_human_node(item):
    return item.get('node_type') in {'human', 'human_gate'} or bool(item.get('requires_human'))


def is_explicit_human_node(item):
    return item.get('node_type') in {'human', 'human_gate'}


TOOL_APPROVAL_RISKS = frozenset({
    'read_only', 'workspace_read', 'workspace_write', 'local_process', 'network_read',
    'external_write', 'credential_access', 'destructive', 'permission_change',
})


def validate_tool_approval_policy(value, *, owner='workflow'):
    """Validate the saved approval requirement without granting any capability.

    The policy is deliberately a narrow declaration.  Runtime approval is still a
    separate Gateway/Runner capability and is fail-closed at Run start.
    """
    if value is None or not isinstance(value, dict) or set(value) != {'require'}:
        raise TaskError('invalid_workflow', f'{owner}.tool_approval_policy 只支持 require 风险列表。', 422)
    risks = value.get('require')
    if (not isinstance(risks, list) or not risks
            or any(not isinstance(risk, str) or risk not in TOOL_APPROVAL_RISKS for risk in risks)
            or len(risks) != len(set(risks))):
        raise TaskError('invalid_workflow', f'{owner}.tool_approval_policy.require 包含无效或重复风险。', 422)


def validate_tool_approval_policy_if_present(item, *, owner='workflow'):
    if 'tool_approval_policy' in item:
        validate_tool_approval_policy(item.get('tool_approval_policy'), owner=owner)


def workflow_requires_tool_approval(definition):
    if isinstance(definition, dict) and 'tool_approval_policy' in definition:
        return True
    for item in (definition.get('nodes') or []) if isinstance(definition, dict) else []:
        if isinstance(item, dict) and 'tool_approval_policy' in item:
            return True
        for child in ((item.get('subgraph') or {}).get('nodes') or []) if isinstance(item, dict) else []:
            if isinstance(child, dict) and 'tool_approval_policy' in child:
                return True
            for nested in ((child.get('subgraph') or {}).get('nodes') or []) if isinstance(child, dict) else []:
                if isinstance(nested, dict) and 'tool_approval_policy' in nested:
                    return True
    return False


class TaskError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _capability_digest(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def _safe_mcp_summary(server, source):
    if not isinstance(server, dict):
        return None
    result = {'name': str(server.get('name') or ''), 'source': source,
              'transport': str(server.get('transport') or server.get('type') or '')}
    if isinstance(server.get('url'), str) and server['url']:
        parts = urlsplit(server['url'])
        result['url'] = urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))
    for key in ('command', 'cwd'):
        if isinstance(server.get(key), str) and server[key]:
            result[key] = server[key]
    if isinstance(server.get('args'), list):
        result['args'] = [str(item) for item in server['args'][:32]]
    return result if result['name'] else None


def _safe_skill_summary(skill, source):
    if not isinstance(skill, dict):
        return None
    name = skill.get('name') or skill.get('id')
    if not isinstance(name, str) or not name:
        return None
    return {'name': name, 'source': source,
            **({'description': skill['description']} if isinstance(skill.get('description'), str) else {})}


def capability_snapshot(agent, discovery=None):
    """Create the immutable, secret-free capability view used by a Run.

    The Gateway remains the authority for plugin package parsing and runtime materialisation.
    This function records only stable identity and composition facts, never headers, auth, env,
    package files, or plugin scripts.
    """
    agent = agent if isinstance(agent, dict) else {}
    discovery = discovery if isinstance(discovery, dict) else {}
    plugins = []
    components = []
    for server in agent.get('mcpServers', agent.get('mcp_servers', [])) or []:
        summary = _safe_mcp_summary(server, 'direct')
        if summary:
            components.append({'kind': 'mcp', **summary})
    for skill in agent.get('skills', []) or []:
        summary = _safe_skill_summary(skill, 'direct')
        if summary:
            components.append({'kind': 'skill', **summary})
    for plugin in agent.get('plugins', []) or []:
        if not isinstance(plugin, dict) or not isinstance(plugin.get('name'), str):
            continue
        metadata_only = plugin.get('_metadata_only') is True
        manifest = plugin.get('manifest') if isinstance(plugin.get('manifest'), dict) else {}
        manifest_identity = {
            key: manifest[key] for key in ('name', 'version')
            if isinstance(manifest.get(key), str)
        }
        enabled = plugin.get('enabled', True) is not False
        plugin_components = []
        for server in plugin.get('mcpServers', []) or []:
            summary = _safe_mcp_summary(server, 'plugin')
            if summary:
                summary['plugin'] = plugin['name']
                components.append({'kind': 'mcp', **summary})
                plugin_components.append(summary)
        for skill in plugin.get('skills', []) or []:
            summary = _safe_skill_summary(skill, 'plugin')
            if summary:
                summary['plugin'] = plugin['name']
                components.append({'kind': 'skill', **summary})
                plugin_components.append(summary)
        skipped = [
            {'path': str(item.get('path') or ''), 'reason': str(item.get('reason') or '')}
            for item in (plugin.get('skipped') or [])
            if isinstance(item, dict)
        ]
        plugin_record = {
            'name': plugin['name'], 'enabled': enabled, 'manifest': manifest_identity,
            'manifest_digest': _capability_digest(manifest_identity), 'skipped': skipped,
            'component_digest': _capability_digest(plugin_components),
        }
        if metadata_only:
            plugin_record['metadata_only'] = True
        if isinstance(plugin.get('_package_digest'), str) and plugin['_package_digest']:
            plugin_record['package_digest'] = plugin['_package_digest']
        if isinstance(plugin.get('_package_read_error'), str):
            plugin_record['package_read_error'] = plugin['_package_read_error']
        # An installed but disabled plugin is retained in the snapshot for audit, while its
        # derived components are deliberately omitted from the effective composition below.
        if not enabled:
            components = [item for item in components if item.get('plugin') != plugin['name']]
        plugins.append(plugin_record)
    effective = {
        'agent_id': str(agent.get('id') or ''), 'base': str(agent.get('base') or ''),
        # Gateway owns this digest. Hexa retains its own secret-free snapshot digest below, but
        # sends this value back on every NodeRun so Gateway can reject a changed Harness before
        # allocating a session or dispatching a provider call.
        'gateway_capability_digest': str(agent.get('capabilityDigest') or agent.get('capability_digest') or ''),
        'components': sorted(components, key=lambda item: (item.get('kind', ''), item.get('name', ''), item.get('plugin', ''))),
        'disabled_tools': sorted({str(item) for item in (agent.get('disabledTools', agent.get('disabled_tools', [])) or []) if isinstance(item, str)}),
        'plugins': plugins,
        'discovery': {
            'versions': [str(item) for item in (discovery.get('versions') or []) if isinstance(item, str)],
            'capabilities': {str(key): bool(value) for key, value in (discovery.get('capabilities') or {}).items()},
            'plugin_schemas': [str(item) for item in (discovery.get('plugin_schemas') or []) if isinstance(item, str)],
        },
    }
    effective['digest'] = _capability_digest(effective)
    effective['preflight_errors'] = [
        {'plugin': item['name'], 'path': skipped['path'], 'reason': skipped['reason']}
        for item in plugins if item['enabled'] for skipped in item['skipped']
    ]
    if any(item['enabled'] and item.get('package_read_error') for item in plugins):
        effective['preflight_errors'].extend(
            {'plugin': item['name'], 'path': 'package', 'reason': item['package_read_error']}
            for item in plugins if item['enabled'] and item.get('package_read_error')
        )
    if any(item['enabled'] and not item.get('metadata_only') for item in plugins) and discovery.get('capabilities', {}).get('plugins') is not True:
        effective['preflight_errors'].append({'plugin': '*', 'path': 'uhp.discovery', 'reason': 'Gateway does not advertise plugins'})
    return effective


def append_run_event(db, run_id, event_type, *, node_run_id=None, data=None):
    """Append one redacted execution fact in the same transaction as its state."""
    db.add(RunEvent(run_id=run_id, node_run_id=node_run_id, event_type=event_type,
                    event_json=encoded(data or {})))


def workflow_concurrency(value):
    if 'max_concurrency' not in value:
        return 50
    raw = value['max_concurrency']
    if type(raw) is not int or not 1 <= raw <= 50:
        raise TaskError('invalid_workflow', '并发上限必须是 1 到 50 之间的整数。', 422)
    return raw


CONDITION_OPS = {'eq', 'neq', 'in', 'exists'}
CONDITION_PATH = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$')


def validate_condition(item, known_ids):
    condition = item.get('condition')
    if condition is None:
        return
    if not isinstance(condition, dict):
        raise TaskError('invalid_workflow', '条件必须是固定比较对象。', 422)
    source = condition.get('source')
    path = condition.get('path')
    op = condition.get('op')
    if not isinstance(source, str) or source not in set(item.get('deps', [])) or source not in known_ids:
        raise TaskError('invalid_workflow', '条件来源必须是当前节点的依赖。', 422)
    if not isinstance(path, str) or not CONDITION_PATH.fullmatch(path):
        raise TaskError('invalid_workflow', '条件路径格式无效。', 422)
    if op not in CONDITION_OPS:
        raise TaskError('invalid_workflow', '条件操作不受支持。', 422)
    if op == 'exists':
        if 'value' in condition:
            raise TaskError('invalid_workflow', 'exists 条件不能携带 value。', 422)
    elif 'value' not in condition:
        raise TaskError('invalid_workflow', '比较条件必须携带 value。', 422)
    elif op == 'in' and not isinstance(condition['value'], list):
        raise TaskError('invalid_workflow', 'in 条件的 value 必须是数组。', 422)


def validate_repeat(item):
    repeat = item.get('repeat')
    if repeat is None:
        return
    if item.get('foreach') is not None:
        raise TaskError('invalid_workflow', 'repeat 与 foreach 不能同时启用。', 422)
    if not isinstance(repeat, dict) or type(repeat.get('max_iterations')) is not int or not 1 <= repeat['max_iterations'] <= 10:
        raise TaskError('invalid_workflow', 'repeat.max_iterations 必须是 1 到 10 之间的整数。', 422)
    until = repeat.get('until')
    if not isinstance(until, dict) or until.get('op') not in CONDITION_OPS - {'in', 'neq'}:
        raise TaskError('invalid_workflow', 'repeat.until 必须是 eq 或 exists 条件。', 422)
    if not isinstance(until.get('path'), str) or not CONDITION_PATH.fullmatch(until['path']):
        raise TaskError('invalid_workflow', 'repeat.until.path 格式无效。', 422)
    if until['op'] == 'exists':
        if 'value' in until:
            raise TaskError('invalid_workflow', 'repeat.until.exists 不能携带 value。', 422)
    elif 'value' not in until:
        raise TaskError('invalid_workflow', 'repeat.until.eq 必须携带 value。', 422)


def validate_foreach(item, known_ids):
    foreach = item.get('foreach')
    if foreach is None:
        return
    if not isinstance(foreach, dict):
        raise TaskError('invalid_workflow', 'foreach 必须是固定集合对象。', 422)
    source = foreach.get('source')
    if not isinstance(source, str) or source not in set(item.get('deps', [])) or source not in known_ids:
        raise TaskError('invalid_workflow', 'foreach 来源必须是当前节点的依赖。', 422)
    if not isinstance(foreach.get('path'), str) or not CONDITION_PATH.fullmatch(foreach['path']):
        raise TaskError('invalid_workflow', 'foreach.path 格式无效。', 422)
    if type(foreach.get('max_items')) is not int or not 1 <= foreach['max_items'] <= 10:
        raise TaskError('invalid_workflow', 'foreach.max_items 必须是 1 到 10 之间的整数。', 422)
    if foreach.get('mode', 'serial') not in {'serial', 'parallel'}:
        raise TaskError('invalid_workflow', 'foreach.mode 只支持 serial 或 parallel。', 422)
    nested = foreach.get('nested')
    if nested is not None:
        if not isinstance(nested, dict) or set(nested) - {'path', 'max_items', 'mode'}:
            raise TaskError('invalid_workflow', 'foreach.nested 只支持 path、max_items 和 mode。', 422)
        if not isinstance(nested.get('path'), str) or not CONDITION_PATH.fullmatch(nested['path']):
            raise TaskError('invalid_workflow', 'foreach.nested.path 格式无效。', 422)
        if type(nested.get('max_items')) is not int or not 1 <= nested['max_items'] <= 10:
            raise TaskError('invalid_workflow', 'foreach.nested.max_items 必须是 1 到 10 之间的整数。', 422)
        if nested.get('mode', 'serial') not in {'serial', 'parallel'}:
            raise TaskError('invalid_workflow', 'foreach.nested.mode 只支持 serial 或 parallel。', 422)


def validate_loop(item, known_ids):
    loop = item.get('loop')
    if loop is None:
        return
    if item.get('repeat') is not None or item.get('foreach') is not None:
        raise TaskError('invalid_workflow', 'loop 不能与 repeat 或 foreach 同时启用。', 422)
    if not isinstance(loop, dict) or type(loop.get('max_iterations')) is not int or not 1 <= loop['max_iterations'] <= 10:
        raise TaskError('invalid_workflow', 'loop.max_iterations 必须是 1 到 10 之间的整数。', 422)
    body = loop.get('body')
    if not isinstance(body, list) or not body or len(set(body)) != len(body) or any(node_id not in known_ids for node_id in body):
        raise TaskError('invalid_workflow', 'loop.body 必须是已存在的静态节点列表。', 422)
    if item['id'] not in body:
        raise TaskError('invalid_workflow', 'loop.body 必须包含循环检查节点。', 422)
    until = loop.get('until')
    if not isinstance(until, dict) or until.get('source') not in body or until.get('op') not in {'eq', 'exists'}:
        raise TaskError('invalid_workflow', 'loop.until 必须引用循环体内的 eq 或 exists 条件。', 422)
    if not isinstance(until.get('path'), str) or not CONDITION_PATH.fullmatch(until['path']):
        raise TaskError('invalid_workflow', 'loop.until.path 格式无效。', 422)
    if until['op'] == 'exists' and 'value' in until:
        raise TaskError('invalid_workflow', 'loop.until.exists 不能携带 value。', 422)
    if until['op'] == 'eq' and 'value' not in until:
        raise TaskError('invalid_workflow', 'loop.until.eq 必须携带 value。', 422)


def validate_dynamic_plan(item, known_ids):
    plan = item.get('dynamic_plan')
    if plan is None:
        return
    if item.get('repeat') is not None or item.get('foreach') is not None or item.get('loop') is not None:
        raise TaskError('invalid_workflow', 'dynamic_plan 不能与 repeat、foreach 或 loop 同时启用。', 422)
    if not isinstance(plan, dict) or plan.get('source') not in set(item.get('deps', [])) or plan.get('source') not in known_ids:
        raise TaskError('invalid_workflow', 'dynamic_plan 来源必须是当前节点的依赖。', 422)
    if not isinstance(plan.get('path'), str) or not CONDITION_PATH.fullmatch(plan['path']):
        raise TaskError('invalid_workflow', 'dynamic_plan.path 格式无效。', 422)
    if type(plan.get('max_items')) is not int or not 1 <= plan['max_items'] <= 10:
        raise TaskError('invalid_workflow', 'dynamic_plan.max_items 必须是 1 到 10 之间的整数。', 422)
    if plan.get('mode', 'serial') not in {'serial', 'parallel'}:
        raise TaskError('invalid_workflow', 'dynamic_plan.mode 只支持 serial 或 parallel。', 422)
    if 'nested' in plan:
        raise TaskError('invalid_workflow', 'dynamic_plan 不支持嵌套集合展开。', 422)
    if plan.get('topology', 'list') not in ('list', 'dag'):
        raise TaskError('invalid_workflow', 'dynamic_plan.topology 只支持 list 或 dag。', 422)


def _validate_subgraph_shape(subgraph, known_ids, *, depth=0):
    """Validate one bounded subgraph scope; static scopes may nest once."""
    if not isinstance(subgraph, dict) or set(subgraph) - {'max_concurrency', 'nodes', 'dynamic'}:
        raise TaskError('invalid_workflow', 'subgraph 只支持 max_concurrency、nodes 或 dynamic。', 422)
    concurrency = subgraph.get('max_concurrency', 1)
    if type(concurrency) is not int or not 1 <= concurrency <= 10:
        raise TaskError('invalid_workflow', 'subgraph.max_concurrency 必须是 1 到 10 之间的整数。', 422)
    children = subgraph.get('nodes')
    dynamic = subgraph.get('dynamic')
    if (children is None) == (dynamic is None):
        raise TaskError('invalid_workflow', 'subgraph 必须二选一配置 nodes 或 dynamic。', 422)
    if dynamic is not None:
        if depth or not isinstance(dynamic, dict) or set(dynamic) - {'source', 'path', 'max_nodes', 'mode'}:
            raise TaskError('invalid_workflow', '动态子编排只能作为顶层子编排，不能递归。', 422)
        source = dynamic.get('source')
        if not isinstance(source, str) or source not in known_ids:
            raise TaskError('invalid_workflow', 'subgraph.dynamic.source 必须是父节点的依赖。', 422)
        if not isinstance(dynamic.get('path'), str) or not CONDITION_PATH.fullmatch(dynamic['path']):
            raise TaskError('invalid_workflow', 'subgraph.dynamic.path 格式无效。', 422)
        if type(dynamic.get('max_nodes')) is not int or not 1 <= dynamic['max_nodes'] <= 10:
            raise TaskError('invalid_workflow', 'subgraph.dynamic.max_nodes 必须是 1 到 10 之间的整数。', 422)
        if dynamic.get('mode', 'serial') not in {'serial', 'parallel'}:
            raise TaskError('invalid_workflow', 'subgraph.dynamic.mode 只支持 serial 或 parallel。', 422)
        return
    if not isinstance(children, list) or not 1 <= len(children) <= 10:
        raise TaskError('invalid_workflow', 'subgraph.nodes 必须包含 1 到 10 个静态节点。', 422)
    child_ids = set()
    specs = []
    allowed_child_fields = {'id', 'name', 'agent_id', 'model', 'prompt', 'deps', 'inputRefs', 'final_report', 'x', 'y', 'subgraph', 'tool_approval_policy'}
    for child in children:
        if not isinstance(child, dict):
            raise TaskError('invalid_workflow', 'subgraph 子节点格式无效。', 422)
        if set(child) - allowed_child_fields:
            raise TaskError('invalid_workflow', 'subgraph 子节点包含不受支持的字段。', 422)
        validate_tool_approval_policy_if_present(child, owner='subgraph node')
        child_id = child.get('id')
        if not isinstance(child_id, str) or not child_id.strip() or len(child_id) > 255 or child_id in child_ids:
            raise TaskError('invalid_workflow', 'subgraph 子节点 ID 无效或重复。', 422)
        child_ids.add(child_id)
        specs.append(NodeSpec(child_id, tuple(child.get('deps', [])), tuple(child.get('inputRefs', [])), bool(child.get('final_report')), False))
    try:
        validate_workflow(WorkflowSpec(tuple(specs)), max_nodes=10, max_edges=20)
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskError('invalid_workflow', 'subgraph 子节点、依赖或输入映射无效。', 422) from exc
    for child in children:
        if child.get('subgraph') is not None:
            if depth >= 1:
                raise TaskError('invalid_workflow', 'subgraph 最多支持两层静态嵌套。', 422)
            _validate_subgraph_shape(child['subgraph'], child_ids, depth=depth + 1)


def validate_subgraph(item, known_ids):
    """Validate a bounded subgraph scope owned by one parent NodeRun."""
    subgraph = item.get('subgraph')
    if subgraph is None:
        return
    if any(item.get(mode) is not None for mode in ('repeat', 'foreach', 'loop', 'dynamic_plan')):
        raise TaskError('invalid_workflow', 'subgraph 不能与 repeat、foreach、loop 或 dynamic_plan 同时启用。', 422)
    if not item.get('deps'):
        raise TaskError('invalid_workflow', 'subgraph 节点必须依赖父工作流节点。', 422)
    _validate_subgraph_shape(subgraph, set(item.get('deps', [])), depth=0)


def workflow_from_json(value):
    if not isinstance(value, dict) or not isinstance(value.get('nodes'), list):
        raise TaskError('invalid_workflow', '工作流格式无效。', 422)
    workflow_concurrency(value)
    if 'tool_approval_policy' in value:
        validate_tool_approval_policy(value.get('tool_approval_policy'))
    known_ids = {item.get('id') for item in value['nodes'] if isinstance(item, dict)}
    for item in value['nodes']:
        if isinstance(item, dict):
            validate_tool_approval_policy_if_present(item, owner=f"node {item.get('id', '')}")
            if is_explicit_human_node(item) and any(item.get(mode) is not None for mode in ('repeat', 'foreach', 'loop', 'dynamic_plan')):
                raise TaskError('invalid_workflow', '人工节点只支持单次执行模式。', 422)
            if is_explicit_human_node(item) and item.get('tool_approval_policy') is not None:
                raise TaskError('invalid_workflow', '人工节点不能声明工具审批策略。', 422)
            validate_condition(item, known_ids)
            validate_repeat(item)
            validate_foreach(item, known_ids)
            validate_loop(item, known_ids)
            validate_dynamic_plan(item, known_ids)
            validate_subgraph(item, known_ids)
    try:
        workflow = WorkflowSpec(tuple(NodeSpec(item['id'], tuple(item.get('deps', [])), tuple(item.get('inputRefs', [])), bool(item.get('final_report')), bool(item.get('requires_human'))) for item in value['nodes']))
        validate_workflow(workflow)
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskError('invalid_workflow', '节点、依赖或输入映射无效。', 422) from exc
    nodes = {item['id']: item for item in value['nodes']}
    scopes = []
    for controller in value['nodes']:
        loop = controller.get('loop')
        if not loop:
            continue
        body = set(loop['body'])
        ancestors = set()
        pending = list(controller.get('deps', []))
        while pending:
            current = pending.pop()
            if current not in ancestors:
                ancestors.add(current)
                pending.extend(nodes[current].get('deps', []))
        if body - (ancestors | {controller['id']}):
            raise TaskError('invalid_workflow', '循环检查必须依赖全部循环体节点。', 422)
        if any(body & scope for scope in scopes):
            raise TaskError('invalid_workflow', '循环体不能重叠；嵌套循环需要独立作用域。', 422)
        for other in value['nodes']:
            if other['id'] not in body and (set(other.get('deps', [])) & (body - {controller['id']})):
                raise TaskError('invalid_workflow', '循环体外节点只能依赖循环检查节点。', 422)
        scopes.append(body)
    if len(encoded(value).encode()) > 2 * 1024 * 1024:
        raise TaskError('storage_limit_exceeded', '工作流超过 2MB 限制。', 422)
    return workflow


def owned_task(db, task_id, user_id):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    selected = db.scalar(select(AppWorkspace.id).where(AppWorkspace.user_id == user_id, AppWorkspace.selected.is_(True)))
    if task is None or (selected is not None and task.workspace_id != selected):
        raise TaskError('not_found', '任务不存在。', 404)
    return task


def owned_run(db, run_id, user_id):
    run = db.scalar(select(Run).join(Task, Task.id == Run.task_id).where(Run.id == run_id, Task.user_id == user_id))
    selected = db.scalar(select(AppWorkspace.id).where(AppWorkspace.user_id == user_id, AppWorkspace.selected.is_(True)))
    task = db.get(Task, run.task_id) if run is not None else None
    if run is None or task is None or (selected is not None and task.workspace_id != selected):
        raise TaskError('not_found', '运行记录不存在。', 404)
    return run


def current_revision(db, task):
    if task.current_revision_id:
        revision = db.get(WorkflowRevision, task.current_revision_id)
        if revision and revision.task_id == task.id:
            return revision
    return db.scalar(select(WorkflowRevision).where(WorkflowRevision.task_id == task.id, WorkflowRevision.revision == task.current_revision))


def stale_nodes(db, task):
    adopted = json.loads(task.current_result_json)
    stale = set()
    for node_id, attempt_id in adopted.items():
        row = db.get(NodeRun, attempt_id)
        if row is None:
            stale.add(node_id)
            continue
        for ref in json.loads(row.input_json).get('refs', []):
            if ref['node_id'] in adopted and adopted[ref['node_id']] != ref['node_run_id']:
                stale.add(node_id)
    while True:
        before = set(stale)
        for node_id, attempt_id in adopted.items():
            row = db.get(NodeRun, attempt_id)
            if row and any(ref['node_id'] in stale for ref in json.loads(row.input_json).get('refs', [])):
                stale.add(node_id)
        if before == stale:
            return sorted(stale)


def task_json(db, task):
    revision = current_revision(db, task)
    latest = db.scalar(select(Run).where(Run.task_id == task.id).order_by(Run.id.desc()))
    source = None
    if task.source_template_id and task.source_template_version_id:
        source = {'id': task.source_template_id, 'version_id': task.source_template_version_id, 'version': task.source_template_version}
    return {'id': task.id, 'title': task.title, 'description': task.description, 'input': task.input_text, 'workspace_id': task.workspace_id,
            'source_template_id': task.source_template_id, 'source_template_version_id': task.source_template_version_id, 'source_template_version': task.source_template_version,
            'source_template': source, 'status': task.status, 'current_revision': task.current_revision,
            'current_revision_id': revision.id if revision else None,
            'workflow_revision': {'id': revision.id, 'revision': revision.revision, 'kind': 'saved'} if revision else None,
            'workflow_state': 'saved' if revision else 'draft',
            'workflow': json.loads(revision.definition_json) if revision else {'nodes': []},
            'current_result': json.loads(task.current_result_json), 'stale_nodes': stale_nodes(db, task),
            'latest_run_id': latest.id if latest else None}


def command_receipt_json(receipt):
    if receipt is None:
        return None
    return {'id': receipt.id, 'node_run_id': receipt.node_run_id, 'command_id': receipt.command_id,
            'request_hash': receipt.request_hash, 'side_effect_state': receipt.side_effect_state,
            'reconciliation_required': receipt.reconciliation_required, 'response_id': receipt.response_id,
            'error_code': receipt.error_code,
            'created_at': receipt.created_at.isoformat() if receipt.created_at else None,
            'updated_at': receipt.updated_at.isoformat() if receipt.updated_at else None}


def reconcile_receipt(db, run, row, receipt, response, *, encoded, redact_values=()):
    """Project an already stored Gateway response onto an unknown attempt.

    This function never dispatches work. The caller must have performed the
    Gateway read and must hold the task executor lock before entering it.
    """
    status = response.get('status') if isinstance(response, dict) else None
    if status not in {'completed', 'failed', 'incomplete', 'cancelled'}:
        return False
    if receipt.side_effect_state != 'unknown' or not receipt.reconciliation_required:
        return False
    if receipt.response_id and response.get('id') and str(response['id']) != receipt.response_id:
        return False
    safe = {'response_id': receipt.response_id, 'status': status}
    if status == 'completed':
        from app.gateway.client import response_text
        safe['text'] = redact(response_text(response), redact_values)
        row.status, row.error_code = 'succeeded', None
        row.output_json = encoded(safe)
        row.finished_at = datetime.now(timezone.utc)
        receipt.side_effect_state = 'completed'
        receipt.reconciliation_required = False
        receipt.error_code = None
        # A canceled Run remains canceled while reconciliation records the already
        # observed Gateway outcome. Only an executor-recovered failed Run may be
        # reopened for continuation.
        if run.status != 'canceled':
            run.status = 'running'
            task = db.get(Task, run.task_id)
            if task:
                task.status = 'running'
        append_run_event(db, run.id, 'node.reconciled', node_run_id=row.id,
                         data={'node_id': row.node_id, 'status': status})
    else:
        row.status, row.error_code = 'failed', 'agent_incomplete' if status == 'incomplete' else 'agent_failed'
        row.output_json = None
        row.finished_at = datetime.now(timezone.utc)
        receipt.side_effect_state = 'failed'
        receipt.reconciliation_required = False
        receipt.error_code = row.error_code
        append_run_event(db, run.id, 'node.reconciled', node_run_id=row.id,
                         data={'node_id': row.node_id, 'status': status, 'error_code': row.error_code})
    if row.status == 'failed':
        run.status = 'failed'
        task = db.get(Task, run.task_id)
        if task:
            task.status = 'failed'
    return True


def node_json(row, receipt=None):
    return {'id': row.id, 'node_id': row.node_id, 'run_id': row.run_id, 'attempt': row.attempt, 'status': row.status,
            'execution_kind': row.execution_kind, 'iteration': row.iteration, 'foreach_index': row.foreach_index,
            'input': json.loads(row.input_json), 'output': json.loads(row.output_json) if row.output_json else None,
            'error_code': row.error_code, 'response_id': row.response_id,
            'command_receipt': command_receipt_json(receipt),
            'progress': redact({'text': row.partial_text or '', 'execution': json.loads(row.execution_json) if row.execution_json else {}}),
            'started_at': row.started_at.isoformat() if row.started_at else None,
            'finished_at': row.finished_at.isoformat() if row.finished_at else None}


def latest_nodes(db, run_id):
    latest = {}
    rows = db.scalars(select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.iteration, NodeRun.attempt, NodeRun.id)).all()
    visible = [row for row in rows if row.execution_kind not in {
        'foreach_item', 'dynamic_item', 'foreach_nested_item', 'foreach_nested_aggregate',
        'subgraph_node', 'subgraph_aggregate',
    }]
    for row in visible:
        prior = latest.get(row.node_id)
        priority = (row.iteration, json.loads(row.input_json).get('control_node_run_id', row.id), row.execution_kind.endswith('_aggregate'), row.id)
        prior_priority = (prior.iteration, json.loads(prior.input_json).get('control_node_run_id', prior.id), prior.execution_kind.endswith('_aggregate'), prior.id) if prior else None
        if prior is None or priority >= prior_priority:
            latest[row.node_id] = row
    return latest


def receipts_for_nodes(db, rows):
    ids = [row.id for row in rows if row is not None]
    if not ids:
        return {}
    return {receipt.node_run_id: receipt for receipt in db.scalars(select(CommandReceipt).where(CommandReceipt.node_run_id.in_(ids))).all()}


def all_node_runs(db, run_id):
    return db.scalars(select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.id)).all()


def downstream_nodes(definition, target_node):
    affected = {target_node}
    changed = True
    while changed:
        changed = False
        for item in definition.get('nodes', []):
            if item['id'] not in affected and any(dep in affected for dep in item.get('deps', [])):
                affected.add(item['id'])
                changed = True
    return affected


_MISSING = object()


def condition_matches(condition, output):
    current = output
    for part in condition['path'].split('.'):
        if not isinstance(current, dict) or part not in current:
            current = _MISSING
            break
        current = current[part]
    if condition['op'] == 'exists':
        return current is not _MISSING
    if current is _MISSING:
        return False
    if condition['op'] == 'eq':
        return current == condition['value']
    if condition['op'] == 'neq':
        return current != condition['value']
    return current in condition['value']


def repeat_matches(repeat, output):
    return condition_matches(repeat['until'], output)


def value_at_path(output, path):
    current = output
    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def run_json(db, run):
    snapshot = json.loads(run.snapshot_json)
    revision = db.get(WorkflowRevision, run.workflow_revision_id) if run.workflow_revision_id else None
    revision_ref = {'id': revision.id, 'revision': revision.revision} if revision else {'id': run.workflow_revision_id, 'revision': run.workflow_revision}
    rows = latest_nodes(db, run.id)
    decisions = db.scalars(select(RunDecision).where(RunDecision.run_id == run.id).order_by(RunDecision.id)).all()
    receipts = receipts_for_nodes(db, rows.values())
    return {'id': run.id, 'task_id': run.task_id, 'workflow_revision': run.workflow_revision, 'workflow_revision_ref': revision_ref,
            'workflow_revision_number': run.workflow_revision, 'workflow_revision_id': run.workflow_revision_id,
            'status': run.status,
            'paused': run.paused, 'kind': run.kind, 'superseded_by': run.superseded_by,
            'workflow': snapshot.get('workflow', {}), 'execution_snapshot': snapshot,
            'nodes': [node_json(row, receipts.get(row.id)) for row in rows.values()],
            'decisions': [{'node_id': row.node_id, 'input_refs': json.loads(row.input_refs_json)} for row in decisions
                          if row.node_id in rows and row.iteration == rows[row.node_id].iteration],
            'decision_history': [{'node_id': row.node_id, 'iteration': row.iteration,
                                  'input_refs': json.loads(row.input_refs_json)} for row in decisions]}


def save_workflow(db, task, expected_revision, workflow):
    workflow_from_json(workflow)
    if db.scalar(select(Run.id).where(Run.task_id == task.id, Run.status.in_(ACTIVE))):
        raise TaskError('active_run_exists', '活动运行中配置已锁定，请先取消运行。')
    claimed = db.execute(update(Task).where(Task.id == task.id, Task.current_revision == expected_revision).values(current_revision=expected_revision + 1))
    if claimed.rowcount != 1:
        raise TaskError('revision_conflict', '工作流版本已变化，请刷新后重试。')
    revision = WorkflowRevision(task_id=task.id, revision=expected_revision + 1, definition_json=encoded(redact(workflow)))
    db.add(revision)
    db.flush()
    task.current_revision_id = revision.id
    db.commit()
    db.refresh(task)
    return task_json(db, task)


def command_replay(db, task_id, key, action, body):
    fingerprint = hashlib.sha256(encoded({'action': action, 'body': body}).encode()).hexdigest()
    prior = db.scalar(select(TaskCommand).where(TaskCommand.task_id == task_id, TaskCommand.key == key))
    if prior and prior.fingerprint != fingerprint:
        raise TaskError('idempotency_conflict', '幂等键已用于其他请求。')
    return fingerprint, json.loads(prior.response_json) if prior else None


def save_command(db, task_id, key, fingerprint, result):
    db.add(TaskCommand(task_id=task_id, key=key, fingerprint=fingerprint, response_json=encoded(result)))


async def prepare_run(db, task, body, key, gateway, secrets):
    fingerprint = hashlib.sha256(encoded(body).encode()).hexdigest()
    prior = db.scalar(select(Run).where(Run.task_id == task.id, Run.idempotency_key == key))
    if prior:
        if prior.request_hash != fingerprint:
            raise TaskError('idempotency_conflict', '幂等键已用于其他请求。')
        return prior, True
    if task.status == 'archived' or (task.status == 'completed' and body.get('kind') != 'rerun'):
        raise TaskError('invalid_transition', '请先重新打开任务。')
    revision = current_revision(db, task)
    definition = json.loads(revision.definition_json)
    workflow_from_json(definition)
    if workflow_requires_tool_approval(definition):
        raise TaskError('configuration_unavailable', '工具审批运行时尚未接通，不能启动需要审批的工作流。', 422)
    if not definition['nodes']:
        raise TaskError('invalid_workflow', '请先添加 Agent 节点。', 422)
    active = db.scalar(select(Run).where(Run.task_id == task.id, Run.status.in_(ACTIVE)))
    if active and not ((active.status in ('waiting_human', 'waiting_approval') or active.paused)
                       and active.workflow_revision != task.current_revision):
        raise TaskError('active_run_exists', '任务已有正在运行的 Run。')
    from app.tasks.resume import validate_resume, seed_resume
    resume = validate_resume(db, task, revision, definition, body, latest_nodes=latest_nodes, error=TaskError)
    try:
        agents = {row['id']: row for row in await gateway.list_agents(getattr(gateway, 'api_key', None))}
        catalogs = {}
        capability_rows = {}
        discovery = {}

        def workflow_agent_ids(nodes):
            for node in nodes or []:
                if not is_explicit_human_node(node) and node.get('agent_id'):
                    yield node['agent_id']
                yield from workflow_agent_ids((node.get('subgraph') or {}).get('nodes', []))

        used_agent_ids = set(workflow_agent_ids(definition['nodes']))
        for agent_id in used_agent_ids:
            if agent_id not in agents:
                raise ValueError('agent unavailable')
            if hasattr(gateway, 'get_agent_capabilities'):
                # Older/no-plugin Gateway adapters may expose only the harness list. Their
                # absence of an optional detail route is compatible when the list contains no
                # plugin declaration; an explicitly configured plugin remains fail-closed.
                listed = agents[agent_id]
                listed_plugins = listed.get('plugins') if isinstance(listed, dict) else None
                try:
                    capability_rows[agent_id] = await gateway.get_agent_capabilities(agent_id)
                except GatewayError:
                    if isinstance(listed_plugins, list) and listed_plugins:
                        for plugin in listed_plugins:
                            if isinstance(plugin, dict) and not any(key in plugin for key in ('manifest', 'mcpServers', 'skills', 'skipped')):
                                plugin['_metadata_only'] = True
                            elif isinstance(plugin, dict):
                                raise
                    capability_rows[agent_id] = listed
            else:
                capability_rows[agent_id] = agents[agent_id]
        has_plugins = any(
            isinstance(plugin, dict) and plugin.get('enabled', True) is not False and plugin.get('_metadata_only') is not True
            for row in capability_rows.values()
            for plugin in (row.get('plugins') or []) if isinstance(row, dict)
        )
        if has_plugins and hasattr(gateway, 'get_uhp_discovery'):
            discovery = await gateway.get_uhp_discovery()
        for item in definition['nodes']:
            if item.get('node_type') in {'human', 'human_gate'}:
                continue
            agent_id = item.get('agent_id', '')
            if agent_id not in agents:
                raise ValueError('agent unavailable')
            if agent_id not in catalogs:
                catalogs[agent_id] = await gateway.list_agent_models(agent_id)
            available = {row['id'] for row in catalogs[agent_id].get('models', []) if row.get('available', True)}
            if item.get('model') not in available:
                raise ValueError('model unavailable')
            for child in item.get('subgraph', {}).get('nodes', []):
                if child.get('subgraph') is not None:
                    for nested_child in child.get('subgraph', {}).get('nodes', []):
                        nested_agent_id = nested_child.get('agent_id', '')
                        if nested_agent_id not in agents:
                            raise ValueError('nested subgraph agent unavailable')
                        if nested_agent_id not in catalogs:
                            catalogs[nested_agent_id] = await gateway.list_agent_models(nested_agent_id)
                        nested_available = {row['id'] for row in catalogs[nested_agent_id].get('models', []) if row.get('available', True)}
                        if nested_child.get('model') not in nested_available:
                            raise ValueError('nested subgraph model unavailable')
                    continue
                child_agent_id = child.get('agent_id', '')
                if child_agent_id not in agents:
                    raise ValueError('subgraph agent unavailable')
                if child_agent_id not in catalogs:
                    catalogs[child_agent_id] = await gateway.list_agent_models(child_agent_id)
                child_available = {row['id'] for row in catalogs[child_agent_id].get('models', []) if row.get('available', True)}
                if child.get('model') not in child_available:
                    raise ValueError('subgraph model unavailable')
    except Exception as exc:
        raise TaskError('configuration_unavailable', '节点 Agent 或模型不可用，请检查配置。', 422) from exc
    capability_snapshots = {
        agent_id: capability_snapshot(capability_rows.get(agent_id, agents[agent_id]), discovery)
        for agent_id in sorted(capability_rows)
    }
    preflight_errors = [
        {'agent_id': agent_id, **error}
        for agent_id, snapshot_row in capability_snapshots.items()
        for error in snapshot_row.get('preflight_errors', [])
    ]
    if preflight_errors:
        raise TaskError('configuration_unavailable', 'Agent 插件存在未加载能力，请修复插件后再运行。', 422)
    if resume:
        previous_agents = json.loads(resume[0].snapshot_json).get('agents', {})
        used_agents = {item.get('agent_id') for item in definition['nodes'] if not is_explicit_human_node(item)}
        if any(redact(agents.get(identity), secrets) != previous_agents.get(identity) for identity in used_agents):
            raise TaskError('resume_configuration_conflict', 'Agent 配置已经改变，请整节点重跑。', 409)
    snapshot = redact({'workflow': definition, 'input': task.input_text, 'agents': agents,
                       'capabilities': capability_snapshots,
                       'workflow_revision_id': revision.id,
                       'source': {'kind': 'saved_workflow_revision', 'revision': revision.revision}}, secrets)
    if resume:
        snapshot['resume'] = {'source_run_id': resume[0].id, 'control_node_run_id': resume[3].id,
                              'item_node_run_id': body.get('item_node_run_id'),
                              'item_node_run_ids': [child.id for child in resume[4]],
                              'execution_config_source_run_id': resume[0].id}
    run = Run(task_id=task.id, workflow_revision=task.current_revision, workflow_revision_id=revision.id, idempotency_key=key, request_hash=fingerprint,
              snapshot_json=encoded(snapshot), kind=body.get('kind', 'normal'), target_node=body.get('target_node'))
    if run.kind == 'rerun' and run.target_node not in {item['id'] for item in definition['nodes']}:
        raise TaskError('invalid_workflow', '重跑节点不存在。', 422)
    db.add(run)
    db.flush()
    append_run_event(db, run.id, 'run.created', data={'kind': run.kind, 'workflow_revision_id': revision.id})
    reused = {}
    if run.kind == 'rerun' and run.target_node and not resume:
        affected = downstream_nodes(definition, run.target_node)
        adopted = json.loads(task.current_result_json)
        for node_id, attempt_id in adopted.items():
            row = db.get(NodeRun, attempt_id)
            source = db.get(Run, row.run_id) if row else None
            if node_id not in affected and row and source and source.task_id == task.id and row.status == 'succeeded':
                reused[node_id] = row
    for attempt_id in body.get('reuse_refs', []):
        row = db.get(NodeRun, attempt_id)
        source = db.get(Run, row.run_id) if row else None
        if not row or not source or source.task_id != task.id or row.status != 'succeeded' or row.node_id in stale_nodes(db, task):
            raise TaskError('input_ref_unavailable', '复用结果无效或已过期。', 422)
        reused[row.node_id] = row
    if resume:
        seed_resume(db, run, resume, body, encoded=encoded, downstream_nodes=downstream_nodes, error=TaskError)
    else:
        for item in definition['nodes']:
            row = reused.get(item['id'])
            db.add(NodeRun(run_id=run.id, node_id=item['id'], iteration=1, status='succeeded' if row else 'idle',
                           input_json=encoded({'reused_from': row.id}) if row else '{}', output_json=row.output_json if row else None))
    if active:
        active.status = 'completed'
        active.superseded_by = run.id
    task.status = 'running'
    db.commit()
    return run, False


class TaskExecutor:
    LEASE_TTL_SECONDS = 30
    LEASE_REAPER_INTERVAL_SECONDS = 10

    def __init__(self, session_factory, gateway, secrets=(), lease_owner=None):
        self.session_factory, self.gateway, self.secrets = session_factory, gateway, secrets
        self.lease_owner = lease_owner or f'hexa-api-{uuid.uuid4().hex}'
        self.jobs = {}
        self.locks = {}
        self.reaper_job = None

    @staticmethod
    def _utc(value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    def acquire_run_lease(self, db, run_id):
        now = datetime.now(timezone.utc)
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update().execution_options(populate_existing=True))
        if run is None or run.status not in ('pending', 'running') or run.paused:
            return None
        if run.lease_owner and run.lease_owner != self.lease_owner and run.lease_expires_at and self._utc(run.lease_expires_at) > now:
            return None
        run.lease_owner = self.lease_owner
        run.lease_fence = (run.lease_fence or 0) + 1
        run.lease_heartbeat_at = now
        run.lease_expires_at = now + timedelta(seconds=self.LEASE_TTL_SECONDS)
        return run.lease_fence

    def renew_run_lease(self, db, run_id, fence):
        now = datetime.now(timezone.utc)
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update().execution_options(populate_existing=True))
        if run is None or run.lease_owner != self.lease_owner or run.lease_fence != fence:
            return False
        run.lease_heartbeat_at = now
        run.lease_expires_at = now + timedelta(seconds=self.LEASE_TTL_SECONDS)
        return True

    def release_run_lease(self, db, run_id, fence):
        run = db.scalar(select(Run).where(Run.id == run_id).with_for_update().execution_options(populate_existing=True))
        if run is None or run.lease_owner != self.lease_owner or run.lease_fence != fence:
            return False
        run.lease_owner = None
        run.lease_heartbeat_at = None
        run.lease_expires_at = None
        return True

    def lock(self, task_id):
        return self.locks.setdefault(task_id, asyncio.Lock())

    def schedule(self, run_id):
        if run_id not in self.jobs or self.jobs[run_id].done():
            job = asyncio.create_task(self.execute(run_id))
            self.jobs[run_id] = job

    def start_reaper(self):
        if self.reaper_job is None or self.reaper_job.done():
            self.reaper_job = asyncio.create_task(self._reap_expired_leases())
        return self.reaper_job

    async def _reap_expired_leases(self):
        while True:
            try:
                await asyncio.sleep(self.LEASE_REAPER_INTERVAL_SECONDS)
                await asyncio.to_thread(self.recover, expired_only=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def close(self):
        if self.reaper_job is not None:
            self.reaper_job.cancel()
            await asyncio.gather(self.reaper_job, return_exceptions=True)
        for job in self.jobs.values():
            job.cancel()
        await asyncio.gather(*self.jobs.values(), return_exceptions=True)

    def recover(self, *, expired_only=False):
        with self.session_factory() as db:
            identities = db.scalars(select(Run.id).where(Run.status.in_(('pending', 'running')))).all()
        for identity in identities:
            with self.session_factory() as db:
                run = db.scalar(select(Run).where(Run.id == identity).with_for_update())
                if not run or run.status not in ('pending', 'running') or run.paused:
                    continue
                now = datetime.now(timezone.utc)
                if expired_only and not (run.lease_owner and run.lease_expires_at and self._utc(run.lease_expires_at) <= now):
                    continue
                if not expired_only and run.lease_owner and run.lease_expires_at and self._utc(run.lease_expires_at) > now:
                    continue
                run.lease_fence = (run.lease_fence or 0) + 1
                run.lease_owner = None
                run.lease_heartbeat_at = None
                run.lease_expires_at = None
                run.status = 'failed'
                task = db.get(Task, run.task_id)
                task.status = 'failed'
                append_run_event(db, run.id, 'run.recovered_unknown', data={'reason': 'executor_restart'})
                for row in all_node_runs(db, run.id):
                    if row.status in ('queued', 'running'):
                        row.status, row.error_code = 'failed', 'interrupted_unknown_outcome'
                        receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.node_run_id == row.id))
                        if receipt and receipt.side_effect_state in ('not_started', 'started'):
                            receipt.side_effect_state = 'unknown'
                            receipt.reconciliation_required = True
                            receipt.error_code = 'interrupted_unknown_outcome'
                            receipt.response_id = row.response_id or receipt.response_id
                        append_run_event(db, run.id, 'node.unknown', node_run_id=row.id,
                                         data={'node_id': row.node_id, 'error_code': row.error_code})
                append_run_event(db, run.id, 'run.failed', data={'error_code': 'interrupted_unknown_outcome'})
                db.commit()

    async def execute(self, run_id):
        with self.session_factory() as db:
            lease_fence = self.acquire_run_lease(db, run_id)
            if lease_fence is None:
                return
            db.commit()
        lease_stop = asyncio.Event()
        lease_lost = asyncio.Event()

        async def heartbeat():
            while not lease_stop.is_set():
                try:
                    await asyncio.wait_for(lease_stop.wait(), timeout=self.LEASE_TTL_SECONDS / 3)
                    return
                except asyncio.TimeoutError:
                    with self.session_factory() as lease_db:
                        if not self.renew_run_lease(lease_db, run_id, lease_fence):
                            lease_lost.set()
                            lease_db.rollback()
                            return
                        lease_db.commit()

        heartbeat_job = asyncio.create_task(heartbeat())
        try:
            while True:
                with self.session_factory() as db:
                    run = db.get(Run, run_id)
                    if not run or run.status not in ('pending', 'running') or run.paused or lease_lost.is_set() or not self.renew_run_lease(db, run_id, lease_fence):
                        db.rollback()
                        return
                    run.status = 'running'
                    task = db.get(Task, run.task_id)
                    snapshot = json.loads(run.snapshot_json)
                    definition = snapshot['workflow']
                    if workflow_requires_tool_approval(definition):
                        run.status = 'failed'
                        if task:
                            task.status = 'failed'
                        for row in all_node_runs(db, run.id):
                            receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.node_run_id == row.id))
                            if receipt and receipt.side_effect_state in ('started', 'unknown'):
                                receipt.side_effect_state = 'unknown'
                                receipt.reconciliation_required = True
                                receipt.error_code = row.error_code = 'interrupted_unknown_outcome'
                                append_run_event(db, run.id, 'node.unknown', node_run_id=row.id,
                                                 data={'node_id': row.node_id, 'error_code': row.error_code})
                            if row.status in ('idle', 'queued', 'running'):
                                row.status = 'failed'
                                if not (receipt and receipt.reconciliation_required):
                                    row.error_code = 'configuration_unavailable'
                                row.finished_at = datetime.now(timezone.utc)
                        append_run_event(db, run.id, 'run.failed', data={'error_code': 'configuration_unavailable'})
                        db.commit()
                        return
                    max_concurrency = workflow_concurrency(definition)
                    rows = latest_nodes(db, run.id)
                    nodes = {item['id']: item for item in definition['nodes']}
                    decisions = {row.node_id: json.loads(row.input_refs_json) for row in db.scalars(select(RunDecision).where(RunDecision.run_id == run.id)).all()
                                 if row.node_id in rows and row.iteration == rows[row.node_id].iteration}
                    from app.tasks.fanout import advance_fanouts
                    fanout_calls, fanout_changed = advance_fanouts(
                        db, run, definition, rows, encoded=encoded,
                        value_at_path=value_at_path, condition_matches=condition_matches,
                        decisions=decisions,
                    )
                    from app.tasks.subgraph import advance_subgraphs
                    subgraph_calls, subgraph_changed = advance_subgraphs(
                        db, run, definition, rows, encoded=encoded,
                        value_at_path=value_at_path, condition_matches=condition_matches,
                    )
                    if fanout_changed or subgraph_changed:
                        db.commit()
                        continue
                    unfinished = [item for item in nodes.values() if rows[item['id']].status == 'idle']
                    ready = [item for item in unfinished if all(rows[dep].status == 'succeeded' or (rows[dep].status == 'skipped' and item.get('allow_missing_inputs')) for dep in item.get('deps', []))]
                    for item in ready:
                        condition = item.get('condition')
                        if not condition:
                            continue
                        source = rows[condition['source']]
                        output = json.loads(source.output_json) if source.output_json else None
                        if not condition_matches(condition, output):
                            row = rows[item['id']]
                            row.status = 'skipped'
                            row.error_code = 'condition_not_matched'
                            row.finished_at = datetime.now(timezone.utc)
                    if any(item.get('condition') and rows[item['id']].status == 'skipped' for item in ready):
                        db.commit()
                        continue
                    executable = [item for item in ready if not (item.get('foreach') or item.get('dynamic_plan') or item.get('subgraph')) and (not is_human_node(item) or item['id'] in decisions)]
                    human_nodes = [item for item in executable if is_explicit_human_node(item)]
                    regular_agent_nodes = [item for item in executable if not is_explicit_human_node(item)]
                    work_units = [('node', item, rows[item['id']]) for item in regular_agent_nodes]
                    work_units.extend(fanout_calls)
                    work_units.extend(subgraph_calls)
                    work_units = [('human', item, rows[item['id']]) for item in human_nodes] + work_units[:max_concurrency]
                    if not work_units:
                        if ready:
                            run.status, task.status = 'waiting_human', 'waiting'
                        elif any(row.status == 'failed' for row in rows.values()):
                            run.status, task.status = 'failed', 'failed'
                            append_run_event(db, run.id, 'run.failed', data={'error_code': next((row.error_code for row in rows.values() if row.status == 'failed' and row.error_code), 'node_failed')})
                        elif all(row.status in ('succeeded', 'skipped') for row in rows.values()):
                            run.status = 'completed'
                            append_run_event(db, run.id, 'run.completed')
                            final = next((item for item in nodes.values() if item.get('final_report') and rows[item['id']].status == 'succeeded'), None)
                            if final:
                                task.current_result_json = encoded({final['id']: rows[final['id']].id})
                                task.status = 'completed'
                            else:
                                task.status = 'waiting'
                        else:
                            run.status, task.status = 'failed', 'failed'
                        db.commit()
                        return
                    calls = []
                    space = db.get(AppWorkspace, task.workspace_id) if task.workspace_id else None
                    for unit_kind, item, row in work_units:
                        refs = [] if unit_kind == 'subgraph_node' else decisions.get(item['id'], item.get('inputRefs', []))
                        if unit_kind == 'human':
                            inputs = [{'task_id': task.id, 'run_id': run.id, 'node_id': ref, 'node_run_id': rows[ref].id, 'output': json.loads(rows[ref].output_json)} for ref in refs if rows[ref].status == 'succeeded']
                            row.input_json = encoded({'task_input': snapshot['input'], 'refs': inputs, 'decision': 'human_confirmed'})
                            row.output_json = encoded({'selected_input_refs': refs, 'selected_results': inputs, 'status': 'confirmed'})
                            row.status = 'succeeded'
                            row.started_at = row.started_at or datetime.now(timezone.utc)
                            row.finished_at = datetime.now(timezone.utc)
                            continue
                        inputs = [{'task_id': task.id, 'run_id': run.id, 'node_id': ref, 'node_run_id': rows[ref].id, 'output': json.loads(rows[ref].output_json)} for ref in refs if ref in rows and rows[ref].status == 'succeeded']
                        context = redact({'task_input': snapshot['input'], 'prompt': item.get('prompt', ''), 'refs': inputs}, self.secrets)
                        state = json.loads(row.input_json)
                        from app.tasks.execution_binding import execution_binding
                        dynamic_binding_required = unit_kind in {
                            'subgraph_node', 'foreach_item', 'dynamic_item', 'foreach_nested_item',
                        } or isinstance(state.get('execution_binding'), dict)
                        binding = state.get('execution_binding')
                        if not isinstance(binding, dict) and not dynamic_binding_required:
                            binding = execution_binding(snapshot, item.get('agent_id'), item.get('model'))
                        context['execution_binding'] = binding
                        if unit_kind == 'subgraph_node':
                            state = json.loads(row.input_json)
                            context['subgraph_node_id'] = state['subgraph_node_id']
                            context['subgraph_parent_node_run_id'] = state['subgraph_parent_node_run_id']
                            context['subgraph_index'] = state['subgraph_index']
                            context['deps'] = state.get('deps', [])
                            context['inputRefs'] = state.get('inputRefs', [])
                            if state.get('nested_subgraph_parent'):
                                context['nested_subgraph_parent'] = True
                                context['nested_parent_node_id'] = state.get('nested_parent_node_id')
                                context['nested_prompt_prefix'] = state.get('nested_prompt_prefix', '')
                            from app.tasks.subgraph import _children, _refs
                            parent = db.get(NodeRun, state['subgraph_parent_node_run_id'])
                            context['refs'] = state.get('parent_refs', []) + _refs(_children(db, parent), state)
                            if state.get('nested_subgraph_parent') and parent and parent.status == 'succeeded' and parent.output_json:
                                context['refs'].append({'id': state.get('nested_parent_node_id'), 'node_run_id': parent.id,
                                                        'output': json.loads(parent.output_json)})
                                context['prompt'] = state.get('nested_prompt_prefix', '') + '\n' + item.get('prompt', '')
                            elif state.get('nested_subgraph_parent'):
                                context['prompt'] = state.get('nested_prompt_prefix', '') + '\n' + item.get('prompt', '')
                            if state.get('dynamic'):
                                dynamic_prompt = state.get('dynamic_node', {}).get('prompt', '')
                                context['prompt'] = state.get('dynamic_parent_prompt', '') + '\n' + dynamic_prompt
                                context['dynamic'] = True
                                context['dynamic_node'] = state.get('dynamic_node', {})
                                context['dynamic_parent_prompt'] = state.get('dynamic_parent_prompt', '')
                            context['_orchestration_role'] = 'subgraph_node'
                        if unit_kind in ('foreach_item', 'dynamic_item', 'foreach_nested_item'):
                            context['refs'] = json.loads(rows[item['id']].input_json).get('refs', inputs)
                        previous = state.get('loop_previous')
                        if previous:
                            previous_rows = [db.get(NodeRun, identity) for identity in previous['node_run_ids']]
                            context['loop_previous'] = {
                                'iteration': previous['iteration'],
                                'refs': [{'node_id': prior.node_id, 'node_run_id': prior.id,
                                          'output': json.loads(prior.output_json)}
                                         for prior in previous_rows
                                         if prior and prior.run_id == run.id and prior.status == 'succeeded' and prior.output_json],
                            }
                        if unit_kind in ('foreach_item', 'dynamic_item', 'foreach_nested_item'):
                            context[unit_kind] = state[unit_kind]
                            if unit_kind == 'foreach_nested_item':
                                context['foreach_item'] = state['foreach_nested_item']
                                context['outer_item_node_run_id'] = state['outer_item_node_run_id']
                                context['outer_foreach_index'] = state['outer_foreach_index']
                            context['foreach_index'] = row.foreach_index
                            if unit_kind == 'dynamic_item':
                                context['dynamic_index'] = row.foreach_index
                                context['prompt'] = item.get('prompt', '') + '\n' + state[unit_kind]['prompt']
                                if item['dynamic_plan'].get('topology') == 'dag':
                                    from app.tasks.dynamic_graph import graph_refs
                                    from app.tasks.fanout import fanout_items
                                    local = graph_refs(db, rows[item['id']], fanout_items=fanout_items)
                                    context['plan_refs'] = [
                                        {'id': identity, 'node_run_id': local[identity].id,
                                         'output': json.loads(local[identity].output_json)}
                                        for identity in state['dynamic_item'].get('inputRefs', [])
                                        if local[identity].status == 'succeeded'
                                    ]
                            context['_orchestration_role'] = unit_kind
                        row.input_json, row.status = encoded(redact(context, self.secrets)), 'running'
                        row.started_at = datetime.now(timezone.utc)
                        command_id = f'hexa-task-{run.id}-{row.id}'
                        request_hash = hashlib.sha256(encoded({
                            'command_id': command_id,
                            'agent_id': item.get('agent_id', ''),
                            'model': item.get('model', ''),
                            'context': context,
                        }).encode()).hexdigest()
                        db.add(CommandReceipt(node_run_id=row.id, command_id=command_id,
                                              request_hash=request_hash, side_effect_state='not_started'))
                        append_run_event(db, run.id, 'node.dispatched', node_run_id=row.id,
                                         data={'node_id': row.node_id, 'execution_kind': row.execution_kind,
                                               'attempt': row.attempt, 'iteration': row.iteration})
                        calls.append((row.id, item, context, space.gateway_id if space else ''))
                    db.commit()
                await asyncio.gather(*(self.execute_node(run_id, *call, lease_fence=lease_fence, lease_lost=lease_lost) for call in calls))
                with self.session_factory() as db:
                    run = db.get(Run, run_id)
                    if not run or run.status not in ('pending', 'running'):
                        continue
                    definition = json.loads(run.snapshot_json)['workflow']
                    rows = latest_nodes(db, run_id)
                    repeat_rows = []
                    for item in definition['nodes']:
                        repeat = item.get('repeat')
                        row = rows[item['id']]
                        if repeat and row.status == 'succeeded' and not repeat_matches(repeat, json.loads(row.output_json) if row.output_json else None):
                            repeat_rows.append((item, row))
                    for item, row in repeat_rows:
                        repeat = item['repeat']
                        if row.attempt >= repeat['max_iterations']:
                            row.status = 'failed'
                            row.error_code = 'repeat_limit_exceeded'
                            row.finished_at = datetime.now(timezone.utc)
                        elif node_record_usage(db, run_id) >= 500:
                            row.status, row.error_code = 'failed', 'storage_limit_exceeded'
                            row.finished_at = datetime.now(timezone.utc)
                        else:
                            from app.tasks.execution_binding import execution_binding
                            db.add(NodeRun(run_id=run_id, node_id=row.node_id, attempt=row.attempt + 1,
                                           iteration=row.iteration, status='idle',
                                           input_json=encoded({'execution_binding': execution_binding(
                                               json.loads(run.snapshot_json), item.get('agent_id'), item.get('model'))})))
                            db.flush()
                    loop_changed = False
                    for item in definition['nodes']:
                        loop = item.get('loop')
                        row = rows[item['id']]
                        if not loop or row.status != 'succeeded':
                            continue
                        until_source = rows.get(loop['until']['source'])
                        until_output = json.loads(until_source.output_json) if until_source and until_source.output_json else None
                        if condition_matches(loop['until'], until_output):
                            continue
                        if row.iteration >= loop['max_iterations']:
                            row.status = 'failed'
                            row.error_code = 'loop_limit_exceeded'
                            row.finished_at = datetime.now(timezone.utc)
                            loop_changed = True
                            continue
                        count = node_record_usage(db, run_id)
                        if count + len(loop['body']) > 500:
                            row.status, row.error_code = 'failed', 'storage_limit_exceeded'
                            row.finished_at = datetime.now(timezone.utc)
                            loop_changed = True
                            continue
                        next_iteration = row.iteration + 1
                        previous = {'iteration': row.iteration,
                                    'node_run_ids': [rows[identity].id for identity in loop['body']
                                                     if rows[identity].status == 'succeeded']}
                        from app.tasks.execution_binding import execution_binding
                        snapshot_for_binding = json.loads(run.snapshot_json)
                        by_node_id = {node['id']: node for node in definition['nodes']}
                        for body_node_id in loop['body']:
                            db.add(NodeRun(run_id=run_id, node_id=body_node_id, attempt=1,
                                           iteration=next_iteration, status='idle',
                                           input_json=encoded({
                                               'loop_previous': previous,
                                               'execution_binding': execution_binding(
                                                   snapshot_for_binding, by_node_id[body_node_id].get('agent_id'),
                                                   by_node_id[body_node_id].get('model')),
                                           })))
                        db.flush()
                        loop_changed = True
                    if repeat_rows or loop_changed:
                        db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            with self.session_factory() as db:
                run = db.get(Run, run_id)
                if run and run.status in ('pending', 'running'):
                    run.status = 'failed'
                    task = db.get(Task, run.task_id)
                    if task:
                        task.status = 'failed'
                    for row in all_node_runs(db, run_id):
                        if row.status in ('queued', 'running'):
                            row.status = 'failed'
                            row.error_code = 'executor_error'
                    append_run_event(db, run.id, 'run.failed', data={'error_code': 'executor_error'})
                    db.commit()
        finally:
            lease_stop.set()
            heartbeat_job.cancel()
            await asyncio.gather(heartbeat_job, return_exceptions=True)
            with self.session_factory() as db:
                if self.release_run_lease(db, run_id, lease_fence):
                    db.commit()

    async def execute_node(self, run_id, attempt_id, item, context, workspace_id, *, lease_fence=None, lease_lost=None):
        result, error = None, None
        exception_response_id = None
        command_id = f'hexa-task-{run_id}-{attempt_id}'
        request_hash = hashlib.sha256(encoded({
            'command_id': command_id,
            'agent_id': item.get('agent_id', ''),
            'model': item.get('model', ''),
            'context': context,
        }).encode()).hexdigest()
        run_snapshot = {}
        with self.session_factory() as db:
            if lease_fence is not None:
                run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
                if (not run or run.status != 'running' or run.lease_owner != self.lease_owner
                        or run.lease_fence != lease_fence or (lease_lost and lease_lost.is_set())):
                    db.rollback()
                    return
            current_run = db.get(Run, run_id)
            if current_run:
                run_snapshot = json.loads(current_run.snapshot_json)
            receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.node_run_id == attempt_id))
            if receipt is None:
                receipt = CommandReceipt(node_run_id=attempt_id, command_id=command_id,
                                         request_hash=request_hash, side_effect_state='not_started')
                db.add(receipt)
            receipt.side_effect_state = 'started'
            db.commit()
        def save_progress(*, response_id=None, partial=None, details=None):
            with self.session_factory() as db:
                run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
                if lease_fence is not None and (not run or run.lease_owner != self.lease_owner
                        or run.lease_fence != lease_fence or (lease_lost and lease_lost.is_set())):
                    return
                row = db.get(NodeRun, attempt_id)
                if not row or not run or row.status != 'running' or run.status != 'running':
                    return
                if response_id:
                    row.response_id = response_id
                    receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.node_run_id == row.id))
                    if receipt:
                        receipt.response_id = response_id
                if partial is not None:
                    row.partial_text = redact(partial, self.secrets)[:262144]
                if details is not None:
                    from app.gateway.execution import safe_execution
                    row.execution_json = encoded(safe_execution(details, self.secrets))
                db.commit()
        async def progress(response_id, partial):
            save_progress(response_id=response_id, partial=partial)
        async def execution(details):
            save_progress(details=details)
        try:
            binding = context.get('execution_binding') if isinstance(context, dict) else None
            dynamic_binding_required = bool(isinstance(context, dict) and context.get('_orchestration_role') in {
                'subgraph_node', 'foreach_item', 'dynamic_item', 'foreach_nested_item',
            })
            if not isinstance(binding, dict) and not dynamic_binding_required:
                from app.tasks.execution_binding import execution_binding
                binding = execution_binding(run_snapshot, item.get('agent_id'), item.get('model'))
            from app.tasks.execution_binding import binding_matches
            if not binding_matches(binding, run_snapshot, item.get('agent_id'), item.get('model'),
                                   required=dynamic_binding_required):
                raise GatewayError('执行配置绑定与节点不一致。', code='hexa_execution_binding_changed')
            agent_snapshot = (run_snapshot.get('capabilities') or {}).get(item.get('agent_id', ''), {})
            result = await self.gateway.create_response(
                encoded(context), None, f'hexa-task-{run_id}-{attempt_id}',
                agent_id=item['agent_id'], model=item['model'], workspace_id=workspace_id,
                capability_digest=agent_snapshot.get('gateway_capability_digest', ''),
                on_progress=progress, on_execution=execution)
            if result.get('execution'):
                await execution(result['execution'])
            if (result.get('status') == 'incomplete'
                    and isinstance(result.get('approval'), dict)
                    and result['approval'].get('id')
                    and result['approval'].get('command_id')):
                error = 'tool_approval_required'
            elif result.get('status') != 'completed':
                error = 'agent_incomplete'
            if len(encoded(result).encode()) > 1024 * 1024:
                error = 'storage_limit_exceeded'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            exception_response_id = getattr(exc, 'response_id', None)
            error = ('configuration_changed' if isinstance(exc, GatewayError)
                     and getattr(exc, 'code', '') in {'hexa_capability_changed', 'hexa_execution_binding_changed'}
                     else 'agent_failed' if isinstance(exc, GatewayError) and not exc.uncertain
                     else 'interrupted_unknown_outcome')
        uncertain = error == 'interrupted_unknown_outcome'
        with self.session_factory() as db:
            run = db.scalar(select(Run).where(Run.id == run_id).with_for_update())
            row = db.get(NodeRun, attempt_id)
            if run is None or row is None:
                return
            if run.status == 'canceled' or row.status == 'canceled':
                # Cancellation can race the Gateway return. Preserve the response identity
                # and unknown side-effect fact even though the NodeRun cannot be completed.
                receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.node_run_id == row.id))
                if receipt and receipt.side_effect_state in ('not_started', 'started', 'unknown'):
                    receipt.side_effect_state = 'unknown'
                    receipt.reconciliation_required = True
                    receipt.error_code = 'interrupted_unknown_outcome'
                    response_identity = ((result or {}).get('response_id') if isinstance(result, dict) else None) or exception_response_id
                    if response_identity:
                        receipt.response_id = str(response_identity)
                        row.response_id = str(response_identity)
                db.commit()
                return
            if run.status != 'running' or row.status != 'running':
                return
            if lease_fence is not None and (lease_lost and lease_lost.is_set() or run.lease_owner != self.lease_owner or run.lease_fence != lease_fence):
                db.rollback()
                return
            task = db.get(Task, run.task_id)
            artifacts = []
            for file in (result or {}).get('files', []) if not error and isinstance(result, dict) else []:
                if not file.get('file_id') or not file.get('container_id'):
                    continue
                artifact = Artifact(
                    user_id=task.user_id,
                    workspace_id=task.workspace_id,
                    task_id=task.id,
                    run_id=run.id,
                    node_run_id=row.id,
                    gateway_file_id=str(file['file_id']),
                    gateway_container_id=str(file['container_id']),
                    filename=str(file.get('filename') or '输出文件')[:1024],
                    media_type=str(file.get('media_type') or 'application/octet-stream')[:255],
                    bytes=int(file.get('bytes') or 0),
                )
                db.add(artifact)
                db.flush()
                artifacts.append({'id': artifact.id, 'filename': artifact.filename, 'media_type': artifact.media_type, 'bytes': artifact.bytes})
            waiting_approval = error == 'tool_approval_required'
            row.status = 'waiting_approval' if waiting_approval else ('failed' if error else 'succeeded')
            row.error_code = error
            if isinstance(result, dict) and result.get('response_id'):
                row.response_id = str(result['response_id'])
            elif exception_response_id:
                row.response_id = str(exception_response_id)
            if waiting_approval:
                row.output_json = encoded({'approval': redact(result.get('approval'), self.secrets)})
            elif error:
                row.output_json = None
            else:
                safe_result = dict(redact(result, self.secrets)) if isinstance(result, dict) else {'value': redact(result, self.secrets)}
                safe_result.pop('files', None)
                if artifacts:
                    safe_result['artifacts'] = artifacts
                row.output_json = encoded(safe_result)
            row.finished_at = datetime.now(timezone.utc)
            receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.node_run_id == row.id))
            if receipt:
                receipt.side_effect_state = 'unknown' if uncertain else ('not_started' if waiting_approval else ('failed' if error else 'completed'))
                receipt.reconciliation_required = uncertain
                receipt.response_id = row.response_id
                receipt.error_code = error
            event_type = ('node.unknown' if uncertain else 'node.approval_required' if waiting_approval
                          else 'node.failed' if error else 'node.succeeded')
            append_run_event(db, run.id, event_type, node_run_id=row.id,
                             data={'node_id': row.node_id, **({'error_code': error} if error else {})})
            if waiting_approval:
                run.status = 'waiting_approval'
                task.status = 'waiting'
                append_run_event(db, run.id, 'run.waiting_approval', data={'node_id': row.node_id})
            db.commit()
