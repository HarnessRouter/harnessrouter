#!/usr/bin/env python3
"""The System One base's browser links against system libraries that docker/entrypoint.sh installs with
apt, from a list written there (CHROMIUM_LIBS), not with `playwright install-deps` (#623, item 5): that
ran the venv's Playwright driver as root, code an install brought, to arrive at the same apt command.
The list is Playwright's own, read off its nativeDeps table (`tools` + `chromium` for the Debian the
image runs), and this holds the two together: a Playwright bump whose list differs fails here until
the list in the entrypoint moves with it.

  python3 scripts/check-chromium-libs.py <nativeDeps.ts|nativeDeps.js> --distro debian13-x64 [--distro …]
      the table from a file: Playwright's source at the pinned tag, or the driver's compiled copy
  python3 scripts/check-chromium-libs.py --fetch --distro debian13-x64 [--distro …]
      the source at the tag of the entrypoint's SYSTEMONE_PLAYWRIGHT_PIN, from GitHub (the tests job)
  python3 scripts/check-chromium-libs.py
      in the container (the release gate): the driver the venv installed, which must be the pinned
      version, for this Debian and this architecture, and every package of the list installed
"""
import glob
import os
import platform
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINTS = [os.path.join(ROOT, "docker", "entrypoint.sh"), "/app/entrypoint.sh"]
NATIVE_DEPS_SRC = ("https://raw.githubusercontent.com/microsoft/playwright/v{pin}/"
                   "packages/playwright-core/src/server/registry/nativeDeps.ts")
VENV_GLOB = "{data}/agent-tools/systemone-venv/lib/python3*/site-packages/playwright"
DRIVER_LIB = "driver/package/lib"      # the table is in whichever bundle the driver compiled it into
KEYS = ("tools", "chromium")


def entrypoint_path() -> str:
    for p in ENTRYPOINTS:
        if os.path.exists(p):
            return p
    sys.exit("no docker/entrypoint.sh beside this script and no /app/entrypoint.sh")


def committed_libs(text: str) -> list[str]:
    """CHROMIUM_LIBS=( … ) of the entrypoint, in order; comments inside the parentheses are skipped."""
    m = re.search(r"^CHROMIUM_LIBS=\((.*?)^\)", text, re.M | re.S)
    if not m:
        sys.exit("docker/entrypoint.sh has no CHROMIUM_LIBS=( … ) list")
    libs = []
    for line in m.group(1).splitlines():
        libs += line.split("#", 1)[0].split()
    dup = sorted({x for x in libs if libs.count(x) > 1})
    if dup:
        sys.exit(f"CHROMIUM_LIBS names {', '.join(dup)} more than once")
    bad = [x for x in libs if not re.fullmatch(r"[a-z0-9][a-z0-9.+-]+", x)]
    if bad:
        sys.exit(f"CHROMIUM_LIBS holds what is not a Debian package name: {' '.join(bad)}")
    return libs


def playwright_pin(text: str) -> str:
    m = re.search(r'^SYSTEMONE_PLAYWRIGHT_PIN="\$\{HR_SYSTEMONE_PLAYWRIGHT_VERSION:-([^}]+)\}"$', text, re.M)
    if not m:
        sys.exit("docker/entrypoint.sh has no SYSTEMONE_PLAYWRIGHT_PIN default")
    return m.group(1)


def table_libs(text: str, distro: str, key: str, _seen: frozenset = frozenset()) -> list[str]:
    """One list (`tools` or `chromium`) of one distro of Playwright's nativeDeps, from its TypeScript
    source or the driver's compiled JavaScript: `'debian13-x64': { tools: [ 'xvfb', … ], chromium: [ … ] }`
    in the table, or `deps['debian13-arm64'] = { tools: [...deps['debian13-x64'].tools], … }` after it.
    A spread of another distro's list is that list."""
    if distro in _seen:
        sys.exit(f"nativeDeps: {distro}.{key} refers to itself")
    q = r"[\"']"
    m = re.search(rf"(?:^\s*{q}{re.escape(distro)}{q}\s*:\s*\{{|deps\[{q}{re.escape(distro)}{q}\]\s*=\s*\{{)", text, re.M)
    if not m:
        sys.exit(f"nativeDeps has no entry for {distro}")
    block = text[m.end():]
    end = re.search(r"^\s*\}[,;]?\s*$", block, re.M)      # the distro's closing brace, at the margin
    block = block[:end.start()] if end else block
    # the list's brackets, with one level inside them: `[...deps['debian13-x64'].tools]`
    km = re.search(rf"(?:^|[{{,\s]){q}?{key}{q}?\s*:\s*\[((?:[^\[\]]|\[[^\[\]]*\])*)\]", block, re.S)
    if not km:
        sys.exit(f"nativeDeps: {distro} has no {key} list")
    body = km.group(1)
    out: list[str] = []
    for item in re.finditer(rf"\.\.\.deps\[{q}([^\"']+){q}\]\.(\w+)|{q}([^\"']+){q}", body):
        if item.group(1):
            if item.group(2) != key:
                sys.exit(f"nativeDeps: {distro}.{key} spreads {item.group(1)}.{item.group(2)}")
            out += table_libs(text, item.group(1), key, _seen | {distro})
        else:
            out.append(item.group(3))
    return out


