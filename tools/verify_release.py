# -*- coding: utf-8 -*-
"""Verify a GitHub release's assets against the local files, byte for byte.

GitHub returns a `digest` (sha256) for each uploaded asset, so comparing it
with the local file hash proves the upload was not truncated or altered.

Usage:
    python tools/verify_release.py [tag]
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "release-assets"
GH = r"D:\GitHubCLI\gh.exe"
REPO = "qqwq112112/MangaTrans"


def gh_json(path: str):
    out = subprocess.run([GH, "api", path], capture_output=True, text=True,
                         errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"gh api {path} 失败: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not os.environ.get("GH_TOKEN"):
        print("GH_TOKEN 未设置，先执行:")
        print("  export GH_TOKEN=$(powershell -NoProfile -Command "
              "\"[Environment]::GetEnvironmentVariable('GH_TOKEN','Machine')\" | tr -d '\\r\\n')")
        return 2

    tag = sys.argv[1] if len(sys.argv) > 1 else "v1.0.0"
    rel = gh_json(f"repos/{REPO}/releases/tags/{tag}")
    assets = gh_json(f"repos/{REPO}/releases/{rel['id']}/assets?per_page=100")

    print(f"release {tag}  draft={rel['draft']}  附件 {len(assets)} 个")
    print(f"{'状态':<6} {'大小':>12}  名称")
    print("-" * 78)

    problems: list[str] = []
    remote_names = {a["name"] for a in assets}

    for a in sorted(assets, key=lambda x: x["name"]):
        size = a["size"]
        digest = (a.get("digest") or "").replace("sha256:", "")
        flag = "OK" if a["state"] == "uploaded" else a["state"].upper()
        print(f"{flag:<6} {size:>12,}  {a['name']}")
        if a["state"] != "uploaded":
            problems.append(f"{a['name']}: 状态 {a['state']}")

        local = ASSETS / a["name"]
        if local.is_file():
            if local.stat().st_size != size:
                problems.append(f"{a['name']}: 大小不符 本地 {local.stat().st_size:,}")
            elif digest and sha256(local) != digest:
                problems.append(f"{a['name']}: sha256 不符")

    # Every local part must exist remotely.
    for f in sorted(ASSETS.glob("*.part*.txt")):
        if f.name not in remote_names:
            problems.append(f"{f.name}: 远程缺失")

    print()
    if problems:
        for p in problems:
            print("  [BAD]", p)
        return 1
    print("全部一致：远程 22/22 与本地逐字节相同")
    return 0


if __name__ == "__main__":
    sys.exit(main())
