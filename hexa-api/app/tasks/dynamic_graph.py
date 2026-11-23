"""Validated local plan topology; execution policy always belongs to its parent."""
import json


def graph_valid(values):
    from app.tasks.service import TaskError, validate_condition
    if not isinstance(values, list):
        return False
    nodes = {}
    allowed = {'id', 'prompt', 'deps', 'inputRefs', 'condition', 'allow_missing_inputs'}
    for value in values:
        if not isinstance(value, dict) or set(value) - allowed:
            return False
        identity, prompt = value.get('id'), value.get('prompt')
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 255 or identity in nodes:
            return False
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            return False
        for field in ('deps', 'inputRefs'):
            refs = value.get(field, [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
                return False
        if 'allow_missing_inputs' in value and type(value['allow_missing_inputs']) is not bool:
            return False
        nodes[identity] = value
    if sum(len(value.get('deps', [])) for value in values) > 200:
        return False
    for identity, value in nodes.items():
        deps = set(value.get('deps', []))
        if identity in deps or deps - nodes.keys() or set(value.get('inputRefs', [])) - deps:
            return False
        try:
            validate_condition(value, set(nodes))
        except (TaskError, TypeError, ValueError):
            return False
    visited = set()
    while len(visited) < len(nodes):
        ready = {identity for identity, value in nodes.items()
                 if identity not in visited and set(value.get('deps', [])) <= visited}
        if not ready:
            return False
        visited.update(ready)
    return True


def graph_ready(children, condition_matches, now):
    """Only current-manifest successes satisfy local dependencies."""
    by_id = {json.loads(child.input_json)['dynamic_item']['id']: child for child in children}
    ready, changed = [], False
    for child in children:
        if child.status != 'idle':
            continue
        config = json.loads(child.input_json)['dynamic_item']
        deps = [by_id[identity] for identity in config.get('deps', [])]
        if not all(row.status == 'succeeded' or (row.status == 'skipped' and config.get('allow_missing_inputs')) for row in deps):
            continue
        condition = config.get('condition')
        if condition:
            source = by_id[condition['source']]
            output = json.loads(source.output_json) if source.output_json else None
            if not condition_matches(condition, output):
                child.status, child.error_code, child.finished_at = 'skipped', 'condition_not_matched', now
                changed = True
                continue
        ready.append(child)
    return ready, changed


def graph_refs(db, control, *, fanout_items):
    return {json.loads(child.input_json)['dynamic_item']['id']: child
            for child in fanout_items(db, control, 'dynamic')}
