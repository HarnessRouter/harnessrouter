"""What Mem0 links inside itself, read only, so a memory's graph can be drawn (HarnessRouter, deploy/memories/mem0).

Mem0 links each fact it extracts to the names, quoted titles and topics in it: an entity store whose rows carry the
text, its kind and `linked_memory_ids`, and which its search uses to rank. No route of Mem0's own serves it (its
/entities lists users, agents and runs). This one lists a scope's entities and the facts each is linked to.
"""
from __future__ import annotations

from typing import Optional

from auth import verify_auth
from fastapi import APIRouter, Depends, Query
from server_state import get_memory_instance

router = APIRouter(prefix="/hr", tags=["harnessrouter"])


@router.get("/entities", summary="A scope's entities and the memories each is linked to")
def linked_entities(user_id: str = Query(...), agent_id: Optional[str] = Query(None), _auth=Depends(verify_auth)) -> list[dict]:
    filters = {"user_id": user_id, **({"agent_id": agent_id} if agent_id else {})}
    rows = get_memory_instance().entity_store.list(filters=filters, top_k=10000)
    rows = rows[0] if rows and isinstance(rows[0], list) else rows or []
    out = []
    for r in rows:
        p = getattr(r, "payload", None) or {}
        out.append({"id": str(getattr(r, "id", "")), "text": str(p.get("data") or ""), "kind": str(p.get("entity_type") or ""),
                    "memory_ids": [str(x) for x in p.get("linked_memory_ids") or []]})
    return out
