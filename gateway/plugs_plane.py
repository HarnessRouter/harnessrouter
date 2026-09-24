"""Plugs: the vendor tools an agent reaches through the `plugs` MCP server this gateway hosts.

A plug is a service connected once for a workspace (its GitHub repository, its Vercel project, its
InsForge backend). The registry on the engine mints and keeps the per-workspace credential; this
module is the tool surface over it: what tools each plug type offers, with the risk of each, and
how one call maps onto the vendor's API. The credential arrives as `fields` resolved by the caller
(app.py, from the org vault) at the moment of the call, is used in process, and is never returned:
every tool answers data, never the token that fetched it.

Tool names are the vendor's own where a vendor MCP server exists (GitHub's, verbatim), so an agent
package written against the vendor's server works unchanged under `github.<name>`. Vercel and
InsForge have no vendor MCP server; their surfaces are the operations a company's agents need with
a project-scoped credential, on routes verified against the live services. Nothing here creates or
deletes the tenancy itself (a repository, a project): that is the provisioner's, and a plug's
credential is scoped so it could not anyway.

Risk hints ride on every tool: `read` answers without changing anything, `write` changes the
company's own resources, `destructive` is hard to undo (a delete, a merge, a push to a shared
branch). They reach the agent as MCP tool annotations and the audit row as a column.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx

GITHUB_API = "https://api.github.com"
VERCEL_API = "https://api.vercel.com"
CALL_TIMEOUT_S = 60            # one vendor request
DEPLOY_WAIT_S = 120            # how long deploy_from_repo watches a deployment before handing back
DEPLOY_POLL_S = 5
TEXT_CAP = 200_000             # the most text one tool result carries back to the agent

# Tests set an httpx transport here so every vendor call is exercised and nothing is spent.
transport: httpx.BaseTransport | None = None


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=CALL_TIMEOUT_S, transport=transport, follow_redirects=True)


class PlugToolError(RuntimeError):
    """The vendor refused or the arguments do not make a call; the message is for the agent."""


# ── the registry of tools ─────────────────────────────────────────────────────────────────────
# One plug type answers under its own name; an alias shares another's tools (the OAuth-consent
# GitHub plug carries the same `token` field as the provisioned one).
TYPES: dict[str, str] = {"github": "GitHub", "github_app": "GitHub", "vercel": "Vercel", "insforge": "InsForge",
                         "browser": "Browser"}
BROWSER = "browser"     # a platform plug: no customer credential; served by the gateway's browser plane
OPEN_TYPES = {BROWSER}   # open to every org (Richard, 2026-09-24); the rest are held to HR_PLUGS_ORGS while verified
_ALIAS = {"github_app": "github"}
RISKS = ("read", "write", "destructive")
_TOOLS: dict[str, list[dict]] = {}


def _tool(plug: str, name: str, risk: str, description: str, schema: dict):
    assert risk in RISKS
    if plug == "github":
        # An OAuth-consent GitHub plug may cover several repositories; every tool then takes the one
        # it means. A provisioned plug covers one and the argument is not needed.
        schema["properties"].setdefault("repo", _s("Repository as owner/name, when the plug covers several; "
                                                   "the plug's own repository when omitted"))
    def deco(fn):
        _TOOLS.setdefault(plug, []).append({"name": name, "risk": risk, "description": description,
                                            "inputSchema": schema, "fn": fn})
        return fn
    return deco


# The GitHub App permission each tool needs. A plug whose installation was not granted one says so
# on its record (config.permissions_missing), and the refusal names the grant rather than a 403.
_GITHUB_PERMISSION = {
    **{t: "contents" for t in ("get_repo", "get_file_contents", "list_branches", "list_commits", "get_commit",
                               "search_code", "create_or_update_file", "push_files", "create_branch", "delete_file")},
    **{t: "issues" for t in ("list_issues", "get_issue", "get_issue_comments", "search_issues", "create_issue",
                             "update_issue", "add_issue_comment")},
    **{t: "pull_requests" for t in ("list_pull_requests", "get_pull_request", "get_pull_request_files",
                                    "get_pull_request_diff", "create_pull_request", "update_pull_request",
                                    "create_pull_request_review", "merge_pull_request")},
    **{t: "actions" for t in ("list_workflows", "list_workflow_runs", "get_workflow_run", "get_job_logs",
                              "run_workflow", "rerun_workflow_run", "cancel_workflow_run")},
}


def permission_of(plug: str, name: str) -> str | None:
    """The vendor permission a tool needs, where the plug type records grants; None otherwise."""
    return _GITHUB_PERMISSION.get(name) if _ALIAS.get(plug, plug) == "github" else None


def _obj(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _s(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def _i(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def _b(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


def tools_of(plug: str) -> list[dict]:
    return list(_TOOLS.get(_ALIAS.get(plug, plug), []))


def tool_list(plugs: list[str], enabled: dict | None = None) -> list[dict]:
    """MCP tool descriptors for the plugs a harness is bound to, `<plug>.<tool>` each, narrowed to
    the names `enabled` lists for a plug when it lists any."""
    out = []
    for plug in plugs:
        allow = (enabled or {}).get(plug)
        for t in tools_of(plug):
            if allow is not None and t["name"] not in allow:
                continue
            out.append({"name": f"{plug}.{t['name']}",
                        "description": f"[{TYPES.get(plug, plug)}, {t['risk']}] {t['description']}",
                        "inputSchema": t["inputSchema"],
                        "annotations": {"readOnlyHint": t["risk"] == "read",
                                        "destructiveHint": t["risk"] == "destructive"}})
    return out


def find(plug: str, name: str) -> dict | None:
    return next((t for t in tools_of(plug) if t["name"] == name), None)


async def call(plug: str, name: str, args: dict, fields: dict, config: dict) -> str:
    """Run one tool and answer its result as text for the agent. Raises PlugToolError with the
    vendor's own sentence when the vendor refuses."""
    t = find(plug, name)
    if t is None:
        raise PlugToolError(f"No tool named {plug}.{name} on this server.")
    if not isinstance(args, dict):
        raise PlugToolError("arguments must be an object")
    async with client() as c:
        out = await t["fn"](c, fields, config, args)
    text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
    if len(text) > TEXT_CAP:
        text = text[:TEXT_CAP] + f"\n…[{len(text) - TEXT_CAP} more characters not shown]"
    return text


