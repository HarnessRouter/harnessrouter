#!/usr/bin/env python3
"""The chromium-libs check has to be able to fail: a list that drifts from the pinned Playwright's and
passes is worse than no check. Each case below is one way the two can part, and each has to be caught;
the matching forms beside them must not. Playwright's table is read in both of its shapes: the
TypeScript source at a tag, and the compiled JavaScript the venv's driver carries."""
import contextlib
import importlib.util
import io
import os
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ccl", os.path.join(here, "check-chromium-libs.py"))
ccl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccl)

# Playwright's source: the table literal, and an alias after it that spreads another distro's lists.
TS = """
export const deps: DistroDeps = {
  'ubuntu24.04-x64': {
    tools: [
      'xvfb',
      'fonts-noto-color-emoji',
    ],
    chromium: [
      'libasound2t64',
      'libnss3'
    ],
    firefox: [
      'libasound2',
    ],
    lib2package: {
      'libasound.so.2': 'libasound2t64',
    },
  },
  'debian13-x64': {
    tools: [
      'xvfb',
      'fonts-unifont',
    ],
    chromium: [
      'libnss3',
      'libx11-6',
    ],
    firefox: [
      'libgtk-3-0t64',
    ],
    lib2package: {
      'libnss3.so': 'libnss3',
    },
  },
};

deps['debian13-arm64'] = {
  tools: [...deps['debian13-x64'].tools],
  chromium: [...deps['debian13-x64'].chromium],
  firefox: [
    ...deps['debian13-x64'].firefox,
  ],
  lib2package: {
    ...deps['debian13-x64'].lib2package,
  },
};
"""
# The driver's compiled copy of the same: double quotes, one line per list, the alias as an assignment.
JS = """
const deps = {};
deps["ubuntu24.04-x64"] = {
  tools: ["xvfb", "fonts-noto-color-emoji"],
  chromium: ["libasound2t64", "libnss3"],
  firefox: ["libasound2"],
  lib2package: { "libasound.so.2": "libasound2t64" }
};
deps["debian13-x64"] = {
  tools: ["xvfb", "fonts-unifont"],
  chromium: ["libnss3", "libx11-6"],
  firefox: ["libgtk-3-0t64"],
  lib2package: { "libnss3.so": "libnss3" }
};
deps["debian13-arm64"] = {
  tools: [...deps["debian13-x64"].tools],
  chromium: [...deps["debian13-x64"].chromium],
  firefox: [...deps["debian13-x64"].firefox],
  lib2package: { ...deps["debian13-x64"].lib2package }
};
"""
DEBIAN13 = ["xvfb", "fonts-unifont", "libnss3", "libx11-6"]

for label, text in (("ts", TS), ("js", JS)):
    assert ccl.playwright_libs(text, "debian13-x64") == DEBIAN13, (label, ccl.playwright_libs(text, "debian13-x64"))
    assert ccl.playwright_libs(text, "debian13-arm64") == DEBIAN13, (label, "the alias is the list it spreads")
    assert ccl.playwright_libs(text, "ubuntu24.04-x64") == ["xvfb", "fonts-noto-color-emoji", "libasound2t64", "libnss3"], label
    # firefox's and the library map are not part of what chromium needs
    assert "libgtk-3-0t64" not in ccl.playwright_libs(text, "debian13-x64") and "libnss3.so" not in ccl.playwright_libs(text, "debian13-x64")
    assert not ccl.compare(DEBIAN13, text, "debian13-x64", label) and not ccl.compare(DEBIAN13, text, "debian13-arm64", label)
    # every way the two can part is reported, naming the package
    for case, libs in {
        "a package dropped": DEBIAN13[:-1],
        "a package added": DEBIAN13 + ["libxcb1"],
        "a package renamed": [x if x != "libnss3" else "libnss3t64" for x in DEBIAN13],
    }.items():
        out = ccl.compare(libs, text, "debian13-x64", label)
        assert out, f"{label}: not caught: {case}"
        assert any(p in " ".join(out) for p in ("libx11-6", "libxcb1", "libnss3")), (case, out)
    assert ccl.compare(DEBIAN13, text, "ubuntu24.04-x64", label), f"{label}: another distro's list passed as Debian 13's"


def exits(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            fn(*a)
        except SystemExit as e:
            return str(e.code)
    return None


assert "no entry for debian14-x64" in exits(ccl.playwright_libs, TS, "debian14-x64")
assert "has no chromium list" in exits(ccl.table_libs, "deps['x-x64'] = {\n  tools: ['a'],\n};\n", "x-x64", "chromium")
assert "refers to itself" in exits(ccl.table_libs, "deps['x-x64'] = {\n  tools: [...deps['x-x64'].tools],\n};\n", "x-x64", "tools")

# The entrypoint's list: CHROMIUM_LIBS=( … ) with comments inside, read in order; a doubled or malformed name fails.
EP = """
CHROMIUM_LIBS=(
  # tools
  xvfb fonts-unifont   # two
  # chromium
  libnss3
  libx11-6
)
CHROMIUM_LIBS_MARK=/var/lib/harnessrouter/chromium-libs
SYSTEMONE_PLAYWRIGHT_PIN="${HR_SYSTEMONE_PLAYWRIGHT_VERSION:-1.64.1}"
"""
assert ccl.committed_libs(EP) == DEBIAN13, ccl.committed_libs(EP)
assert ccl.playwright_pin(EP) == "1.64.1"
assert "more than once" in exits(ccl.committed_libs, EP.replace("  libnss3\n", "  libnss3 libnss3\n"))
assert "not a Debian package name" in exits(ccl.committed_libs, EP.replace("  libnss3\n", '  "$X"\n'))
assert "no CHROMIUM_LIBS" in exits(ccl.committed_libs, "TOOLS=x\n")
assert "no SYSTEMONE_PLAYWRIGHT_PIN" in exits(ccl.playwright_pin, "TOOLS=x\n")

# The committed list itself: it parses, and against a table that holds it, main passes; one that does not, fails.
with open(os.path.join(ccl.ROOT, "docker", "entrypoint.sh"), encoding="utf-8") as f:
    real = ccl.committed_libs(f.read())
assert len(real) == len(set(real)) and len(real) >= 20, real
with tempfile.TemporaryDirectory() as td:
    table = os.path.join(td, "nativeDeps.ts")
    with open(table, "w", encoding="utf-8") as f:
        f.write("export const deps = {\n  'debian13-x64': {\n    tools: [\n" + "".join(f"      '{x}',\n" for x in real[:11])
                + "    ],\n    chromium: [\n" + "".join(f"      '{x}',\n" for x in real[11:]) + "    ],\n  },\n};\n")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert ccl.main([table, "--distro", "debian13-x64"]) == 0, out.getvalue()
    assert "chromium libs hold" in out.getvalue()
    with open(table, "w", encoding="utf-8") as f:
        f.write("export const deps = {\n  'debian13-x64': {\n    tools: [\n      'xvfb',\n    ],\n    chromium: [\n      'libnss3',\n      'libnotthere1',\n    ],\n  },\n};\n")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        assert ccl.main([table, "--distro", "debian13-x64"]) == 1
    assert "libnotthere1" in out.getvalue() and "CHROMIUM_LIBS names what" in out.getvalue()
    assert "--distro is needed" in exits(ccl.main, [table])
print("check-chromium-libs can fail: every drift above is caught, and the forms that match pass")
