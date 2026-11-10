# -*- coding: utf-8 -*-
"""Rebuild every distributable and verify each one contains the current code.

Why this exists
---------------
Three separate PyInstaller command lines were being run by hand, and more than
once only one or two of them got rebuilt. The OCR build then stayed at an older
commit and still showed the old native dialogs. This script builds all targets
and asserts that each produced exe embeds the current module set, so a partial
rebuild is impossible to miss.

Usage:
    python tools/build_all.py            # build all
    python tools/build_all.py --check    # only verify existing builds
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
# Where the portable build is deployed. Override with MGT_PORTABLE_DEST.
PORTABLE_DEST = pathlib.Path(
    os.environ.get("MGT_PORTABLE_DEST", "") or
    (ROOT.parent / "MangaTrans-Portable"))

# Every build must ship these modules; if a build is stale it will be missing.
REQUIRED_MODULES = ("mangatrans.notify", "mangatrans.history", "mangatrans.ocr")

COMMON_EXCLUDES = [
    "--exclude-module", "tkinter",
    "--exclude-module", "numpy",
    "--exclude-module", "cv2",
    "--exclude-module", "fitz",
    "--exclude-module", "torch",
    "--exclude-module", "transformers",
    "--exclude-module", "manga_ocr",
    "--exclude-module", "unidic_lite",
    "--exclude-module", "PySide6.Qt3DAnimation",
    "--exclude-module", "PySide6.Qt3DCore",
    "--exclude-module", "PySide6.Qt3DExtras",
    "--exclude-module", "PySide6.Qt3DInput",
    "--exclude-module", "PySide6.Qt3DLogic",
    "--exclude-module", "PySide6.Qt3DRender",
    "--exclude-module", "PySide6.QtBluetooth",
    "--exclude-module", "PySide6.QtCharts",
    "--exclude-module", "PySide6.QtDataVisualization",
    "--exclude-module", "PySide6.QtDesigner",
    "--exclude-module", "PySide6.QtGraphs",
    "--exclude-module", "PySide6.QtHelp",
    "--exclude-module", "PySide6.QtMultimedia",
    "--exclude-module", "PySide6.QtMultimediaWidgets",
    "--exclude-module", "PySide6.QtNetworkAuth",
    "--exclude-module", "PySide6.QtNfc",
    "--exclude-module", "PySide6.QtPdf",
    "--exclude-module", "PySide6.QtPdfWidgets",
    "--exclude-module", "PySide6.QtPositioning",
    "--exclude-module", "PySide6.QtQml",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "PySide6.QtQuick3D",
    "--exclude-module", "PySide6.QtQuickControls2",
    "--exclude-module", "PySide6.QtQuickWidgets",
    "--exclude-module", "PySide6.QtRemoteObjects",
    "--exclude-module", "PySide6.QtScxml",
    "--exclude-module", "PySide6.QtSensors",
    "--exclude-module", "PySide6.QtSerialBus",
    "--exclude-module", "PySide6.QtSerialPort",
    "--exclude-module", "PySide6.QtSpatialAudio",
    "--exclude-module", "PySide6.QtSql",
    "--exclude-module", "PySide6.QtStateMachine",
    "--exclude-module", "PySide6.QtTest",
    "--exclude-module", "PySide6.QtTextToSpeech",
    "--exclude-module", "PySide6.QtUiTools",
    "--exclude-module", "PySide6.QtWebChannel",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineQuick",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.QtWebSockets",
]

# The exe icon (taskbar / file explorer) plus the assets folder that the window
# icon loads at runtime.
ICON_ARGS = [
    "--icon", "assets\\icon.ico",
    "--add-data", "assets\\icon.ico;assets",
    "--add-data", "assets\\icon_256.png;assets",
]

TARGETS = {
    "MangaTrans": {
        "label": "精简版",
        "args": ICON_ARGS + [
            "--add-data", "tools\\win_ocr.ps1;tools",
            "--add-data", "tools\\ocr_worker.py;tools",
            "--collect-all", "zhconv",
        ] + COMMON_EXCLUDES,
    },
    "MangaTrans-Portable": {
        "label": "便携版",
        "args": ICON_ARGS + [
            "--add-data", "tools\\win_ocr.ps1;tools",
            "--add-data", "tools\\ocr_worker.py;tools",
            "--collect-all", "zhconv",
        ] + COMMON_EXCLUDES,
    },
    "MangaTrans-OCR": {
        "label": "全内置OCR版",
        "args": ICON_ARGS + [
            "--add-data", "tools\\win_ocr.ps1;tools",
            "--collect-all", "manga_ocr",
            "--collect-all", "unidic_lite",
            "--collect-all", "zhconv",
            "--collect-submodules", "transformers",
            "--exclude-module", "tkinter",
        ],
    },
}


def bundle_modules(exe: pathlib.Path) -> set[str]:
    """Return the module names embedded in an exe's PYZ archive."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    reader = CArchiveReader(str(exe))
    pyz_entries = [n for n in reader.toc if "PYZ" in n.upper()]
    if not pyz_entries:
        return set()
    tmp = pathlib.Path(tempfile.gettempdir()) / "_mgt_buildcheck.pyz"
    tmp.write_bytes(reader.extract(pyz_entries[0]))
    try:
        return set(ZlibArchiveReader(str(tmp)).toc.keys())
    finally:
        tmp.unlink(missing_ok=True)


