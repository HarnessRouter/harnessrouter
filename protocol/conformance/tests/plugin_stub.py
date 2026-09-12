"""A deliberately wrong UHP server, with one toggleable defect per rule in the Plugins chapter.

The P-series checks what a server DERIVES from a package, what it REFUSES, and what it leaves
out of an export. A check that only ever passes proves nothing about any of that, so this stub
implements the Plugins chapter in memory, correctly by default, and takes a DEFECT environment
variable naming one thing to get wrong. test_plugin_checks.py drives it once per defect and
asserts the diagonal: each defect is caught by the check that claims to cover it, and by no other.

No task is ever run: every P- check is configuration, so the stub needs no credentials, no
network and no agent tokens, and the matrix finishes in seconds.

    DEFECT=accepts_collision PORT=8932 python3 plugin_stub.py
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFECT = os.environ.get("DEFECT", "none")
PORT = int(os.environ.get("PORT", "8932"))
KEY = "stub-key"
VERSION = "2026-09-12"
MANIFEST_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
NAME_RE = re.compile(r"^(?!.*(--|\.\.))[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")

DEFECTS = {
    "none",
    "no_plugin_schemas",        # capability true, but the schema list is missing
    "copies_into_direct",       # the harness's own mcpServers absorb the plugin's
    "files_endpoint_partial",   # the files endpoint returns plugin.json alone
    "expands_placeholders",     # ${PLUGIN_DATA} comes back as a sandbox path
    "accepts_no_manifest",      # a package with no plugin.json installs
    "accepts_collision",        # a plugin server named like the harness's own installs
    "loses_files_on_rename",    # PUT keeps only the first file of each package
    "export_leaks_credentials", # the export carries auth and headers
    "export_unrecorded",        # the export omits credentials and says nothing
    "drops_invalid_silently",   # an invalid mcp.json entry vanishes with no skipped record
    "enabled_not_preserved",    # enabled: false is stored as true
    "accepts_unknown_schema",   # a manifest for an unknown Agent Plugins version installs
    "accepts_duplicate_name",   # two plugins with one name install side by side
}
assert DEFECT in DEFECTS, f"unknown defect {DEFECT!r}; one of {sorted(DEFECTS)}"

HARNESSES: dict[str, dict] = {}


class Refuse(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail


# ── the Plugins chapter, in memory ────────────────────────────────────────────────────────
def check_path(path) -> str:
    if not isinstance(path, str) or not path or path.startswith("/"):
        raise Refuse(422, "plugin_invalid", "bad file path", {"path": path, "reason": "not relative"})
    parts = path.split("/")
    if any(seg in ("", ".", "..") for seg in parts):
        raise Refuse(422, "plugin_invalid", "path escapes the plugin root",
                     {"path": path, "reason": "escapes the root"})
    return path


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---", text, flags=re.S)
    out = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def load_package(item: dict) -> dict:
    """Read a package as an Agent Plugins client would. Returns the derived plugin object."""
    files = item.get("files") or []
    if not isinstance(files, list) or not files:
        raise Refuse(422, "plugin_invalid", "a plugin needs files", {"path": "", "reason": "no files"})
    by_path = {check_path(f.get("path")): f for f in files}
    skipped: list[dict] = []

    raw = by_path.get("plugin.json")
    if raw is None:
        if DEFECT == "accepts_no_manifest":
            manifest = {"$schema": MANIFEST_SCHEMA, "name": "unnamed"}
        else:
            raise Refuse(422, "plugin_invalid", "no plugin.json at the root",
                         {"path": "plugin.json", "reason": "missing"})
    else:
        try:
            manifest = json.loads(raw.get("content") or "")
        except Exception:
            raise Refuse(422, "plugin_invalid", "plugin.json is not JSON",
                         {"path": "plugin.json", "reason": "not JSON"})
    if not isinstance(manifest, dict):
        raise Refuse(422, "plugin_invalid", "plugin.json is not an object",
                     {"path": "plugin.json", "reason": "not an object"})
    if manifest.get("$schema") != MANIFEST_SCHEMA and DEFECT != "accepts_unknown_schema":
        raise Refuse(422, "unsupported_plugin_schema", "unsupported Agent Plugins version",
                     {"supported": [MANIFEST_SCHEMA]})
    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise Refuse(422, "plugin_invalid", "manifest name is invalid",
                     {"path": "plugin.json#/name", "reason": "does not satisfy §5.5"})
    known = {"$schema", "name", "version", "description", "author", "homepage", "repository",
             "license", "keywords", "extensions"}
    for k in manifest:
        if k not in known:
            skipped.append({"path": f"plugin.json#/{k}", "reason": "unknown top-level field"})
    if item.get("name") not in (None, name):
        raise Refuse(422, "plugin_invalid", "name contradicts the manifest",
                     {"path": "plugin.json#/name", "reason": f"sent {item.get('name')!r}"})

    servers: list[dict] = []
    raw = by_path.get("mcp.json")
    if raw is not None:
        try:
            mcp = json.loads(raw.get("content") or "")
        except Exception:
            mcp = None
        entries = (mcp or {}).get("mcpServers") if isinstance(mcp, dict) else None
        if not isinstance(mcp, dict) or mcp.get("$schema") != MCP_SCHEMA or not isinstance(entries, dict):
            skipped.append({"path": "mcp.json", "reason": "not a valid Agent Plugins 1.0.0 mcp.json"})
            entries = {}
        for sname, cfg in entries.items():
            cfg = cfg if isinstance(cfg, dict) else {}
            t = cfg.get("type")
            allowed = {"stdio": {"type", "command", "args", "env", "cwd"},
                       "streamable-http": {"type", "url", "headers"},
                       "sse": {"type", "url", "headers"}}.get(t)
            ok = allowed is not None and set(cfg) <= allowed and (
                isinstance(cfg.get("command"), str) if t == "stdio" else isinstance(cfg.get("url"), str))
            if not ok:
                if DEFECT != "drops_invalid_silently":
                    skipped.append({"path": f"mcp.json#/mcpServers/{sname}",
                                    "reason": f"not a valid server entry (type {t!r})"})
                continue
            s = {"name": sname, "enabled": True}
            if t == "stdio":
                s.update({"transport": "stdio", "command": cfg["command"]})
                for k in ("args", "env", "cwd"):
                    if k in cfg:
                        s[k] = cfg[k]
                if DEFECT == "expands_placeholders":
                    s["args"] = [a.replace("${PLUGIN_DATA}", "/sandbox/plugin-data") for a in s.get("args", [])]
            else:
                s.update({"transport": "http" if t == "streamable-http" else "sse", "url": cfg["url"]})
                if "headers" in cfg:
                    s["headers"] = cfg["headers"]
            servers.append(s)

    skills: list[dict] = []
    dirs = sorted({p.split("/")[1] for p in by_path if p.startswith("skills/") and p.count("/") >= 2})
    for d in dirs:
        md = by_path.get(f"skills/{d}/SKILL.md")
        if md is None:
            continue                                   # not a skill, per Agent Plugins §7.1
        fm = frontmatter(md.get("content") or "")
        if fm.get("name") != d or not fm.get("description"):
            skipped.append({"path": f"skills/{d}", "reason": "SKILL.md does not conform to Agent Skills"})
            continue
        skills.append({"name": d, "description": fm["description"]})

    enabled = item.get("enabled", True) is not False
    if DEFECT == "enabled_not_preserved":
        enabled = True
    return {"name": name, "enabled": enabled, "manifest": manifest, "mcpServers": servers,
            "skills": skills, "skipped": skipped, "files": files}


def build_harness(body: dict, existing: dict | None = None) -> dict:
    base = body.get("base")
    if base != "stub":
        raise Refuse(422, "unsupported_base", "unsupported base", {"supported": ["stub"]})
    skills = []
    for s in body.get("skills") or []:
        files = s.get("files") or ([{"path": "SKILL.md", "content": s["content"]}] if s.get("content") else [])
        if not any(f.get("path") == "SKILL.md" for f in files):
            raise Refuse(422, "invalid_input", "a skill needs a SKILL.md")
        skills.append({"name": s.get("name"), "enabled": s.get("enabled", True) is not False, "files": files})
    plugins = [load_package(p) for p in body.get("plugins") or []]
    if existing and DEFECT == "loses_files_on_rename":
        for p in plugins:
            p["files"] = p["files"][:1]

    seen: dict[str, str] = {}
    for p in plugins:
        if p["name"] in seen and DEFECT != "accepts_duplicate_name":
            raise Refuse(409, "plugin_conflict", "two plugins share a name",
                         {"component": "plugin", "name": p["name"], "between": [p["name"], p["name"]]})
        seen[p["name"]] = "plugin"
    for component, direct, key in (("mcp_server", body.get("mcp_servers") or [], "mcpServers"),
                                   ("skill", skills, "skills")):
        owners: dict[str, str] = {d.get("name"): "harness" for d in direct if d.get("enabled", True) is not False}
        for p in plugins:
            if not p["enabled"]:
                continue
            for c in p[key]:
                if c["name"] in owners and DEFECT != "accepts_collision":
                    raise Refuse(409, "plugin_conflict", f"{component} name collides",
                                 {"component": component, "name": c["name"],
                                  "between": [owners[c["name"]], p["name"]]})
                owners[c["name"]] = p["name"]
    return {"id": (existing or {}).get("id") or f"chrn_{uuid.uuid4().hex}", "name": body.get("name") or "",
            "base": base, "mcp_servers": body.get("mcp_servers") or [], "skills": skills,
            "plugins": plugins, "disabled_tools": body.get("disabled_tools") or [],
            "created_at": (existing or {}).get("created_at") or int(time.time() * 1000)}


def out(h: dict) -> dict:
    servers = list(h["mcp_servers"])
    if DEFECT == "copies_into_direct":
        for p in h["plugins"]:
            servers += p["mcpServers"]
    return {"id": h["id"], "object": "harness", "name": h["name"], "base": h["base"],
            "mcpServers": servers, "skills": h["skills"], "plugins": h["plugins"],
            "disabledTools": h["disabled_tools"], "createdAt": h["created_at"]}


def plugin_name_of(h: dict) -> str:
    n = re.sub(r"[^a-z0-9.]+", "-", h["name"].lower()).strip("-")
    n = re.sub(r"\.{2,}", ".", n).strip(".")
    if not NAME_RE.match(n):
        n = re.sub(r"[^a-z0-9.]+", "-", h["id"].lower()).strip("-")
    return n


def export(h: dict) -> dict:
    files = [{"path": "plugin.json", "content": json.dumps({"$schema": MANIFEST_SCHEMA, "name": plugin_name_of(h)})}]
    skipped = []
    entries = {}
    for s in h["mcp_servers"]:
        if s.get("enabled", True) is False:
            continue
        t = s.get("transport") or "http"
        if t == "stdio":
            e = {"type": "stdio", "command": s.get("command")}
            for k in ("args", "env", "cwd"):
                if k in s:
                    e[k] = s[k]
        else:
            e = {"type": "streamable-http" if t == "http" else "sse", "url": s.get("url")}
            for k in ("auth", "headers"):
                if k in s:
                    if DEFECT == "export_leaks_credentials":
                        e[k] = s[k]
                    elif DEFECT != "export_unrecorded":
                        skipped.append({"path": f"mcp.json#/mcpServers/{s['name']}/{k}",
                                        "reason": "credentials are not exported"})
        entries[s["name"]] = e
    if entries:
        files.append({"path": "mcp.json", "content": json.dumps({"$schema": MCP_SCHEMA, "mcpServers": entries})})
    for sk in h["skills"]:
        if not sk["enabled"]:
            continue
        for f in sk["files"]:
            files.append({**f, "path": f"skills/{sk['name']}/{f['path']}"})
    return load_package({"files": files}) | {"skipped": skipped}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quiet
        pass

    def send(self, status: int, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("uhp-version", VERSION)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def refuse(self, e: Refuse):
        err = {"type": "invalid_request_error", "code": e.code, "message": e.message,
               "param": None, "detail": e.detail}
        return self.send(e.status, {"error": err})

    def authed(self) -> bool:
        return (self.headers.get("authorization") or "").removeprefix("Bearer ").strip() == KEY

    def read_body(self) -> dict:
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def path_parts(self):
        return [p for p in urlsplit(self.path).path.split("/") if p]

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method: str):
        body = self.read_body()
        p = self.path_parts()
        if method == "GET" and p == ["v1", "uhp"]:
            d = {"object": "uhp.discovery", "protocol": "uhp", "versions": [VERSION],
                 "default_version": VERSION, "conformance_class": "full",
                 "capabilities": {"streaming": True, "sessions": True, "cancellation": True,
                                  "files_input": True, "files_output": True, "session_listing": True,
                                  "harness_management": True, "plugins": True},
                 "plugin_schemas": [MANIFEST_SCHEMA]}
            if DEFECT == "no_plugin_schemas":
                d.pop("plugin_schemas")
            return self.send(200, d)
        if not self.authed():
            return self.send(401, {"error": {"type": "authentication_error", "code": "missing_credential",
                                             "message": "no credential", "param": None, "detail": None}})
        try:
            if p[:2] != ["v1", "harnesses"]:
                raise Refuse(404, "not_found", "no such endpoint")
            if method == "GET" and len(p) == 2:
                return self.send(200, {"harnesses": [out(h) for h in HARNESSES.values()]})
            if method == "POST" and len(p) == 2:
                h = build_harness(body)
                HARNESSES[h["id"]] = h
                return self.send(200, out(h))
            h = HARNESSES.get(p[2]) if len(p) >= 3 else None
            if h is None:
                raise Refuse(404, "harness_not_found", "no such harness")
            if method == "GET" and len(p) == 3:
                return self.send(200, out(h))
            if method == "PUT" and len(p) == 3:
                HARNESSES[h["id"]] = build_harness({**body, "base": h["base"]}, existing=h)
                return self.send(200, out(HARNESSES[h["id"]]))
            if method == "DELETE" and len(p) == 3:
                HARNESSES.pop(h["id"], None)
                return self.send(200, {"id": h["id"], "deleted": True})
            if method == "GET" and len(p) == 4 and p[3] == "plugin":
                return self.send(200, export(h))
            if method == "GET" and len(p) == 6 and p[3] in ("plugins", "skills") and p[5] == "files":
                items = h["plugins"] if p[3] == "plugins" else h["skills"]
                hit = next((i for i in items if i["name"] == p[4]), None)
                if hit is None:
                    raise Refuse(404, "plugin_not_found" if p[3] == "plugins" else "invalid_input", "no such item")
                files = hit["files"]
                if DEFECT == "files_endpoint_partial" and p[3] == "plugins":
                    files = [f for f in files if f["path"] == "plugin.json"]
                return self.send(200, {"files": files})
            raise Refuse(404, "not_found", "no such endpoint")
        except Refuse as e:
            return self.refuse(e)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
