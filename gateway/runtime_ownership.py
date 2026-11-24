"""Internal ownership coordinator for trusted native continuations.

The transport must use the deployment's authenticated Runner route. No public
request chooses a transport, Runtime owner or executable callback. This module
does not register a backend or enable the UHP tool_approvals capability.
"""
import asyncio
import contextlib
import math
import time
import uuid


class OwnershipError(RuntimeError):
    """Stable diagnostics without transport/credential/native payloads."""


class RuntimeOwnership:
    def __init__(self, transport, *, ttl=30.0, clock=time.time):
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 86400:
            raise OwnershipError('runtime_lease_invalid')
        self.transport, self.ttl, self.clock = transport, ttl, clock

    def _validate(self, value, runtime, owner, fence=None, *, released=False, idle=False):
        if (not isinstance(value, dict) or value.get('runtime_id') != runtime
                or value.get('owner') != (None if released else owner)
                or type(value.get('fence')) is not int or value['fence'] < 1
                or (fence is not None and value['fence'] != fence)
                or not {'execution_id', 'execution_state'} <= value.keys()):
            raise OwnershipError('runtime_lease_unavailable')
        if released:
            if value.get('heartbeat_at') is not None or value.get('expires_at') is not None:
                raise OwnershipError('runtime_lease_unavailable')
        else:
            for key in ('heartbeat_at', 'expires_at'):
                if type(value.get(key)) not in (int, float) or not math.isfinite(value[key]):
                    raise OwnershipError('runtime_lease_unavailable')
            if not value['heartbeat_at'] < value['expires_at'] or value['expires_at'] <= self.clock():
                raise OwnershipError('runtime_lease_unavailable')
        operation, state = value['execution_id'], value['execution_state']
        if ((operation is None) != (state is None)
                or (operation is not None and (not isinstance(operation, str) or not operation
                                               or state != 'active'))
                or ((idle or released) and operation is not None)):
            raise OwnershipError('runtime_lease_unavailable')
        return dict(value)

    async def _call(self, action, sid, body):
        try:
            # The deadline also bounds a heartbeat blocked behind an unavailable
            # Runner. The generic sandbox transport's long retry ladder is not
            # appropriate for a permission-relevant lease.
            return await asyncio.wait_for(self.transport('/internal/runtime-leases/' + action,
                sid, method='POST', body=body), timeout=self.ttl / 3)
        except Exception:
            raise OwnershipError('runtime_lease_unavailable') from None

    async def run(self, sid, runtime_id, operation):
        if any(not isinstance(value, str) or not 1 <= len(value) <= 1024 for value in (sid, runtime_id)):
            raise OwnershipError('runtime_lease_invalid')
        owner = 'owner_' + uuid.uuid4().hex
        body = {'runtime_id': runtime_id, 'owner': owner, 'ttl_seconds': self.ttl}
        acquired = self._validate(await self._call('acquire', sid, body), runtime_id, owner, idle=True)
        fence = acquired['fence']
        token = {'runtime_id': runtime_id, 'owner': owner, 'fence': fence}
        body = {**body, 'fence': fence}

        async def heartbeat():
            while True:
                await asyncio.sleep(self.ttl / 3)
                self._validate(await self._call('renew', sid, body), runtime_id, owner, fence)

        async def invoke():
            return await operation(dict(token))

        work = asyncio.create_task(invoke())
        monitor = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait((work, monitor), return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                # The gate around the callback is responsible for durable
                # unknown. Cancellation is not proof that native work stopped.
                raise OwnershipError('runtime_lease_lost')
            result = await work
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
            self._validate(await self._call('renew', sid, body), runtime_id, owner, fence, idle=True)
            self._validate(await self._call('release', sid, body), runtime_id, owner, fence, released=True)
            return result
        finally:
            # No release on an uncertain/failed invocation. An execution pin
            # outlives these tasks and cannot be cleared by TTL or cancellation.
            for task in (work, monitor):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, monitor, return_exceptions=True)