def newest_source_mtime() -> float:
    files = list((ROOT / "mangatrans").glob("*.py")) + [ROOT / "main.py"]
    return max(f.stat().st_mtime for f in files)


def verify(exe: pathlib.Path, label: str, source_mtime: float) -> bool:
    if not exe.exists():
        print(f"  [{label}] 缺少 {exe}")
        return False
    mtime = exe.stat().st_mtime
    stamp = dt.datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")
    stale = mtime < source_mtime
    mods = bundle_modules(exe)
    missing = [m for m in REQUIRED_MODULES if m not in mods]
    ok = not stale and not missing
    status = "OK " if ok else "BAD"
    print(f"  [{status}] {label:12} {stamp}  模块={len(mods)}"
          + (f"  缺少={missing}" if missing else "")
          + ("  早于源码!" if stale else ""))
    return ok


def build(name: str, spec: dict) -> int:
    print(f"\n=== 构建 {spec['label']} ({name}) ===")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--windowed", "--name", name] + spec["args"] + ["main.py"]
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def deploy_portable() -> None:
    src = DIST / "MangaTrans-Portable"
    if not src.exists():
        print("  便携版构建缺失，跳过部署")
        return
    PORTABLE_DEST.mkdir(parents=True, exist_ok=True)
    for item in (src / "MangaTrans-Portable.exe",):
        (PORTABLE_DEST / item.name).write_bytes(item.read_bytes())
    internal_src = src / "_internal"
    internal_dst = PORTABLE_DEST / "_internal"
    if internal_dst.exists():
        shutil_rmtree(internal_dst)
    import shutil
    shutil.copytree(internal_src, internal_dst)

    # The data folder holds settings, API keys and reading progress from THIS
    # machine. Shipping it would leak local absolute paths and credentials, so a
    # deploy always wipes it - the app recreates it on first run.
    stale = PORTABLE_DEST / "data"
    if stale.exists():
        shutil_rmtree(stale)
        print("  已清除本机 data/（含进度与 API Key）")
    print(f"  已部署到 {PORTABLE_DEST}")


def shutil_rmtree(path: pathlib.Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验已有构建，不重新打包")
    args = ap.parse_args()

    source_mtime = newest_source_mtime()
    print("源码最新修改:",
          dt.datetime.fromtimestamp(source_mtime).strftime("%m-%d %H:%M:%S"))

    if not args.check:
        failed = []
        for name, spec in TARGETS.items():
            if build(name, spec) != 0:
                failed.append(name)
        if failed:
            print(f"\n构建失败: {failed}")
            return 1
        deploy_portable()

    print("\n=== 校验 ===")
    ok = True
    for name, spec in TARGETS.items():
        exe = DIST / name / f"{name}.exe"
        ok &= verify(exe, spec["label"], source_mtime)
    portable_exe = PORTABLE_DEST / "MangaTrans-Portable.exe"
    if portable_exe.exists():
        ok &= verify(portable_exe, "便携版(已部署)", source_mtime)

    print("\n全部为最新构建" if ok else "\n有构建过期或不完整")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
