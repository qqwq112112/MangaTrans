# -*- coding: utf-8 -*-
"""把 Release 用 zip 切成不超过上限的分卷，并生成一键合并脚本。

某些上传途径（GitHub 网页"上传文件"、部分企业网络）单文件上限只有 25 MB，
而三个构建压缩后是 68.5 / 68.5 / 337.9 MB，必须切分。

这里用**纯字节切分**而不是 Bandizip 的 zip 分卷（.z01/.z02/.zip）：
后者最后一块叫 .zip，用户容易误以为单独能解压，实际必须凑齐全部。
字节分卷命名带序号（.part01 ...），合并后与原始 zip 逐字节相同。

产物:
    <名>.zip.part01 ... .partNN     每个不超过 PART_BYTES
    合并并解压.bat                  自动 copy /b 拼回并用 PowerShell 解压

用法:
    python tools/split_assets.py            # 切分 release-assets/*.zip
    python tools/split_assets.py --verify   # 只校验已有分卷能否还原
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "release-assets"

# 24,000,000 字节 ≈ 22.9 MiB / 24.0 MB。故意取整十进制，这样无论
# 平台上限按 25 MB(10^6) 还是 25 MiB(2^20) 算，都不会超。
PART_BYTES = 24_000_000

# GitHub 的网页上传接口只接受白名单扩展名：.part01 / .bat 都会被拒，
# 报 "We don't support that file type."。分卷和脚本因此统一加 `.txt` 后缀
# —— .txt 在列表里，且不影响 copy /b 拼接（内容仍是二进制）。
PART_EXT = ".txt"
MERGE_NAME = "合并并解压.bat" + PART_EXT

BAT_HEADER = """@echo off
chcp 936 >nul
title MangaTrans 分卷合并
cd /d "%~dp0"

echo ============================================
echo   MangaTrans 分卷合并工具
echo   分卷上限 25 MB，必须全部下载才能还原
echo ============================================
echo.
"""
BAT_FOOTER = """
echo.
echo ============================================
echo   处理完成
echo ============================================
echo.
echo 解压出的文件夹可直接双击其中的 exe 运行。
echo 如果提示缺少文件，请确认分卷是否下载齐全。
echo.
pause
exit /b 0

