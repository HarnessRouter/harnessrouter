"""Pure validation tests run without installing the optional native Runtime."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langgraph_approval import LangGraphApprovalAdapter, NativeApprovalError
from runtime_lease import RuntimeLeaseRegistry, RuntimeLeaseToken


@pytest.mark.parametrize('case', ['no-interrupt', 'multiple-interrupts', 'no-next', 'nested', 'errored',
                                  'free-form', 'batch', 'mismatched-review', 'allow-always', 'missing-args'])
def test_malformed_or_uncovered_interrupt_unit_boundary(case):
    item = SimpleNamespace(id='interrupt-one', value={
        'action_requests': [{'name': 'write_report', 'args': {'text': 'private'}}],
        'review_configs': [{'action_name': 'write_report', 'allowed_decisions': ['approve', 'reject']}]})
    task = SimpleNamespace(state=None, error=None, interrupts=(item,))
    snapshot = SimpleNamespace(interrupts=(item,), next=('tools',), tasks=(task,))
    if case == 'no-interrupt':
        snapshot.interrupts = ()
    elif case == 'multiple-interrupts':
        snapshot.interrupts = (item, item)
    elif case == 'no-next':
        snapshot.next = ()
    elif case == 'nested':
        task.state = {'configurable': {'checkpoint_ns': 'child'}}
    elif case == 'errored':
        task.error = 'error'
    elif case == 'free-form':
        item.value = 'Please approve'
    elif case == 'batch':
        item.value['action_requests'] *= 2
    elif case == 'mismatched-review':
        item.value['review_configs'][0]['action_name'] = 'another'
    elif case == 'allow-always':
        item.value['review_configs'][0]['allowed_decisions'] = ['approve']
    else:
        del item.value['action_requests'][0]['args']
    native = LangGraphApprovalAdapter(None, {'configurable': {'thread_id': 's'}}, {
        'write_report': {'name': 'write_report', 'origin': 'runtime'}})
    with pytest.raises(NativeApprovalError, match='^native_approval_unavailable$'):
        native._action(snapshot)


def test_native_adapter_requires_live_runtime_lease(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.sqlite3'))
    lease = registry.acquire('runtime', 'owner', ttl=2, now=10.0)
    native = LangGraphApprovalAdapter(None, {'configurable': {'thread_id': 's'}}, {},
                                      lease_registry=registry,
                                      lease_token=RuntimeLeaseToken('runtime', 'owner', lease.fence),
                                      clock=lambda: 10.5)
    native._assert_runtime_lease()
    native.clock = lambda: 13.0
    with pytest.raises(NativeApprovalError, match='^runtime_lease_lost$'):
        native._assert_runtime_lease()


def test_native_adapter_rejects_malformed_lease_binding(tmp_path):
    registry = RuntimeLeaseRegistry(str(tmp_path / 'leases.sqlite3'))
    native = LangGraphApprovalAdapter(None, {'configurable': {'thread_id': 's'}}, {},
                                      lease_registry=registry, lease_token=None)
    with pytest.raises(NativeApprovalError, match='^runtime_lease_required$'):
        native._assert_runtime_lease()
