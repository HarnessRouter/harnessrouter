"""What changes in a memory, told to whoever has it open, as it happens.

A record changes when a person edits it, when an agent calls a tool, when a turn is observed, and when a
provider finishes deriving. Each of those has its own caller, and all of them reach the provider through
`provider_of`. So the telling is one thin wrapper there (`Announced`) and no writer has to remember it.

An event names what changed and who changed it, never what it now says: a reader reads the record, under
its own privileges, the way any read goes. A reconnecting reader names the last event it saw and gets what
it missed; one that was away too long is told `reset` and reads everything again.

One process holds the channels, as one process holds the sessions. Nothing here survives a restart, and
nothing needs to: every client reads again when it reconnects.

A memory kept for one person of an agent's (memory_plane.end_user_node) sits below the agent's memory, and that is
the memory a person watching the agent has open. So a change to a person's memory is told on the agent's memory too,
as `records.changed` with no record and no person named (`below: true`): that something below changed, so a reader
reads again under its own privileges, which never reach a person's memory it may not read.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import AsyncIterator

log = logging.getLogger("memory_live")

_KEPT = 256             # events a channel keeps for a reader that reconnects
_BEHIND = 256           # events a reader may fall behind by before it is told to read everything again
_JOB_MAX_S = 900        # a provider's job watched this long, then left for the next read to find
_JOBS_MAX = 64          # jobs watched at once
_SETTLED = ("completed", "failed")


class _Channel:
    __slots__ = ("seq", "kept", "readers")

    def __init__(self) -> None:
        self.seq = 0
        self.kept: collections.deque = collections.deque(maxlen=_KEPT)
        self.readers: set[asyncio.Queue] = set()


_channels: dict[str, _Channel] = {}
_jobs: dict[str, asyncio.Task] = {}


def _channel(mid: str) -> _Channel:
    ch = _channels.get(mid)
    if ch is None:
        ch = _channels[mid] = _Channel()
    return ch


def publish(mid: str, kind: str, **fields) -> None:
    """Tell a memory's readers. Never raises and never waits: a write has already happened."""
    try:
        ch = _channel(mid)
        ch.seq += 1
        event = {"id": ch.seq, "type": kind, "memory_id": mid, "at": time.time(), **fields}
        ch.kept.append(event)
        for q in list(ch.readers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # too far behind to catch up one by one: it reads everything again, and hears what comes after
                _drain(q)
                q.put_nowait({"id": ch.seq, "type": "reset", "memory_id": mid, "at": time.time()})
    except Exception as e:  # noqa: BLE001
        log.warning("memory event not told: %s", type(e).__name__)


def tell(mid: str, kind: str, above=(), **fields) -> None:
    """`publish` on this memory, and on each memory `above` it that hears of what changes below (a person's memory,
    the agent's): there, only that something below changed, never which record or whose."""
    publish(mid, kind, **fields)
    for up in above or ():
        if up and up != mid:
            publish(up, "records.changed", record_ids=[], below=True)


def _drain(q: asyncio.Queue) -> None:
    while not q.empty():
        q.get_nowait()


async def stream(mid: str, after: int | None, tick: float = 15.0) -> AsyncIterator[dict | None]:
    """A memory's events from here on, after the ones a reconnecting reader missed. `None` every `tick`
    seconds with nothing to say: the caller's moment to keep the connection open and check the reader."""
    ch = _channel(mid)
    q: asyncio.Queue = asyncio.Queue(maxsize=_BEHIND)
    ch.readers.add(q)
    try:
        if after is not None:
            oldest = ch.kept[0]["id"] if ch.kept else ch.seq + 1
            if after > ch.seq or after < oldest - 1:
                # this process doesn't know that place: it restarted, or the reader was away too long
                if after != ch.seq:
                    yield {"id": ch.seq, "type": "reset", "memory_id": mid, "at": time.time()}
            else:
                for ev in list(ch.kept):
                    if ev["id"] > after:
                        yield ev
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=tick)
            except asyncio.TimeoutError:
                yield None
                continue
            yield ev
    finally:
        ch.readers.discard(q)
        if not ch.readers and not ch.kept:
            _channels.pop(mid, None)


def readers(mid: str) -> int:
    ch = _channels.get(mid)
    return len(ch.readers) if ch else 0