:error
echo.
echo ============================================
echo   处理失败
echo ============================================
echo.
echo 请确认：1) 分卷是否全部下载；2) 分卷后缀是否为 .part01 起。
echo 重新下载缺失的分卷后，再次运行本脚本即可。
echo.
pause
exit /b 1
"""


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def split_one(src: pathlib.Path) -> list[pathlib.Path]:
    """切成 PART_BYTES 大小的分卷，返回分卷列表。

    Output always lands in ASSETS (the upload folder), never beside `src`:
    the source zips are parked under _original_zips/ and the parts must not
    follow them in there.
    """
    for old in ASSETS.glob(src.name + ".part*"):
        old.unlink()

    total = src.stat().st_size
    parts: list[pathlib.Path] = []
    with src.open("rb") as fh:
        index = 1
        while True:
            chunk = fh.read(PART_BYTES)
            if not chunk:
                break
            part = ASSETS / f"{src.name}.part{index:02d}{PART_EXT}"
            part.write_bytes(chunk)
            parts.append(part)
            index += 1

    print(f"  {src.name}")
    print(f"    {total:,} 字节 → {len(parts)} 个分卷")
    for p in parts:
        size = p.stat().st_size
        flag = "OK " if size <= PART_BYTES else "BAD"
        print(f"      [{flag}] {p.name:46} {size:>12,} 字节")
    return parts


def verify_one(src: pathlib.Path, parts: list[pathlib.Path]) -> bool:
    """把分卷拼回内存，与原始 zip 比对哈希。"""
    h = hashlib.sha256()
    for p in parts:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    joined_size = sum(p.stat().st_size for p in parts)
    ok = (h.hexdigest() == sha256(src)) and (joined_size == src.stat().st_size)
    mark = "OK " if ok else "BAD"
    print(f"    [{mark}] 还原校验 {len(parts)} 卷 / {joined_size:,} 字节 / "
          f"sha256 {h.hexdigest()[:16]}…")
    return ok


def write_bat(items: list[tuple[pathlib.Path, list[pathlib.Path]]]) -> pathlib.Path:
    """生成合并脚本：用 PowerShell 按文件名排序拼接 + 解压。

    `copy /b a.part01.txt+b.part02.txt` 也试过，但 cmd 的通配符形式
    （`copy /b x.part*.txt out`）实测只复制了第一个文件，不可靠；
    显式列举又会在卷数变化时失效。PowerShell 的 Sort-Object Name 配合
    两位零填充（part01…part15），字典序即正确顺序。
    """
    lines = [BAT_HEADER]
    for src, parts in items:
        stem = src.name
        folder = stem[:-4] if stem.lower().endswith(".zip") else stem
        lines.append(f'echo [1/2] 合并 {stem} 的 {len(parts)} 个分卷…')
        lines.append(
            'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
            f"$o=[IO.File]::Create('%~dp0{stem}');"
            f"Get-ChildItem '%~dp0{stem}.part*.txt' | Sort-Object Name | "
            'ForEach-Object { $i=$_.OpenRead(); $i.CopyTo($o); $i.Close() };'
            '$o.Close(); '
            f'if ((Get-Item \'%~dp0{stem}\').Length -ne {src.stat().st_size}) '
            '{ exit 1 }"'
        )
        lines.append('if errorlevel 1 (')
        lines.append(f'    echo    [失败] 合并出错，请检查 {stem} 的分卷是否齐全。')
        lines.append('    goto :error')
        lines.append(')')
        lines.append(f'echo    [完成] {stem}')
        lines.append('')
        lines.append(f'echo [2/2] 解压 {stem}…')
        # The zip already contains a single top-level folder named after the
        # build, so extract into the current directory. Extracting into a
        # same-named subfolder would nest it one level deeper.
        lines.append(
            'powershell -NoProfile -ExecutionPolicy Bypass -Command '
            f'"Expand-Archive -LiteralPath \'%~dp0{stem}\' '
            '-DestinationPath \'%~dp0\' -Force"'
        )
        lines.append('if errorlevel 1 (')
        lines.append(f'    echo    [失败] 解压 {stem} 出错。')
        lines.append('    goto :error')
        lines.append(')')
        lines.append(f'echo    [完成] 已解压到 {folder}\\')
        lines.append('')
        lines.append(f'echo    SHA256（可用 certutil 复核）: {sha256(src)}')
        lines.append('')

    bat = ASSETS / MERGE_NAME
    bat.write_text("\n".join(lines) + BAT_FOOTER, encoding="gbk", newline="\r\n")
    return bat


def find_sources() -> list[pathlib.Path]:
    """Original zips live either beside the assets or in the _original_zips/
    holding pen (moved there so they cannot be uploaded by accident)."""
    for folder in (ASSETS / "_original_zips", ASSETS):
        found = sorted(folder.glob("*.zip"))
        if found:
            return found
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="只校验已有分卷，不重新切分")
    args = ap.parse_args()

    sources = find_sources()
    if not sources:
        print(f"{ASSETS} 下没有 zip，先跑 tools/package_binaries.py")
        return 1

    items: list[tuple[pathlib.Path, list[pathlib.Path]]] = []
    ok = True

    print(f"分卷上限 {PART_BYTES:,} 字节，扩展名 {PART_EXT}")
    for src in sources:
        print()
        if args.verify:
            parts = sorted(ASSETS.glob(src.name + ".part*" + PART_EXT))
            if not parts:
                print(f"  {src.name}: 没有分卷，跳过")
                continue
        else:
            parts = split_one(src)
        if not verify_one(src, parts):
            ok = False
        items.append((src, parts))

    if not args.verify:
        bat = write_bat(items)
        print(f"\n已生成 {bat.name}（下载后去掉末尾的 .txt 再双击）")

    total_parts = sum(len(p) for _, p in items)
    biggest = max((q.stat().st_size for _, ps in items for q in ps), default=0)
    print(f"\n合计 {total_parts} 个分卷，最大单卷 {biggest:,} 字节 "
          f"({biggest / 1_000_000:.1f} MB)")
    print("全部低于 25 MB 上限" if ok and biggest <= PART_BYTES else "有分卷超限或校验失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
