"""Fail on floating sources or registry downloads without integrity, including nested pins."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
lock = json.loads((root / "docker/pi-lab/package-lock.json").read_text(encoding="utf-8"))
revision = "1559b5cb12c72da4a485bc50fe326586b216fb19"
for name, package in lock["packages"].items():
    if not name:
        continue
    source = package.get("resolved", "")
    if name == "node_modules/sol-pi":
        assert source.endswith("#" + revision), source
    else:
        assert source.startswith("https://registry.npmjs.org/"), (name, source)
        assert package.get("integrity", "").startswith("sha512-"), name
print(f"Verified {len(lock['packages']) - 1} locked packages and upstream commit.")
