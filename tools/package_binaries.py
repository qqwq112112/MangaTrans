# -*- coding: utf-8 -*-
"""把三个 PyInstaller 构建目录打成可直接上传 GitHub Releases 的压缩包。

GitHub Releases 单个附件上限 2 GB。实测三个构建压缩后都远低于该值，
所以正常情况下每个版本就是一个 zip，不分卷；只有当某个包超过
`MAX_ASSET_MB` 时才会自动改成 Bandizip 分卷，避免上传被拒。

用法:
    python tools/package_binaries.py                # 打包全部三个版本
    python tools/package_binaries.py --only ocr     # 只打某一个
    python tools/package_binaries.py --check        # 只校验已有产物

产物输出到 <项目根>/release-assets/。
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT = ROOT / "release-assets"

VERSION = "1.0.0"

# GitHub Releases 硬上限 2048 MB；留 148 MB 余量给上传时的 multipart 开销。
MAX_ASSET_MB = 1900

# Bandizip 控制台工具。本机装在"图吧工具箱"下（见 DEV-ENVIRONMENT.md）。
BZ_CANDIDATES = [
    r"C:\图吧工具箱\Bandizip\bz.exe",
    r"C:\Program Files\Bandizip\bz.exe",
    r"C:\Program Files (x86)\Bandizip\bz.exe",
]

# 便携模式靠 exe 同级的 portable.txt 判定（mangatrans/config.py::portable_root）。
# 该文件必须随包分发，否则便携版会退化成写 %APPDATA%。
PORTABLE_MARKER = """Portable mode marker

All settings, translation progress and caches are stored in the data folder
next to this file, so the whole directory can be copied to another machine
or a USB stick and keeps working.

Remove this file to fall back to:
    %APPDATA%/MangaTrans