def _pick(d, keys: tuple) -> dict:
    return {k: d.get(k) for k in keys if isinstance(d, dict) and d.get(k) is not None}


def _need(args: dict, key: str):
    v = args.get(key)
    if v is None or v == "":
        raise PlugToolError(f"{key} is required")
    return v


# ── GitHub: the company repository, through an installation token scoped to it ───────────────
def _gh_msg(r: httpx.Response) -> str:
    try:
        d = r.json()
        return str(d.get("message") or d)[:300] if isinstance(d, dict) else r.text[:300]
    except ValueError:
        return r.text[:300]


async def _gh(c: httpx.AsyncClient, fields: dict, method: str, path: str, *, body=None, params=None,
              accept: str = "application/vnd.github+json", text: bool = False):
    r = await c.request(method, GITHUB_API + path, json=body, params=params,
                        headers={"Authorization": f"Bearer {fields.get('token', '')}", "Accept": accept,
                                 "X-GitHub-Api-Version": "2022-11-28"})
    if r.status_code >= 400:
        raise PlugToolError(f"GitHub answered {r.status_code}: {_gh_msg(r)}")
    if text:
        return r.text
    return r.json() if r.content else {}


def _repo(config: dict, args: dict | None = None) -> str:
    """The repository a call addresses: the one asked for when the plug covers several (config.repos),
    else the plug's own (config.repo). Never one outside the plug."""
    repos = [r for r in (config.get("repos") or []) if isinstance(r, str)]
    own = str(config.get("repo") or "")
    want = str((args or {}).get("repo") or "")
    if want:
        if "/" not in want or want not in (repos or [own]):
            raise PlugToolError(f"the GitHub plug does not cover {want}; it covers "
                                + (", ".join(repos[:20]) if repos else (own or "no repository")))
        return want
    if "/" in own:
        return own
    if repos:
        raise PlugToolError("the GitHub plug covers several repositories; pass repo, one of " + ", ".join(repos[:20]))
    raise PlugToolError("the GitHub plug names no repository; reconnect it in the workspace's Plugs page")


def _branch(config: dict, args: dict, key: str = "branch") -> str:
    return str(args.get(key) or config.get("default_branch") or "main")


_ISSUE = ("number", "title", "state", "html_url", "created_at", "updated_at", "body")
_PULL = ("number", "title", "state", "html_url", "draft", "merged", "mergeable", "created_at", "updated_at", "body")
_COMMIT_KEYS = ("sha", "html_url")


def _user(d) -> str:
    return str(((d or {}).get("user") or {}).get("login") or "")


def _issue_out(d: dict) -> dict:
    return {**_pick(d, _ISSUE), "user": _user(d), "labels": [x.get("name") for x in d.get("labels") or [] if isinstance(x, dict)]}


def _pull_out(d: dict) -> dict:
    return {**_pick(d, _PULL), "user": _user(d), "head": (d.get("head") or {}).get("ref"),
            "base": (d.get("base") or {}).get("ref")}


def _commit_out(d: dict) -> dict:
    c = d.get("commit") or {}
    return {**_pick(d, _COMMIT_KEYS), "message": c.get("message"),
            "author": (c.get("author") or {}).get("name"), "date": (c.get("author") or {}).get("date")}


@_tool("github", "get_repo", "read", "The company repository: name, default branch, visibility, url.",
       _obj({}))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}")
    return _pick(d, ("full_name", "default_branch", "private", "html_url", "description", "pushed_at", "size", "open_issues_count"))


@_tool("github", "get_file_contents", "read",
       "Read a file (decoded text) or list a directory at a path, on a branch or commit.",
       _obj({"path": _s("File or directory path; empty for the repository root"),
             "ref": _s("Branch, tag or commit sha; the default branch when omitted")}, ("path",)))
async def _(c, f, cfg, a):
    path = str(a.get("path") or "").strip("/")
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/contents/{path}", params={"ref": a["ref"]} if a.get("ref") else None)
    if isinstance(d, list):
        return {"path": path, "entries": [_pick(e, ("name", "path", "type", "size", "sha")) for e in d]}
    if d.get("encoding") == "base64" and d.get("content") is not None:
        raw = base64.b64decode(d["content"])
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {**_pick(d, ("path", "sha", "size")), "binary": True}
        return {**_pick(d, ("path", "sha", "size")), "content": content}
    return _pick(d, ("path", "sha", "size", "type", "download_url"))


@_tool("github", "list_branches", "read", "Branches of the repository with their head commits.", _obj({}))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/branches", params={"per_page": 100})
    return [{"name": b.get("name"), "sha": (b.get("commit") or {}).get("sha"), "protected": b.get("protected")} for b in d]


@_tool("github", "list_commits", "read", "Recent commits, optionally on one branch or touching one path.",
       _obj({"sha": _s("Branch name or commit sha to start from"), "path": _s("Only commits touching this path"),
             "per_page": _i("How many, at most 100")}))
