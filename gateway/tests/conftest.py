"""The gateway's test environment, set once, before any test module imports `app`.

`app` reads its configuration at import and never again, so whichever test module imports it
first decides the environment for the whole run. Three files (database, media, media_attack) each
set a full environment at the top and relied on being that first module; any new file sorting
before `test_database_mcp.py` that imported `app` bare silently won the race with no environment,
and 100+ tests in those files failed on collection order alone. pytest loads conftest before any
test module, so this is the one place the environment lives. The per-file `os.environ.update`
blocks still run, later and harmlessly: same keys, and each keeps its own data directory."""
import os
import tempfile

_DATA = tempfile.mkdtemp(prefix="hr-gwtest-")
os.environ.update({
    "HR_BACKING": "local",
    "HR_DATA_DIR": _DATA,
    "HARNESS_WORKSPACE": os.path.join(_DATA, "workspaces"),
    "HR_SECRET_KEY": "test-passphrase-not-a-real-one",
    "HARNESS_INTERNAL_KEY": "test-internal-key",
    "HARNESS_GLOBAL_TENANT": "global",
    "HARNESS_PUBLIC_BASE_URL": "https://gateway.example",
    "HR_POOL_AUTH": "none",
    "HR_IDENTITY_MODE": "off",
    "HR_MEDIA_SWEEP_S": "3600",
})