"""

VARIANTS = {
    "slim": {
        "label": "精简版",
        "dist": "MangaTrans",
        "exe": "MangaTrans.exe",
        "folder": f"MangaTrans-{VERSION}-slim-win64",
        "docs": ["README.md"],
        "marker": False,
        "note": "日文 OCR 需本机 pip install manga-ocr；中/英用系统 OCR",
    },
    "portable": {
        "label": "便携版",
        "dist": "MangaTrans-Portable",
        "exe": "MangaTrans-Portable.exe",
        "folder": f"MangaTrans-{VERSION}-portable-win64",
        "docs": ["README.md", "使用说明.txt"],
        "marker": True,
        "note": "免安装免依赖；数据存在程序目录的 data/ 内",
    },
    "ocr": {
        "label": "全内置OCR版",
        "dist": "MangaTrans-OCR",
        "exe": "MangaTrans-OCR.exe",
        "folder": f"MangaTrans-{VERSION}-ocr-win64",
        "docs": ["README.md", "MangaTrans-OCR-使用指南.md"],
        "marker": False,
        "note": "内置 manga-ocr + PyTorch；模型权重首次识别时下载",
    },
}


def find_bz() -> pathlib.Path:
    for c in BZ_CANDIDATES:
        p = pathlib.Path(c)
        if p.is_file():
            return p
    raise SystemExit("找不到 Bandizip 控制台工具 bz.exe，请检查 DEV-ENVIRONMENT.md")


def stage(key: str) -> pathlib.Path:
    """把构建目录抄进 staging/<folder>/，允许顺手补必要文件。"""
    spec = VARIANTS[key]
    src = DIST / spec["dist"]
    if not (src / spec["exe"]).exists():
        raise SystemExit(f"{spec['label']}构建缺失：{src / spec['exe']}")

    stage_root = OUT / "_stage"
    dest = stage_root / spec["folder"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # _internal 是 PyInstaller onedir 的运行库，必须整个带走。
    shutil.copytree(src / "_internal", dest / "_internal")
    shutil.copy2(src / spec["exe"], dest / spec["exe"])

    for doc in spec["docs"]:
        p = ROOT / doc
        if not p.is_file():
            print(f"  [warn] 缺少文档 {doc}，跳过")
            continue
        shutil.copy2(p, dest / doc)

    if spec["marker"]:
        (dest / "portable.txt").write_text(PORTABLE_MARKER, encoding="utf-8-sig")

    total = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    n = sum(1 for f in dest.rglob("*") if f.is_file())
    print(f"  暂存 {n} 个文件 / {total / 1048576:.1f} MB → {dest}")
    return dest


def archive(bz: pathlib.Path, folder: pathlib.Path, out: pathlib.Path) -> list[pathlib.Path]:
    """压缩成单个 zip；超过 MAX_ASSET_MB 时自动改用分卷。"""
    if out.exists():
        out.unlink()
    cmd = [str(bz), "c", "-fmt:zip", "-l:9", "-y", str(out), folder.name]
    subprocess.run(cmd, cwd=str(folder.parent), check=True, stdout=subprocess.DEVNULL)

    size_mb = out.stat().st_size / 1048576
    if size_mb <= MAX_ASSET_MB:
        return [out]

    print(f"  {size_mb:.0f} MB 超过 {MAX_ASSET_MB} MB，改用分卷…")
    out.unlink()
    cmd = [str(bz), "c", "-fmt:zip", "-l:9", "-y", f"-v:{MAX_ASSET_MB}MB",
           str(out), folder.name]
    subprocess.run(cmd, cwd=str(folder.parent), check=True, stdout=subprocess.DEVNULL)
    return sorted(p for p in out.parent.glob(out.name + ".*"))


def verify(bz: pathlib.Path, parts: list[pathlib.Path], key: str) -> bool:
    """完整性测试 + 关键路径检查 + 确认没有把本机 data/ 打进去。"""
    spec = VARIANTS[key]
    ok = True
    for p in parts:
        r = subprocess.run([str(bz), "t", str(p)], capture_output=True)
        if r.returncode != 0:
            print(f"  [BAD] 完整性测试失败: {p.name}")
            ok = False

    listing = subprocess.run([str(bz), "l", str(parts[0])],
                             capture_output=True, text=True, errors="ignore").stdout
    required = [f"{spec['folder']}/{spec['exe']}", f"{spec['folder']}/_internal"]
    for item in required:
        if item.replace("/", "\\") not in listing and item not in listing:
            print(f"  [BAD] 包内缺少 {item}")
            ok = False
    if spec["marker"] and "portable.txt" not in listing:
        print("  [BAD] 便携包缺少 portable.txt")
        ok = False
    for banned in ("/data/config.json", "/data/projects.json", "\\data\\config.json"):
        if banned in listing:
            print(f"  [BAD] 包内混入本机数据 {banned}")
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(VARIANTS), action="append",
                    help="只处理指定版本（可重复）")
    ap.add_argument("--check", action="store_true", help="只校验已有产物，不重新打包")
    args = ap.parse_args()

    keys = args.only or list(VARIANTS)
    OUT.mkdir(exist_ok=True)
    bz = find_bz()

    results: list[tuple[str, list[pathlib.Path]]] = []
    all_ok = True

    for key in keys:
        spec = VARIANTS[key]
        print(f"\n=== {spec['label']} ({spec['folder']}) ===")
        print(f"  说明: {spec['note']}")
        name = spec["folder"] + ".zip"
        out = OUT / name

        if not args.check:
            folder = stage(key)
            parts = archive(bz, folder, out)
        else:
            parts = sorted(OUT.glob(name + "*"))
            if not parts:
                print("  [skip] 尚无产物，先去掉 --check 打包一次")
                continue

        for p in parts:
            print(f"  产物 {p.name}  {p.stat().st_size / 1048576:.1f} MB")
        if not verify(bz, parts, key):
            all_ok = False
        results.append((spec["label"], parts))

    # staging 只是中间产物，打包完就清掉，免得误上传
    staging = OUT / "_stage"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)

    print("\n=== 汇总 ===")
    for label, parts in results:
        total = sum(p.stat().st_size for p in parts)
        kind = "分卷" if len(parts) > 1 else "单文件"
        print(f"  {label:10} {len(parts)} 个文件 {kind}  合计 {total / 1048576:.1f} MB")

    print("\n上传方式：GitHub → Releases → Draft a new release → 拖入本目录的 zip 附件")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