async def _(c, f, cfg, a):
    params = {k: a[k] for k in ("sha", "path") if a.get(k)}
    params["per_page"] = min(int(a.get("per_page") or 30), 100)
    return [_commit_out(x) for x in await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/commits", params=params)]


@_tool("github", "get_commit", "read", "One commit with the files it changed.", _obj({"sha": _s("Commit sha or ref")}, ("sha",)))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/commits/{_need(a, 'sha')}")
    return {**_commit_out(d), "stats": d.get("stats"),
            "files": [_pick(x, ("filename", "status", "additions", "deletions")) for x in d.get("files") or []]}


@_tool("github", "search_code", "read", "Search code in the repository (GitHub code search syntax).",
       _obj({"query": _s("Search terms; the repository qualifier is added for you")}, ("query",)))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", "/search/code", params={"q": f"{_need(a, 'query')} repo:{_repo(cfg, a)}", "per_page": 30})
    return {"total": d.get("total_count"), "items": [_pick(x, ("path", "sha", "html_url")) for x in d.get("items") or []]}


@_tool("github", "list_issues", "read", "Issues of the repository (pull requests excluded).",
       _obj({"state": _s("open, closed or all", enum=["open", "closed", "all"]), "labels": _s("Comma-separated label names"),
             "per_page": _i("How many, at most 100")}))
async def _(c, f, cfg, a):
    params = {k: a[k] for k in ("state", "labels") if a.get(k)}
    params["per_page"] = min(int(a.get("per_page") or 30), 100)
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/issues", params=params)
    return [_issue_out(x) for x in d if "pull_request" not in x]


@_tool("github", "get_issue", "read", "One issue.", _obj({"number": _i("Issue number")}, ("number",)))
async def _(c, f, cfg, a):
    return _issue_out(await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/issues/{int(_need(a, 'number'))}"))


@_tool("github", "get_issue_comments", "read", "Comments on an issue or pull request.",
       _obj({"number": _i("Issue or pull request number")}, ("number",)))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/issues/{int(_need(a, 'number'))}/comments", params={"per_page": 100})
    return [{**_pick(x, ("id", "body", "created_at", "html_url")), "user": _user(x)} for x in d]


@_tool("github", "search_issues", "read", "Search issues and pull requests in the repository.",
       _obj({"query": _s("Search terms; the repository qualifier is added for you")}, ("query",)))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", "/search/issues", params={"q": f"{_need(a, 'query')} repo:{_repo(cfg, a)}", "per_page": 30})
    return {"total": d.get("total_count"), "items": [_issue_out(x) for x in d.get("items") or []]}


@_tool("github", "list_pull_requests", "read", "Pull requests of the repository.",
       _obj({"state": _s("open, closed or all", enum=["open", "closed", "all"]), "per_page": _i("How many, at most 100")}))
async def _(c, f, cfg, a):
    params = {"state": a.get("state") or "open", "per_page": min(int(a.get("per_page") or 30), 100)}
    return [_pull_out(x) for x in await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/pulls", params=params)]


@_tool("github", "get_pull_request", "read", "One pull request.", _obj({"number": _i("Pull request number")}, ("number",)))
async def _(c, f, cfg, a):
    return _pull_out(await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/pulls/{int(_need(a, 'number'))}"))


@_tool("github", "get_pull_request_files", "read", "Files a pull request changes.",
       _obj({"number": _i("Pull request number")}, ("number",)))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/pulls/{int(_need(a, 'number'))}/files", params={"per_page": 100})
    return [_pick(x, ("filename", "status", "additions", "deletions", "patch")) for x in d]


@_tool("github", "get_pull_request_diff", "read", "The unified diff of a pull request.",
       _obj({"number": _i("Pull request number")}, ("number",)))
async def _(c, f, cfg, a):
    return await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/pulls/{int(_need(a, 'number'))}",
                     accept="application/vnd.github.diff", text=True)


@_tool("github", "list_workflows", "read", "GitHub Actions workflows of the repository.", _obj({}))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/actions/workflows")
    return [_pick(x, ("id", "name", "path", "state")) for x in d.get("workflows") or []]


@_tool("github", "list_workflow_runs", "read", "Recent workflow runs, for one workflow or all.",
       _obj({"workflow_id": _s("Workflow id or file name (ci.yml); all workflows when omitted"),
             "branch": _s("Only runs on this branch"), "per_page": _i("How many, at most 100")}))
async def _(c, f, cfg, a):
    params = {"per_page": min(int(a.get("per_page") or 20), 100)}
    if a.get("branch"):
        params["branch"] = a["branch"]
    path = (f"/repos/{_repo(cfg, a)}/actions/workflows/{a['workflow_id']}/runs" if a.get("workflow_id")
            else f"/repos/{_repo(cfg, a)}/actions/runs")
    d = await _gh(c, f, "GET", path, params=params)
    return [_pick(x, ("id", "name", "head_branch", "head_sha", "status", "conclusion", "html_url", "created_at", "run_number"))
            for x in d.get("workflow_runs") or []]


@_tool("github", "get_workflow_run", "read", "One workflow run with its jobs.", _obj({"run_id": _i("Run id")}, ("run_id",)))
async def _(c, f, cfg, a):
    rid = int(_need(a, "run_id"))
    d = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/actions/runs/{rid}")
    jobs = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/actions/runs/{rid}/jobs")
    return {**_pick(d, ("id", "name", "head_branch", "head_sha", "status", "conclusion", "html_url", "created_at", "updated_at")),
            "jobs": [_pick(j, ("id", "name", "status", "conclusion", "started_at", "completed_at")) for j in jobs.get("jobs") or []]}


@_tool("github", "get_job_logs", "read", "The log of one workflow job (the tail, when long).", _obj({"job_id": _i("Job id")}, ("job_id",)))
async def _(c, f, cfg, a):
    text = await _gh(c, f, "GET", f"/repos/{_repo(cfg, a)}/actions/jobs/{int(_need(a, 'job_id'))}/logs", accept="*/*", text=True)
    return text if len(text) <= 60_000 else "…" + text[-60_000:]


async def _gh_sha_of(c, f, repo: str, path: str, branch: str) -> str | None:
    r = await c.get(f"{GITHUB_API}/repos/{repo}/contents/{path}", params={"ref": branch},
                    headers={"Authorization": f"Bearer {f.get('token', '')}", "Accept": "application/vnd.github+json"})
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise PlugToolError(f"GitHub answered {r.status_code}: {_gh_msg(r)}")
    d = r.json()
    return d.get("sha") if isinstance(d, dict) else None


@_tool("github", "create_or_update_file", "write", "Create or update one file with a commit.",
       _obj({"path": _s("File path"), "content": _s("The whole file content (text)"),
             "message": _s("Commit message"), "branch": _s("Branch; the default branch when omitted"),
             "sha": _s("The file's current blob sha when updating; looked up when omitted")},
            ("path", "content", "message")))
async def _(c, f, cfg, a):
    repo, path, branch = _repo(cfg, a), str(_need(a, "path")).strip("/"), _branch(cfg, a)
    body = {"message": _need(a, "message"), "branch": branch,
            "content": base64.b64encode(str(a.get("content") or "").encode()).decode()}
    sha = a.get("sha") or await _gh_sha_of(c, f, repo, path, branch)
    if sha:
        body["sha"] = sha
    d = await _gh(c, f, "PUT", f"/repos/{repo}/contents/{path}", body=body)
    return {"path": path, "branch": branch, "sha": (d.get("content") or {}).get("sha"),
            "commit": (d.get("commit") or {}).get("sha"), "html_url": (d.get("content") or {}).get("html_url")}


@_tool("github", "push_files", "destructive", "Commit several files to a branch at once (one commit). Prefer a branch and a pull request over a shared branch.",
       _obj({"branch": _s("Branch to commit to"), "message": _s("Commit message"),
             "files": {"type": "array", "description": "Files to write", "items": _obj({"path": _s("File path"), "content": _s("Whole file content")}, ("path", "content"))}},
            ("branch", "message", "files")))
async def _(c, f, cfg, a):
    repo, branch = _repo(cfg, a), str(_need(a, "branch"))
    files = a.get("files") or []
    if not files:
        raise PlugToolError("files is empty")
    ref = await _gh(c, f, "GET", f"/repos/{repo}/git/ref/heads/{branch}")
    head = (ref.get("object") or {}).get("sha")
    base = await _gh(c, f, "GET", f"/repos/{repo}/git/commits/{head}")
    tree = await _gh(c, f, "POST", f"/repos/{repo}/git/trees", body={
        "base_tree": (base.get("tree") or {}).get("sha"),
        "tree": [{"path": str(x["path"]).strip("/"), "mode": "100644", "type": "blob", "content": str(x.get("content") or "")}
                 for x in files]})
    commit = await _gh(c, f, "POST", f"/repos/{repo}/git/commits",
                       body={"message": _need(a, "message"), "tree": tree.get("sha"), "parents": [head]})
    await _gh(c, f, "PATCH", f"/repos/{repo}/git/refs/heads/{branch}", body={"sha": commit.get("sha")})
    return {"branch": branch, "commit": commit.get("sha"), "files": len(files)}


@_tool("github", "create_branch", "write", "Create a branch from another branch (the default branch when not named).",
       _obj({"branch": _s("New branch name"), "from_branch": _s("Branch to start from")}, ("branch",)))
async def _(c, f, cfg, a):
    repo, name = _repo(cfg, a), str(_need(a, "branch"))
    src = await _gh(c, f, "GET", f"/repos/{repo}/git/ref/heads/{_branch(cfg, a, 'from_branch')}")
    d = await _gh(c, f, "POST", f"/repos/{repo}/git/refs", body={"ref": f"refs/heads/{name}", "sha": (src.get("object") or {}).get("sha")})
    return {"branch": name, "sha": (d.get("object") or {}).get("sha")}


@_tool("github", "delete_file", "destructive", "Delete one file with a commit.",
       _obj({"path": _s("File path"), "message": _s("Commit message"), "branch": _s("Branch; the default branch when omitted"),
             "sha": _s("The file's blob sha; looked up when omitted")}, ("path", "message")))
async def _(c, f, cfg, a):
    repo, path, branch = _repo(cfg, a), str(_need(a, "path")).strip("/"), _branch(cfg, a)
    sha = a.get("sha") or await _gh_sha_of(c, f, repo, path, branch)
    if not sha:
        raise PlugToolError(f"no file at {path} on {branch}")
    d = await _gh(c, f, "DELETE", f"/repos/{repo}/contents/{path}", body={"message": _need(a, "message"), "branch": branch, "sha": sha})
    return {"path": path, "branch": branch, "commit": (d.get("commit") or {}).get("sha")}


@_tool("github", "create_issue", "write", "Open an issue.",
       _obj({"title": _s("Title"), "body": _s("Body (markdown)"),
             "labels": {"type": "array", "items": {"type": "string"}, "description": "Label names"},
             "assignees": {"type": "array", "items": {"type": "string"}, "description": "GitHub logins"}}, ("title",)))
async def _(c, f, cfg, a):
    body = {"title": _need(a, "title"), **{k: a[k] for k in ("body", "labels", "assignees") if a.get(k)}}
    return _issue_out(await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/issues", body=body))


@_tool("github", "update_issue", "write", "Edit an issue's title, body, state or labels.",
       _obj({"number": _i("Issue number"), "title": _s("New title"), "body": _s("New body"),
             "state": _s("open or closed", enum=["open", "closed"]),
             "labels": {"type": "array", "items": {"type": "string"}, "description": "Label names (replaces the set)"}}, ("number",)))
async def _(c, f, cfg, a):
    body = {k: a[k] for k in ("title", "body", "state", "labels") if a.get(k) is not None}
    return _issue_out(await _gh(c, f, "PATCH", f"/repos/{_repo(cfg, a)}/issues/{int(_need(a, 'number'))}", body=body))


@_tool("github", "add_issue_comment", "write", "Comment on an issue or pull request.",
       _obj({"number": _i("Issue or pull request number"), "body": _s("Comment (markdown)")}, ("number", "body")))
async def _(c, f, cfg, a):
    d = await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/issues/{int(_need(a, 'number'))}/comments", body={"body": _need(a, "body")})
    return {**_pick(d, ("id", "html_url", "created_at")), "user": _user(d)}


@_tool("github", "create_pull_request", "write", "Open a pull request from a branch.",
       _obj({"title": _s("Title"), "head": _s("Branch with the changes"), "base": _s("Branch to merge into; the default branch when omitted"),
             "body": _s("Description (markdown)"), "draft": _b("Open as a draft")}, ("title", "head")))
async def _(c, f, cfg, a):
    body = {"title": _need(a, "title"), "head": _need(a, "head"), "base": _branch(cfg, a, "base"),
            **{k: a[k] for k in ("body", "draft") if a.get(k) is not None}}
    return _pull_out(await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/pulls", body=body))


@_tool("github", "update_pull_request", "write", "Edit a pull request's title, body, state or base.",
       _obj({"number": _i("Pull request number"), "title": _s("New title"), "body": _s("New body"),
             "state": _s("open or closed", enum=["open", "closed"]), "base": _s("New base branch")}, ("number",)))
async def _(c, f, cfg, a):
    body = {k: a[k] for k in ("title", "body", "state", "base") if a.get(k) is not None}
    return _pull_out(await _gh(c, f, "PATCH", f"/repos/{_repo(cfg, a)}/pulls/{int(_need(a, 'number'))}", body=body))


@_tool("github", "create_pull_request_review", "write", "Review a pull request: approve, request changes or comment.",
       _obj({"number": _i("Pull request number"), "event": _s("APPROVE, REQUEST_CHANGES or COMMENT", enum=["APPROVE", "REQUEST_CHANGES", "COMMENT"]),
             "body": _s("Review text")}, ("number", "event")))
async def _(c, f, cfg, a):
    body = {"event": _need(a, "event"), **({"body": a["body"]} if a.get("body") else {})}
    d = await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/pulls/{int(_need(a, 'number'))}/reviews", body=body)
    return {**_pick(d, ("id", "state", "html_url", "submitted_at")), "user": _user(d)}


@_tool("github", "merge_pull_request", "destructive", "Merge a pull request into its base branch.",
       _obj({"number": _i("Pull request number"), "merge_method": _s("merge, squash or rebase", enum=["merge", "squash", "rebase"]),
             "commit_title": _s("Title of the merge commit")}, ("number",)))
async def _(c, f, cfg, a):
    body = {k: a[k] for k in ("merge_method", "commit_title") if a.get(k)}
    d = await _gh(c, f, "PUT", f"/repos/{_repo(cfg, a)}/pulls/{int(_need(a, 'number'))}/merge", body=body)
    return _pick(d, ("sha", "merged", "message"))


@_tool("github", "run_workflow", "write", "Dispatch a workflow run on a branch.",
       _obj({"workflow_id": _s("Workflow id or file name (ci.yml)"), "ref": _s("Branch or tag"),
             "inputs": {"type": "object", "description": "Workflow inputs", "additionalProperties": {"type": "string"}}}, ("workflow_id", "ref")))
async def _(c, f, cfg, a):
    body = {"ref": _need(a, "ref"), **({"inputs": a["inputs"]} if isinstance(a.get("inputs"), dict) else {})}
    await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/actions/workflows/{_need(a, 'workflow_id')}/dispatches", body=body)
    return {"dispatched": True, "workflow_id": a["workflow_id"], "ref": a["ref"]}


@_tool("github", "rerun_workflow_run", "write", "Re-run a workflow run.", _obj({"run_id": _i("Run id")}, ("run_id",)))
async def _(c, f, cfg, a):
    await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/actions/runs/{int(_need(a, 'run_id'))}/rerun")
    return {"rerun": True, "run_id": a["run_id"]}


@_tool("github", "cancel_workflow_run", "write", "Cancel a workflow run.", _obj({"run_id": _i("Run id")}, ("run_id",)))
async def _(c, f, cfg, a):
    await _gh(c, f, "POST", f"/repos/{_repo(cfg, a)}/actions/runs/{int(_need(a, 'run_id'))}/cancel")
    return {"cancelled": True, "run_id": a["run_id"]}


# ── Vercel: the company project, through a project-scoped token ───────────────────────────────
def _vc_msg(r: httpx.Response) -> str:
    try:
        d = r.json()
        return str(((d.get("error") or {}).get("message")) or d)[:300] if isinstance(d, dict) else r.text[:300]
    except ValueError:
        return r.text[:300]


async def _vc(c: httpx.AsyncClient, fields: dict, config: dict, method: str, path: str, *, body=None, params=None):
    params = {**(params or {})}
    if config.get("team_id"):
        params["teamId"] = config["team_id"]
    r = await c.request(method, VERCEL_API + path, json=body, params=params,
                        headers={"Authorization": f"Bearer {fields.get('token', '')}"})
    if r.status_code >= 400:
        raise PlugToolError(f"Vercel answered {r.status_code}: {_vc_msg(r)}")
    return r.json() if r.content else {}


def _project(config: dict) -> str:
    pid = str(config.get("project_id") or config.get("project") or "")
    if not pid:
        raise PlugToolError("the Vercel plug names no project; reconnect it in the workspace's Plugs page")
    return pid


_DEPLOY = ("uid", "id", "url", "name", "state", "readyState", "target", "createdAt", "ready", "errorMessage", "inspectorUrl")


def _deploy_out(d: dict) -> dict:
    out = _pick(d, _DEPLOY)
    if out.get("uid") and not out.get("id"):
        out["id"] = out.pop("uid")
    meta = d.get("meta") or {}
    for k in ("githubCommitRef", "githubCommitSha", "githubCommitMessage"):
        if meta.get(k):
            out[k] = meta[k]
    if d.get("alias"):
        out["alias"] = d["alias"]
    return out


@_tool("vercel", "get_project", "read", "The company project: framework, linked repository, domains, latest deployment.", _obj({}))
async def _(c, f, cfg, a):
    d = await _vc(c, f, cfg, "GET", f"/v9/projects/{_project(cfg)}")
    doms = await _vc(c, f, cfg, "GET", f"/v9/projects/{_project(cfg)}/domains")
    latest = [(_deploy_out(x)) for x in d.get("latestDeployments") or []][:3]
    return {**_pick(d, ("id", "name", "framework", "nodeVersion", "rootDirectory", "updatedAt")),
            "link": _pick(d.get("link") or {}, ("type", "org", "repo", "repoId", "productionBranch")),
            "domains": [x.get("name") for x in doms.get("domains") or []], "latestDeployments": latest}


@_tool("vercel", "list_deployments", "read", "Recent deployments with state and url.",
       _obj({"limit": _i("How many, at most 100"), "state": _s("Only this state (READY, ERROR, BUILDING, QUEUED, CANCELED)"),
             "target": _s("production or preview", enum=["production", "preview"])}))
async def _(c, f, cfg, a):
    params = {"projectId": _project(cfg), "limit": min(int(a.get("limit") or 20), 100)}
    for k in ("state", "target"):
        if a.get(k):
            params[k] = a[k]
    d = await _vc(c, f, cfg, "GET", "/v6/deployments", params=params)
    return [_deploy_out(x) for x in d.get("deployments") or []]


@_tool("vercel", "get_deployment", "read", "One deployment: state, url, error.", _obj({"id": _s("Deployment id or url")}, ("id",)))
async def _(c, f, cfg, a):
    return _deploy_out(await _vc(c, f, cfg, "GET", f"/v13/deployments/{_need(a, 'id')}"))


@_tool("vercel", "get_deployment_logs", "read", "Build and runtime log lines of a deployment.",
       _obj({"id": _s("Deployment id"), "limit": _i("How many lines, at most 500")}, ("id",)))
async def _(c, f, cfg, a):
    d = await _vc(c, f, cfg, "GET", f"/v3/deployments/{_need(a, 'id')}/events",
                  params={"limit": min(int(a.get("limit") or 200), 500), "builds": 1, "direction": "backward"})
    rows = d if isinstance(d, list) else d.get("events") or []
    lines = []
    for e in rows:
        payload = e.get("payload") or {}
        lines.append(f"{e.get('type') or ''} {payload.get('text') or e.get('text') or ''}".strip())
    return "\n".join(lines)


@_tool("vercel", "list_env", "read", "Environment variables of the project (names and targets, never values).", _obj({}))
async def _(c, f, cfg, a):
    d = await _vc(c, f, cfg, "GET", f"/v9/projects/{_project(cfg)}/env")
    return [_pick(x, ("id", "key", "target", "type", "updatedAt")) for x in d.get("envs") or []]


async def _vc_link(c, f, cfg) -> dict:
    d = await _vc(c, f, cfg, "GET", f"/v9/projects/{_project(cfg)}")
    return d.get("link") or {}


@_tool("vercel", "deploy_from_repo", "write",
       "Create a deployment from the linked GitHub repository at a ref, then watch it for up to two minutes. "
       "Returns the deployment's id, state and url; call get_deployment to keep watching a slow build.",
       _obj({"ref": _s("Branch, tag or commit; the production branch when omitted"),
             "production": _b("Deploy to production rather than as a preview"),
             "repo": _s("owner/name, when the project is not linked yet")}))
async def _(c, f, cfg, a):
    link = await _vc_link(c, f, cfg)
    src: dict = {"type": "github"}
    if link.get("repoId"):
        src["repoId"] = link["repoId"]
    elif a.get("repo") and "/" in str(a["repo"]):
        src["org"], src["repo"] = str(a["repo"]).split("/", 1)
    elif link.get("org") and link.get("repo"):
        src["org"], src["repo"] = link["org"], link["repo"]
    else:
        raise PlugToolError("the project is not linked to a repository; call link_repo first or pass repo")
    src["ref"] = str(a.get("ref") or link.get("productionBranch") or "main")
    body = {"name": str(cfg.get("project") or _project(cfg)), "project": _project(cfg), "gitSource": src}
    if a.get("production"):
        body["target"] = "production"
    d = await _vc(c, f, cfg, "POST", "/v13/deployments", body=body)
    did = d.get("id") or d.get("uid")
    started = time.monotonic()
    while did and time.monotonic() - started < DEPLOY_WAIT_S:
        if d.get("readyState") in ("READY", "ERROR", "CANCELED"):
            break
        await asyncio.sleep(DEPLOY_POLL_S)
        d = await _vc(c, f, cfg, "GET", f"/v13/deployments/{did}")
    return _deploy_out(d)


@_tool("vercel", "link_repo", "write", "Link the project to a GitHub repository (owner/name).",
       _obj({"repo": _s("owner/name")}, ("repo",)))
async def _(c, f, cfg, a):
    d = await _vc(c, f, cfg, "POST", f"/v9/projects/{_project(cfg)}/link", body={"type": "github", "repo": _need(a, "repo")})
    return {"link": _pick(d.get("link") or d, ("type", "org", "repo", "repoId", "productionBranch"))}


@_tool("vercel", "set_env", "write", "Set an environment variable on the project (created or replaced).",
       _obj({"key": _s("Name"), "value": _s("Value"),
             "target": {"type": "array", "items": {"type": "string", "enum": ["production", "preview", "development"]},
                        "description": "Where it applies; all three when omitted"},
             "sensitive": _b("Store as a sensitive variable (never readable back)")}, ("key", "value")))
async def _(c, f, cfg, a):
    row = {"key": _need(a, "key"), "value": str(a.get("value") or ""),
           "type": "sensitive" if a.get("sensitive") else "encrypted",
           "target": a.get("target") or ["production", "preview", "development"]}
    d = await _vc(c, f, cfg, "POST", f"/v10/projects/{_project(cfg)}/env", body=[row], params={"upsert": "true"})
    created = d.get("created") or []
    return {"key": row["key"], "target": row["target"], "ids": [x.get("id") for x in created if isinstance(x, dict)]}


@_tool("vercel", "delete_env", "destructive", "Remove an environment variable from the project.",
       _obj({"key": _s("Name")}, ("key",)))
async def _(c, f, cfg, a):
    key = _need(a, "key")
    d = await _vc(c, f, cfg, "GET", f"/v9/projects/{_project(cfg)}/env")
    ids = [x.get("id") for x in d.get("envs") or [] if x.get("key") == key]
    if not ids:
        raise PlugToolError(f"no environment variable named {key}")
    for eid in ids:
        await _vc(c, f, cfg, "DELETE", f"/v9/projects/{_project(cfg)}/env/{eid}")
    return {"key": key, "removed": len(ids)}


@_tool("vercel", "create_deploy_hook", "write", "Create a deploy hook url for a branch.",
       _obj({"name": _s("Hook name"), "ref": _s("Branch the hook deploys")}, ("name", "ref")))
async def _(c, f, cfg, a):
    d = await _vc(c, f, cfg, "POST", f"/v1/projects/{_project(cfg)}/deploy-hooks", body={"name": _need(a, "name"), "ref": _need(a, "ref")})
    hooks = (d.get("link") or {}).get("deployHooks") or d.get("deployHooks") or []
    mine = next((h for h in hooks if h.get("name") == a["name"] and h.get("ref") == a["ref"]), hooks[-1] if hooks else d)
    return _pick(mine, ("id", "name", "ref", "url", "createdAt"))


@_tool("vercel", "cancel_deployment", "write", "Cancel a deployment that is building.", _obj({"id": _s("Deployment id")}, ("id",)))
async def _(c, f, cfg, a):
    return _deploy_out(await _vc(c, f, cfg, "PATCH", f"/v12/deployments/{_need(a, 'id')}/cancel"))


# ── InsForge: the company backend, through its project key ───────────────────────────────────
# Routes are the ones verified against a live project (health, auth users, database tables and
# records); anything else the backend serves under /api/ goes through `request`, so a verified
# route the agent knows is reachable without this file guessing its shape.
def _inf_base(config: dict) -> str:
    url = str(config.get("url") or "").rstrip("/")
    if not url.startswith("http"):
        raise PlugToolError("the InsForge plug names no backend url; reconnect it in the workspace's Plugs page")
    return url


async def _inf(c: httpx.AsyncClient, fields: dict, config: dict, method: str, path: str, *, body=None, params=None,
               prefer: str | None = None):
    if not path.startswith("/api/"):
        raise PlugToolError("path must start with /api/")
    headers = {"Authorization": f"Bearer {fields.get('api_key', '')}"}
    if prefer:
        headers["Prefer"] = prefer
    r = await c.request(method, _inf_base(config) + path, json=body, params=params, headers=headers)
    if r.status_code >= 400:
        raise PlugToolError(f"InsForge answered {r.status_code}: {r.text[:300]}")
    if not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        return r.text


def _filters(a: dict) -> dict:
    """PostgREST filters as query parameters: {"status": "eq.open", "age": "gte.18"}."""
    flt = a.get("filters") or {}
    if not isinstance(flt, dict) or not all(isinstance(v, str) and "." in v for v in flt.values()):
        raise PlugToolError('filters must be an object of column: "operator.value" (eq.open, gte.18, like.*x*)')
    return dict(flt)


@_tool("insforge", "get_project", "read", "The company backend: url, project, health, public anon key.", _obj({}))
async def _(c, f, cfg, a):
    try:
        health = await _inf(c, f, cfg, "GET", "/api/health")
    except PlugToolError as e:
        health = {"error": str(e)}
    return {**_pick(cfg, ("project", "project_id", "url", "region")), "anon_key": f.get("anon_key") or None, "health": health}


@_tool("insforge", "list_tables", "read", "Tables in the company database.", _obj({}))
async def _(c, f, cfg, a):
    return await _inf(c, f, cfg, "GET", "/api/database/tables")


@_tool("insforge", "describe_table", "read", "Columns of one table.", _obj({"table": _s("Table name")}, ("table",)))
async def _(c, f, cfg, a):
    return await _inf(c, f, cfg, "GET", f"/api/database/tables/{_need(a, 'table')}")


@_tool("insforge", "query_rows", "read", "Read rows of a table with optional column selection, filters, order and limit.",
       _obj({"table": _s("Table name"), "select": _s("Columns, comma-separated; all when omitted"),
             "filters": {"type": "object", "description": 'Column filters, "operator.value" each (eq.open, gte.18, like.*x*)',
                         "additionalProperties": {"type": "string"}},
             "order": _s("Column with direction, e.g. created_at.desc"), "limit": _i("At most this many rows (default 100)"),
             "offset": _i("Skip this many rows")}, ("table",)))
async def _(c, f, cfg, a):
    params = {**_filters(a), "limit": min(int(a.get("limit") or 100), 1000)}
    for k in ("select", "order", "offset"):
        if a.get(k) not in (None, ""):
            params[k] = a[k]
    return await _inf(c, f, cfg, "GET", f"/api/database/records/{_need(a, 'table')}", params=params)


@_tool("insforge", "create_table", "write", "Create a table. id, created_at and updated_at are added for you.",
       _obj({"table": _s("Table name"),
             "columns": {"type": "array", "description": "Columns",
                         "items": _obj({"name": _s("Column name"),
                                        "type": _s("string, integer, boolean, uuid, datetime, float or json",
                                                   enum=["string", "integer", "boolean", "uuid", "datetime", "float", "json"]),
                                        "nullable": _b("May be null (default true)"), "unique": _b("Unique (default false)")},
                                       ("name", "type"))}}, ("table", "columns")))
async def _(c, f, cfg, a):
    cols = [{"columnName": x["name"], "type": x["type"], "isNullable": x.get("nullable", True) is not False,
             "isUnique": bool(x.get("unique"))} for x in a.get("columns") or []]
    if not cols:
        raise PlugToolError("columns is empty")
    return await _inf(c, f, cfg, "POST", "/api/database/tables", body={"tableName": _need(a, "table"), "columns": cols})


@_tool("insforge", "delete_table", "destructive", "Drop a table and every row in it.", _obj({"table": _s("Table name")}, ("table",)))
async def _(c, f, cfg, a):
    return await _inf(c, f, cfg, "DELETE", f"/api/database/tables/{_need(a, 'table')}") or {"deleted": a["table"]}


@_tool("insforge", "insert_rows", "write", "Insert rows into a table.",
       _obj({"table": _s("Table name"), "rows": {"type": "array", "items": {"type": "object"}, "description": "Row objects"}},
            ("table", "rows")))
async def _(c, f, cfg, a):
    rows = a.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise PlugToolError("rows must be a non-empty array of objects")
    return await _inf(c, f, cfg, "POST", f"/api/database/records/{_need(a, 'table')}", body=rows, prefer="return=representation")


@_tool("insforge", "update_rows", "write", "Update the rows a filter selects.",
       _obj({"table": _s("Table name"), "filters": {"type": "object", "description": 'Which rows, "operator.value" each',
                                                    "additionalProperties": {"type": "string"}},
             "values": {"type": "object", "description": "Columns to set"}}, ("table", "filters", "values")))
async def _(c, f, cfg, a):
    flt = _filters(a)
    if not flt:
        raise PlugToolError("filters must select the rows to update")
    if not isinstance(a.get("values"), dict) or not a["values"]:
        raise PlugToolError("values must be a non-empty object")
    return await _inf(c, f, cfg, "PATCH", f"/api/database/records/{_need(a, 'table')}", body=a["values"], params=flt,
                      prefer="return=representation")


@_tool("insforge", "delete_rows", "destructive", "Delete the rows a filter selects.",
       _obj({"table": _s("Table name"), "filters": {"type": "object", "description": 'Which rows, "operator.value" each',
                                                    "additionalProperties": {"type": "string"}}}, ("table", "filters")))
async def _(c, f, cfg, a):
    flt = _filters(a)
    if not flt:
        raise PlugToolError("filters must select the rows to delete")
    return await _inf(c, f, cfg, "DELETE", f"/api/database/records/{_need(a, 'table')}", params=flt, prefer="return=representation")


@_tool("insforge", "create_user", "write", "Create a sign-in user on the company backend.",
       _obj({"email": _s("Email"), "password": _s("Password")}, ("email", "password")))
async def _(c, f, cfg, a):
    d = await _inf(c, f, cfg, "POST", "/api/auth/users", body={"email": _need(a, "email"), "password": _need(a, "password")})
    return _pick(d if isinstance(d, dict) else {}, ("id", "email", "created_at", "createdAt", "user")) or d


@_tool("insforge", "request", "write",
       "Call any route of the company backend under /api/ (storage, functions, auth, secrets) with the project key. "
       "GET reads; other methods change things.",
       _obj({"method": _s("GET, POST, PUT, PATCH or DELETE", enum=["GET", "POST", "PUT", "PATCH", "DELETE"]),
             "path": _s("Route, starting with /api/"), "body": {"description": "JSON body"},
             "params": {"type": "object", "description": "Query parameters", "additionalProperties": {"type": "string"}}},
            ("method", "path")))
async def _(c, f, cfg, a):
    return await _inf(c, f, cfg, str(_need(a, "method")).upper(), str(_need(a, "path")), body=a.get("body"),
                      params=a.get("params") or None)


# The browser plug's tools come from its own plane; a page action is a write, a look is a read.
import browser_plane as _browser_plane  # noqa: E402

for _t in _browser_plane._TOOLS:
    _TOOLS.setdefault(BROWSER, []).append({"name": _t["name"], "risk": "write" if _t["risk"] == "act" else "read",
                                           "description": _t["description"], "inputSchema": _t["inputSchema"], "fn": None})