async def _watch_job(prov, mid: str, job_id: str, above=()) -> None:
    """A provider that derives after it answers has nobody to tell when it's done, so it's asked, and only
    while someone has the memory open (or a memory above that hears of it): a job nobody is waiting for costs the
    provider nothing."""
    end = time.monotonic() + _JOB_MAX_S
    wait = 1.0
    try:
        while time.monotonic() < end:
            await asyncio.sleep(wait)
            wait = min(wait * 1.6, 15.0)
            if not readers(mid) and not any(readers(up) for up in above or ()):
                continue
            try:
                job = await prov.job(mid, job_id)
            except Exception as e:  # noqa: BLE001
                log.info("job not read: %s", type(e).__name__)
                continue
            if not job:
                return
            if str(job.get("status")) in _SETTLED:
                tell(mid, "records.changed", above, record_ids=[str(r.get("id")) for r in job.get("records") or [] if r.get("id")],
                     job=job_id, status=str(job.get("status")))
                return
    finally:
        _jobs.pop(job_id, None)


def _watch(prov, mid: str, job: dict | None, above=()) -> None:
    job_id = str((job or {}).get("id") or "")
    if not job_id or job_id in _jobs or len(_jobs) >= _JOBS_MAX:
        return
    try:
        _jobs[job_id] = asyncio.get_running_loop().create_task(_watch_job(prov, mid, job_id, above))
    except RuntimeError:
        pass


class VersionMoved(Exception):
    """Someone else wrote since this writer read."""

    def __init__(self, version: int) -> None:
        super().__init__(f"the record is at version {version}")
        self.version = version


_locks: dict[tuple[str, str], list] = {}


class _record_lock:
    """A lock per record that exists only while someone holds or waits for it."""

    def __init__(self, mid: str, rid: str) -> None:
        self.key = (mid, rid)

    async def __aenter__(self):
        held = _locks.setdefault(self.key, [asyncio.Lock(), 0])
        held[1] += 1
        await held[0].acquire()

    async def __aexit__(self, *_):
        held = _locks[self.key]
        held[0].release()
        held[1] -= 1
        if not held[1]:
            del _locks[self.key]


class Announced:
    """A provider as its callers use it. Every write it answers is told to the memory's readers (and, for a
    person's memory, that something changed to the readers of the memory `above` it); everything else passes
    through untouched."""

    __slots__ = ("_p", "_above")

    def __init__(self, provider, above=()) -> None:
        self._p = provider
        self._above = tuple(x for x in above or () if x)

    def __getattr__(self, name):
        return getattr(self._p, name)

    async def bind(self, org: str, workspace: str):
        return Announced(await self._p.bind(org, workspace))

    async def remember(self, mid, record, writer):
        made = await self._p.remember(mid, record, writer)
        tell(mid, "record.created", self._above, record_id=str(made.get("id") or ""), version=made.get("version"), written_by=writer)
        return made

    async def revise(self, mid, rid, patch, writer, expected: int | None = None):
        """One writer at a time on one record, and a writer that names the version it read is refused if that isn't
        the version any more. A provider keeps what it was told last: without this, two writers crossing on a provider
        that takes seconds to answer lose whichever one lands first, and nobody hears about it."""
        async with _record_lock(mid, rid):
            if expected is not None:
                cur = await self._p.get(mid, rid)
                have = (cur or {}).get("version")
                if cur is not None and have is not None and int(have) != int(expected):
                    raise VersionMoved(int(have))
            made = await self._p.revise(mid, rid, patch, writer)
        tell(mid, "record.revised", self._above, record_id=str(made.get("id") or rid), version=made.get("version"), written_by=writer,
             fields=sorted(patch))
        return made

    async def forget(self, mid, rid, writer):
        out = await self._p.forget(mid, rid, writer)
        tell(mid, "record.forgotten", self._above, record_id=rid, written_by=writer)
        return out

    async def close_episode(self, mid, rid, writer):
        out = await self._p.close_episode(mid, rid, writer)
        tell(mid, "record.forgotten", self._above, record_id=rid, written_by=writer)
        return out

    async def erase(self, mid, rids):
        out = await self._p.erase(mid, rids)
        tell(mid, "records.erased", self._above, record_ids=[str(x) for x in rids])
        return out

    async def observe(self, mid, episodes, writer):
        made = await self._p.observe(mid, episodes, writer)
        job = made.get("job")
        tell(mid, "records.changed", self._above, record_ids=[str(r.get("id")) for r in made.get("records") or [] if r.get("id")],
             written_by=writer, **({"job": str(job.get("id")), "status": str(job.get("status"))} if job else {}))
        if job:
            _watch(self._p, mid, job, self._above)
        return made

    async def operate(self, mid, rid, name, body, writer):
        out = await self._p.operate(mid, rid, name, body, writer)
        tell(mid, "record.revised", self._above, record_id=rid, written_by=writer, fields=["operation"])
        return out

    async def consolidate(self, mid, budget, why):
        out = await self._p.consolidate(mid, budget, why)
        tell(mid, "records.changed", self._above, record_ids=[])
        return out

    async def revert_consolidation(self, mid, run, writer):
        out = await self._p.revert_consolidation(mid, run, writer)
        tell(mid, "records.changed", self._above, record_ids=[], written_by=writer)
        return out
