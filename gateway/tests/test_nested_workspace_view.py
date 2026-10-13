"""The checkpoint tarball is the session directory; it is not always the directory the agent works in.

nanobot's loader refuses a session store inside the agent's workspace, so that one base keeps its
store at the session root and works one level down. Read straight through, a nanobot session showed
as 30 files under a `workspace/` prefix the user never typed — its three built-in skill bundles and
its instruction file among them. MEASURED on a live instance before the fix; the four surfaces that
read the checkpoint are the share page, the full files listing, the download-all zip and the kit
route that resolves an app's own file BY PATH (a kit asking for deck.json would not have found it).

The two facts needed to read it as the agent's directory are already written INTO the checkpoint by
the runner, which is why they are read back rather than restated here: `.harness/agent-subdir` names
the directory, and `.git/info/exclude` carries the base's machinery patterns — the same file
`git status` honours, which is what keeps the produced-files list clean. One source, two readers.
"""
import io
import os
import pathlib
import sys
import tarfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HR_BACKING", "local")
import app as A  # noqa: E402

EXCLUDE = ("# written by the harness runner: nanobot's own machinery, never the task's output\n"
           "workspace/.nanobot/\nworkspace/skills/\nworkspace/memory/\nworkspace/AGENTS.md\n")


def _tar(names: dict) -> tarfile.TarFile:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in names.items():
            b = data.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            t.addfile(ti, io.BytesIO(b))
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r")


# exactly the shape a real nanobot checkpoint has (verified against a live instance's workspace.tgz)
NESTED = {
    "./.harness/agent-subdir": "workspace",
    "./.git/info/exclude": EXCLUDE,
    "./.harness/home/.nanobot/cli-apps/x": "state",
    "./workspace/AGENTS.md": "instructions",
    "./workspace/.nanobot/workspace-id": "id",
    "./workspace/skills/imagegen/SKILL.md": "skill",
    "./workspace/report.md": "the deliverable",
}
FLAT = {
    "./.git/info/exclude": "",
    "./.harness/home/x": "state",
    "./AGENTS.md": "instructions",
    "./report.md": "the deliverable",
}


def _view(members: dict) -> set:
    tf = _tar(members)
    with tf:
        sub, pats = A._ws_rules(tf)
        out = set()
        for m in tf.getmembers():
            p = m.name[2:] if m.name.startswith("./") else m.name
            v = A._ws_view(p, sub, pats)
            if v is not None:
                out.add(v)
    return out


def test_a_nested_session_shows_the_agents_directory_and_nothing_else():
    assert _view(NESTED) == {"report.md"}


def test_a_flat_session_is_untouched():
    # every other base: the session dir IS the agent's, and the generic families still hide
    assert _view(FLAT) == {"report.md"}


def test_the_rules_come_from_the_checkpoint_not_from_this_process():
    tf = _tar(NESTED)
    with tf:
        sub, pats = A._ws_rules(tf)
    assert sub == "workspace"
    assert "workspace/skills/" in pats and "workspace/AGENTS.md" in pats
    assert not any(p.startswith("#") for p in pats), "comments are not patterns"


def test_a_marker_that_is_not_one_plain_directory_name_is_ignored():
    # a traversal or an absolute path in the marker must not move the view
    for bad in ("../../etc", "/etc", ".ssh", "a/b"):
        tf = _tar({**NESTED, "./.harness/agent-subdir": bad})
        with tf:
            sub, _p = A._ws_rules(tf)
        assert sub == "", bad


def test_a_path_maps_back_into_the_tar_so_the_download_still_resolves():
    # the listing hands out ids derived from the VISIBLE path; the reader has to find the member
    assert A._ws_member("report.md", "workspace") == "workspace/report.md"
    assert A._ws_member("report.md", "") == "report.md"
    assert A._wf_path(A._wf_id("report.md")) == "report.md"


def test_the_machinery_patterns_are_matched_the_way_git_reads_them():
    # relative to the session dir, which is where the file lives — not to the agent's directory
    sub, pats = "workspace", ("workspace/skills/", "workspace/AGENTS.md")
    assert A._ws_view("workspace/skills/a/b.md", sub, pats) is None
    assert A._ws_view("workspace/AGENTS.md", sub, pats) is None
    assert A._ws_view("workspace/skills.md", sub, pats) == "skills.md"
