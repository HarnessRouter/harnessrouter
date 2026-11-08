"""Every Python base installs from a hashed lock, and its own pins are the ones the lock covers (#623).

docker/entrypoint.sh installs a Python base from docker/locks/<base>.lock.txt only when the base's
requirements are exactly the ones in <base>.in; anything else is treated as an operator's override and
installed unlocked, with an "unverified" stamp and one WARN line. So a pin bumped in the script and not
in the .in (or the other way round) would not fail anything: every volume would quietly go back to an
unverified install. These tests evaluate the script's own default pins and hold them to the .in files,
and hold each lock to what --require-hashes on the image's pip can actually install."""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCKS = ROOT / "docker" / "locks"
ENTRY = (ROOT / "docker" / "entrypoint.sh").read_text()

# base → the array of requirements docker/entrypoint.sh builds for it
PINNED = {
    "aider": "AIDER_REQS", "qoder": "QODER_REQS", "cheetahclaws": "CHEETAHCLAWS_REQS",
    "systemone": "SYSTEMONE_REQS", "openhands": "OPENHANDS_REQS", "opensquilla": "OPENSQUILLA_REQS",
    "nanobot": "NANOBOT_REQS", "dsh": "DSH_REQS", "hermes": "HERMES_REQS",
}
LOCKED = sorted(p.name[: -len(".lock.txt")] for p in LOCKS.glob("*.lock.txt"))
REQ = re.compile(r"^(\S+?)(?:==(\S+)| @ (\S+))(.*?)(?: \\)?$")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_lines(text: str):
    return [l for l in text.splitlines() if l and not l[0].isspace() and not l.startswith("#")]


def _defaults() -> dict[str, str]:
    """What each base's requirements are with no HR_* override set: the script's own assignments,
    evaluated by bash in an empty environment."""
    names = "|".join(v.removesuffix("_REQS") for v in PINNED.values())
    lines = [l for l in ENTRY.splitlines()
             if re.match(rf"^({names})_[A-Z0-9_]+=", l) or l.startswith('if [ "$SYSTEMONE_PIN" =')]
    script = "\n".join(lines) + "\n" + "\n".join(
        f'printf "%s\\t%s\\n" {base} "${{{var}[*]}}"' for base, var in PINNED.items())
    out = subprocess.run(["env", "-i", "bash", "-c", script], capture_output=True, text=True, check=True)
    return dict(l.split("\t", 1) for l in out.stdout.splitlines())


def test_every_base_installed_from_a_lock_has_one():
    code = "\n".join(l for l in ENTRY.splitlines() if not l.lstrip().startswith("#"))
    used = set(re.findall(r'(?:install_pinned_venv|is_locked) ([a-z][a-z0-9-]*) ', code))
    used = {u for u in used if not u.startswith('"')}
    for base in sorted(used | set(PINNED)):
        assert (LOCKS / f"{base}.in").is_file(), f"docker/locks/{base}.in is missing"
        assert (LOCKS / f"{base}.lock.txt").is_file(), f"docker/locks/{base}.lock.txt is missing"


def test_the_scripts_default_pins_are_the_ones_each_lock_was_compiled_from():
    defaults = _defaults()
    for base in PINNED:
        compiled_from = " ".join(_requirement_lines((LOCKS / f"{base}.in").read_text()))
        assert defaults[base] == compiled_from, (
            f"{base}: entrypoint.sh asks for {defaults[base]!r} but {base}.lock.txt was compiled from "
            f"{compiled_from!r}; every volume would install it unverified")


def test_each_lock_holds_its_direct_pins():
    for base in LOCKED:
        lock = (LOCKS / f"{base}.lock.txt").read_text()
        for req in _requirement_lines((LOCKS / f"{base}.in").read_text()):
            m = REQ.match(req)
            if not m:   # a range (Agent Zero's floors): the constraints decide it, the lock records it
                continue
            name = re.sub(r"\[.*\]", "", m.group(1))
            if m.group(2):
                pinned = {_norm(n): v for n, v in re.findall(r"^(\S+)==(\S+) ", lock, re.M)}
                assert pinned.get(_norm(name)) == m.group(2), f"{base}.lock.txt does not pin {name}=={m.group(2)}"
            elif m.group(3):
                assert f"{name} @ {m.group(3)} " in lock, f"{base}.lock.txt does not name {m.group(3)}"


def test_every_distribution_in_every_lock_is_hashed():
    for base in LOCKED + ["build"]:
        text = (LOCKS / f"{base}.lock.txt").read_text()
        blocks = re.split(r"\n(?=\S)", text.strip())
        for block in blocks:
            if block.startswith("#"):
                continue
            assert "--hash=sha256:" in block, f"{base}.lock.txt: {block.splitlines()[0]} has no hash"


def test_the_new_locks_carry_no_environment_markers():
    # A `platform_release >= '19.0'` marker (macOS) makes the image's pip parse the host kernel's
    # release ("6.8.0-1070-gcp") as a version and crash. scripts/lock-pypi.sh resolves for the image's
    # two Linux platforms, which writes no markers at all.
    for base in list(PINNED) + ["agentzero", "build"]:
        for line in _requirement_lines((LOCKS / f"{base}.lock.txt").read_text()):
            assert " ; " not in line, f"{base}.lock.txt carries a marker: {line}"


def test_only_named_distributions_are_built_from_source():
    assert "--only-binary=:all:" in ENTRY
    assert "--no-build-isolation" in ENTRY  # the backend for those comes from build.lock.txt
    # the build backend's own lock holds setuptools and nothing it would fetch at build time
    assert [REQ.match(l).group(1) for l in _requirement_lines((LOCKS / "build.lock.txt").read_text())] == ["setuptools"]
