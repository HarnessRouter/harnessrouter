"""The four bases of batch 4 name ONE version each, everywhere a person or the installer reads it.

The console's label (ui/src/lib/harness.ts), the first-boot installer's pin (docker/entrypoint.sh)
and the hash-locked dependency tree the installer fills the venv from (docker/locks) must agree:
a label that says one release while another is installed is a claim about software nobody shipped,
and a lock whose top-level pin is not the installer's would fail every install closed."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENTRY = (ROOT / "docker" / "entrypoint.sh").read_text()
HARNESS_TS = (ROOT / "ui" / "src" / "lib" / "harness.ts").read_text()

# base id → (installer variable, lock file or None, the distribution the lock pins)
BASES = {
    "vibe": ("VIBE_LOCKED", "vibe.lock.txt", "mistral-vibe"),
    "fast-agent": ("FAST_AGENT_LOCKED", "fast-agent.lock.txt", "fast-agent-mcp"),
    "dcode": ("DCODE_LOCKED", "dcode.lock.txt", "deepagents-code"),
    "docker-agent": ("DOCKER_AGENT_LOCKED", None, None),
}


def _pin(var: str) -> str:
    m = re.search(rf'^{var}="([0-9.]+)"$', ENTRY, re.M)
    assert m, f"{var} is not set in docker/entrypoint.sh"
    return m.group(1)


def test_the_console_label_is_the_installed_version():
    for base, (var, _lock, _dist) in BASES.items():
        m = re.search(rf"id: '{re.escape(base)}',[^}}]*?version: 'v([0-9.]+)'", HARNESS_TS)
        assert m, f"no console entry for {base}"
        assert m.group(1) == _pin(var), f"{base}: the console says v{m.group(1)}, the installer pins {_pin(var)}"


def test_each_lock_pins_the_installers_version_with_hashes():
    for base, (var, lock, dist) in BASES.items():
        if not lock:
            continue
        text = (ROOT / "docker" / "locks" / lock).read_text()
        assert re.search(rf"^{re.escape(dist)}=={re.escape(_pin(var))} \\$", text, re.M), \
            f"{lock} does not pin {dist}=={_pin(var)}"
        # every requirement line carries at least one hash, which is what --require-hashes needs
        reqs = re.findall(r"^([A-Za-z0-9_.\-\[\]]+)==[^\s]+ \\$", text, re.M)
        assert reqs and text.count("--hash=sha256:") >= len(reqs), f"{lock} has a requirement without a hash"


def test_the_installer_installs_from_the_lock_with_hashes_required():
    assert "--require-hashes --no-deps -r \"$lv_lock\"" in ENTRY
    assert 'HR_LOCKS_DIR="${HR_LOCKS_DIR:-/app/locks}"' in ENTRY
    assert "COPY docker/locks/ /app/locks/" in (ROOT / "Dockerfile").read_text()
