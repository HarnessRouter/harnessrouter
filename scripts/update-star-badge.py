#!/usr/bin/env python3
"""Render the README star badge from GitHub's official repository API.

Network/validation failures leave the previous file untouched. The workflow publishes
only this SVG to readme-badges, keeping refresh commits out of the main branch.
"""

import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen


API_URL = "https://api.github.com/repos/HarnessRouter/harnessrouter"
OUTPUT = Path("docs/images/github-stars.svg")


def render(count):
    if type(count) is not int or not 0 <= count <= 999_999_999:
        raise ValueError("Expected a nonnegative integer star count")
    right = max(44, len(str(count)) * 8 + 16)
    width = 73 + right
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" viewBox="0 0 {width} 20" role="img" aria-label="Stars: {count}">
  <title>Stars: {count}</title>
  <desc>Official GitHub repository star count. Refreshed every five minutes when GitHub Actions runs; retains the last successful value if refresh fails.</desc>
  <rect width="{width}" height="20" rx="3" fill="#444c56"/>
  <path fill="#e3b341" d="M73 0h{right-3}a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H73Z"/>
  <path fill="#e3b341" d="m12 3 2.16 4.38L19 8.08l-3.5 3.41.83 4.82L12 14.04l-4.33 2.27.83-4.82L5 8.08l4.84-.7Z"/>
  <g font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">
    <text x="46" y="14" fill="white">Stars</text>
    <text x="{73+right/2:g}" y="14" fill="white">{count}</text>
  </g>
</svg>
'''


def update(output=OUTPUT):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "HarnessRouter-stars"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(API_URL, headers=headers), timeout=20) as response:
        svg = render(json.load(response)["stargazers_count"])
    output = Path(output)
    if output.exists() and output.read_text() == svg:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(svg)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    print("Badge updated" if update() else "Star count unchanged")