def playwright_libs(text: str, distro: str) -> list[str]:
    return [x for k in KEYS for x in table_libs(text, distro, k)]


def compare(libs: list[str], text: str, distro: str, where: str) -> list[str]:
    theirs = playwright_libs(text, distro)
    mine, want = set(libs), set(theirs)
    out = []
    if mine - want:
        out.append(f"{distro}: CHROMIUM_LIBS names what Playwright's {where} does not: {' '.join(sorted(mine - want))}")
    if want - mine:
        out.append(f"{distro}: Playwright's {where} asks for what CHROMIUM_LIBS lacks: {' '.join(sorted(want - mine))}")
    return out


def this_distro() -> str:
    """Playwright's key for the system this runs on: <ID><VERSION_ID>-<arch>, as its registry builds it."""
    kv = {}
    with open("/etc/os-release", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                kv[k] = v.strip('"')
    arch = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    if not arch:
        sys.exit(f"no Playwright architecture for {platform.machine()}")
    return f"{kv.get('ID', '?')}{kv.get('VERSION_ID', '?')}-{arch}"


def installed_driver(pin: str, data_dir: str) -> str:
    """The file of the venv's driver that holds its native dependency table (lib/coreBundle.js in 1.64;
    nativeDeps.js in older drivers), once the venv's Playwright is the pinned version."""
    pkgs = glob.glob(VENV_GLOB.format(data=data_dir))
    if len(pkgs) != 1:
        sys.exit(f"expected one playwright package under {VENV_GLOB.format(data=data_dir)}, found {len(pkgs)}")
    site = os.path.dirname(pkgs[0])
    dist = glob.glob(os.path.join(site, "playwright-*.dist-info"))
    have = [os.path.basename(d)[len("playwright-"):-len(".dist-info")] for d in dist]
    if have != [pin]:
        sys.exit(f"the venv holds playwright {have or 'nothing'}, the pin is {pin}")
    lib = os.path.join(pkgs[0], DRIVER_LIB)
    found = []
    for dirpath, _, files in os.walk(lib):
        for name in files:
            if name.endswith(".js"):
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    if re.search(r"[\"']debian\d+-x64[\"']\s*:\s*\{", f.read()):
                        found.append(path)
    if len(found) != 1:
        sys.exit(f"expected the native dependency table in one file under {lib}, found {len(found)}: {found}")
    return found[0]


def not_installed(libs: list[str]) -> list[str]:
    r = subprocess.run(["dpkg-query", "-W", "-f=${Package} ${db:Status-Status}\n", *libs],
                       capture_output=True, text=True)
    ok = {line.split()[0] for line in r.stdout.splitlines() if line.endswith(" installed")}
    return [x for x in libs if x not in ok]


def main(argv: list[str]) -> int:
    distros, path, fetch = [], None, False
    args = iter(argv)
    for a in args:
        if a == "--distro":
            distros.append(next(args, "") or sys.exit("--distro needs a value"))
        elif a == "--fetch":
            fetch = True
        elif a.startswith("-"):
            sys.exit(__doc__)
        else:
            path = a
    ep = entrypoint_path()
    with open(ep, encoding="utf-8") as f:
        ep_text = f.read()
    libs, pin = committed_libs(ep_text), playwright_pin(ep_text)
    problems: list[str] = []
    if fetch or path:
        if not distros:
            sys.exit("--distro is needed when the table comes from a file or from GitHub")
        if fetch:
            url = NATIVE_DEPS_SRC.format(pin=pin)
            with urllib.request.urlopen(url, timeout=60) as r:
                text = r.read().decode("utf-8")
            where = f"source at v{pin}"
        else:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            where = os.path.basename(path)
        for d in distros:
            problems += compare(libs, text, d, where)
    else:
        if distros:
            sys.exit("in the container the distro is read from /etc/os-release; --distro goes with a file or --fetch")
        data_dir = os.environ.get("HR_DATA_DIR", "/data")
        distros = [this_distro()]
        table = installed_driver(pin, data_dir)
        with open(table, encoding="utf-8") as f:
            text = f.read()
        problems += compare(libs, text, distros[0], f"installed driver {pin}")
        missing = not_installed(libs)
        if missing:
            problems.append(f"not installed in this container: {' '.join(missing)}")
    for p in problems:
        print(p)
    if problems:
        return 1
    print(f"chromium libs hold: {len(libs)} packages, Playwright {pin}'s own for {', '.join(distros)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
