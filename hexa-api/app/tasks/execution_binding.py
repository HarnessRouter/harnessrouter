"""Immutable execution identity carried by derived orchestration nodes."""


def execution_binding(snapshot, agent_id, model):
    """Return the secret-free Run binding for one execution identity.

    Dynamic plans and subgraphs may create local nodes at runtime, but they may
    never create a new execution identity.  The binding points back to the
    capability snapshot captured when the Run was created.  It is deliberately
    digest-only; the full capability record remains at Run scope.
    """
    capabilities = (snapshot or {}).get('capabilities') or {}
    capability = capabilities.get(str(agent_id)) if isinstance(capabilities, dict) else None
    capability = capability if isinstance(capability, dict) else {}
    return {
        'agent_id': str(agent_id or ''),
        'model': str(model or ''),
        'capability_snapshot_digest': str(capability.get('digest') or ''),
        'gateway_capability_digest': str(capability.get('gateway_capability_digest') or ''),
        'permission_policy_digest': str(capability.get('permission_policy_digest') or ''),
        'source': 'run_snapshot',
    }


def binding_matches(binding, snapshot, agent_id, model, *, required=False):
    """Check a derived node binding before any Gateway side effect."""
    if not isinstance(binding, dict):
        return not required
    if binding.get('source') != 'run_snapshot':
        return False
    if binding.get('agent_id') != str(agent_id or '') or binding.get('model') != str(model or ''):
        return False
    expected = execution_binding(snapshot, agent_id, model)
    for key in ('capability_snapshot_digest', 'gateway_capability_digest', 'permission_policy_digest'):
        if binding.get(key, '') != expected.get(key, ''):
            return False
    return True
