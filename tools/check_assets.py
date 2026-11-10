# -*- coding: utf-8 -*-
"""Check release zips for leaked local data before uploading."""
import pathlib
import re
import subprocess

BZ = r"C:\图吧工具箱\Bandizip\bz.exe"
OUT = pathlib.Path(r"D:\MangaTrans\release-assets")

# Paths that must never appear inside a distributable archive.
BANNED = re.compile(r"data[\\/](config|projects)\.json", re.I)

for z in sorted(OUT.glob("*.zip")):
    res = subprocess.run([BZ, "l", str(z)], capture_output=True,
                         text=True, errors="ignore")
    hits = [ln.strip() for ln in res.stdout.splitlines() if BANNED.search(ln)]
    print(f"{z.name:42} 本机数据命中 {len(hits)} 条")
    for h in hits[:3]:
        print("   ", h)

    # Spot-check that the payload files are present.
    names = res.stdout
    need = ["portable.txt"] if "portable" in z.name else []
    for n in need:
        print(f"    {'有' if n in names else '缺'} {n}")
