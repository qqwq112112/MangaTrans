# -*- coding: utf-8 -*-
"""Tests for project memory (断点记忆): persistence, progress restore, categories.

Run: python tools/test_projects.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.archive import load_input_images  # noqa: E402
from mangatrans.document import Document, PageModel  # noqa: E402
from mangatrans.project_store import (  # noqa: E402
    ALL_CATEGORY,
    DEFAULT_CATEGORY,
    ProjectStore,
    op_from_dict,
    op_to_dict,
    source_id,
)
from mangatrans.textrender import RegionOp  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_doc(zip_path: Path) -> Document:
    images, title = load_input_images(zip_path)
    return Document([PageModel(p) for p in images], zip_path, title)


def sample_op(text: str = "测试译文", page_w: int = 1000) -> RegionOp:
    return RegionOp(
        rect=QRectF(0.1, 0.2, 0.5, 0.25),
        fill_color=QColor("#FAF6EC"),
        text=text,
        font_family="Noto Sans SC",
        font_ratio=32 / page_w,
        bold=True,
        text_color=QColor("#111111"),
        line_spacing=1.2,
        padding=0.05,
        auto_fit=True,
        fill_shape="ellipse",
        fill_soft=0.012,
    )


def test_op_roundtrip() -> None:
    print("[1] 区域序列化往返")
    op = sample_op()
    restored = op_from_dict(json.loads(json.dumps(op_to_dict(op))))
    check("矩形一致", abs(restored.rect.x() - op.rect.x()) < 1e-9
          and abs(restored.rect.width() - op.rect.width()) < 1e-9)
    check("译文一致", restored.text == op.text, restored.text)
    check("字体一致", restored.font_family == op.font_family)
    check("填充色一致", restored.fill_color.name() == op.fill_color.name(),
          restored.fill_color.name())
    check("椭圆形状保留", restored.fill_shape == "ellipse", restored.fill_shape)
    check("羽化保留", abs(restored.fill_soft - op.fill_soft) < 1e-9, restored.fill_soft)
    check("加粗保留", restored.bold is True)
    check("缺字段不崩", op_from_dict({}).fill_shape == "rect")


def test_progress_roundtrip(tmp: Path) -> None:
    print("[2] 进度保存 → 重开 → 恢复")
    zip_path = ROOT / "samples" / "sample_manga.zip"
    store = ProjectStore(tmp / "projects.json", tmp / "thumbs")
    doc = make_doc(zip_path)

    doc.add_op(0, sample_op("第一页译文"))
    doc.add_op(0, sample_op("第一页第二处"))
    doc.add_op(2, sample_op("第三页译文"))

    project = store.touch(zip_path, doc.title, "archive", doc.page_count)
    check("项目已入库", project.id in store.projects)
    check("页数正确", project.page_count == 3, str(project.page_count))

    pix = QPixmap(200, 280)
    pix.fill(QColor("#336699"))
    saved = store.save_progress(project.id, doc, page_index=2,
                                reading_mode="vertical", thumb=pix)
    check("保存返回项目", saved is not None)
    check("页码已记住", saved.last_page == 2, str(saved.last_page))
    check("阅读模式已记住", saved.reading_mode == "vertical", saved.reading_mode)
    check("翻译数正确", saved.translated_regions == 3, str(saved.translated_regions))
    check("覆盖页数正确", saved.translated_pages == 2, str(saved.translated_pages))
    check("缩略图已生成", store.thumbnail_path(saved) is not None)
    check("进度比例", abs(saved.progress_ratio - 2 / 3) < 1e-6,
          f"{saved.progress_ratio:.3f}")

    # Reopen from disk: a new process would do exactly this.
    store2 = ProjectStore(tmp / "projects.json", tmp / "thumbs")
    reloaded = store2.get(project.id)
    check("重读后项目存在", reloaded is not None)
    check("重读后页码保留", reloaded.last_page == 2, str(reloaded.last_page))
    ops0 = reloaded.ops_for_page(0)
    ops2 = reloaded.ops_for_page(2)
    check("重读后第 1 页有 2 处", len(ops0) == 2, str(len(ops0)))
    check("重读后第 3 页有 1 处", len(ops2) == 1, str(len(ops2)))
    check("译文内容正确", ops0[0].text == "第一页译文", ops0[0].text)
    check("椭圆形状保留", ops0[0].fill_shape == "ellipse", ops0[0].fill_shape)

    # Apply to a fresh document, mimicking open_path(restore=True).
    doc2 = make_doc(zip_path)
    for index in range(doc2.page_count):
        doc2.pages[index].ops.extend(reloaded.ops_for_page(index))
    check("恢复到新文档", len(doc2.pages[0].ops) == 2 and len(doc2.pages[2].ops) == 1,
          f"{len(doc2.pages[0].ops)}/{len(doc2.pages[2].ops)}")
    check("恢复后不写入撤销栈", not doc2.can_undo)
    exported = tmp / "out"
    written = doc2.export_all(exported)
    check("恢复后可直接导出", len(written) == 3, str(len(written)))


def test_categories(tmp: Path) -> None:
    print("[3] 分类管理")
    zip_a = ROOT / "samples" / "sample_manga.zip"
    zip_b = ROOT / "samples" / "sample_manga_ja.zip"
    store = ProjectStore(tmp / "cat.json", tmp / "thumbs")
    pa = store.touch(zip_a, "中文样例", "archive", 3)
    pb = store.touch(zip_b, "日文样例", "archive", 2)

    cid = store.add_category("连载中")
    check("新建分类", cid is not None and store.category_name(cid) == "连载中")
    check("同名分类去重", store.add_category("连载中") == cid)
    check("移动项目", store.set_category(pb.id, cid))
    check("分类过滤正确", [p.id for p in store.by_category(cid)] == [pb.id])
    check("未分类只含 a", [p.id for p in store.by_category(DEFAULT_CATEGORY)] == [pa.id])
    check("全部分类含两本", len(store.by_category(ALL_CATEGORY)) == 2)
    check("计数正确", store.counts().get(cid) == 1)

    check("重命名分类", store.rename_category(cid, "追更"))
    check("重命名生效", store.category_name(cid) == "追更")
    check("未分类不能改名", not store.rename_category(DEFAULT_CATEGORY, "x"))

    store2 = ProjectStore(tmp / "cat.json", tmp / "thumbs")
    check("分类已持久化", store2.category_name(cid) == "追更")
    check("项目分类已持久化", store2.get(pb.id).category == cid)

    check("删除分类", store2.delete_category(cid))
    check("删除后回到未分类", store2.get(pb.id).category == DEFAULT_CATEGORY)
    check("内置分类不能删", not store2.delete_category(DEFAULT_CATEGORY))


def test_remove_and_clear(tmp: Path) -> None:
    print("[4] 清除进度 / 移出项目库")
    zip_path = ROOT / "samples" / "sample_manga.zip"
    store = ProjectStore(tmp / "rm.json", tmp / "thumbs")
    doc = make_doc(zip_path)
    doc.add_op(0, sample_op("x"))
    project = store.touch(zip_path, "样例", "archive", 3)
    pix = QPixmap(100, 140)
    pix.fill(QColor("#123456"))
    store.save_progress(project.id, doc, 1, "horizontal", pix)

    check("清除进度", store.clear_progress(project.id))
    cleared = store.get(project.id)
    check("翻译已清空", cleared.translated_regions == 0)
    check("页码已归零", cleared.last_page == 0)
    check("项目仍在列表", project.id in store.projects)

    check("移出项目库", store.remove(project.id))
    check("记录已删除", store.get(project.id) is None)
    check("原文件未受影响", zip_path.exists())


def test_missing_and_corrupt(tmp: Path) -> None:
    print("[5] 文件缺失与配置损坏容错")
    store = ProjectStore(tmp / "bad.json", tmp / "thumbs")
    ghost = tmp / "不存在.zip"
    project = store.touch(ghost, "幽灵", "archive", 5)
    check("缺失文件可入库", project.id in store.projects)
    check("exists 为假", not store.get(project.id).exists)

    # Corrupt primary file: the .bak copy should keep the library alive.
    # The backup is written by the *second* save (the first has nothing to
    # back up), which is what happens in real use: open, translate, autosave.
    store.save()
    store.get(project.id).last_page = 1
    store.save()
    check("生成了备份文件", store.path.with_suffix(".json.bak").exists())
    store.path.write_text("{ this is not json", encoding="utf-8-sig")
    store2 = ProjectStore(store.path, tmp / "thumbs")
    check("损坏后用备份恢复", len(store2.projects) == 1, str(len(store2.projects)))
    # .bak holds the previous save by design, so the recovered state is one
    # generation old. What matters is that the library is not lost and that
    # the primary file is rewritten so the next start is clean.
    recovered = store2.get(project.id)
    check("备份中项目可读", recovered is not None)
    check("恢复后主文件已自愈",
          "this is not json" not in store.path.read_text(encoding="utf-8-sig"))
    store3 = ProjectStore(store.path, tmp / "thumbs")
    check("二次启动无需回退", len(store3.projects) == 1, str(len(store3.projects)))

    # Garbage ops should be ignored, not crash the loader.
    payload = {
        "version": 1,
        "categories": [{"id": "default", "name": "未分类"}, {"id": "c1", "name": "连载"}],
        "projects": {
            "abc": {
                "id": "abc", "source": str(ROOT / "samples" / "sample_manga.zip"),
                "title": "脏数据", "page_count": 3,
                "ops": {"0": [{"rect": [0, 0, 1, 1], "text": "ok"}],
                        "1": "not-a-list", "2": [None, 5]},
                "category": "不存在的分类",
            }
        },
    }
    bad = tmp / "dirty.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    store3 = ProjectStore(bad, tmp / "thumbs")
    p = store3.get("abc")
    check("脏数据可加载", p is not None)
    check("非法 ops 被丢弃", p is not None and len(p.ops) == 1, str(len(p.ops) if p else None))
    check("未知分类归到未分类", p.category == DEFAULT_CATEGORY, p.category)


def test_source_id_stability() -> None:
    print("[6] 项目 id 稳定性")
    zip_path = ROOT / "samples" / "sample_manga.zip"
    a = source_id(zip_path)
    b = source_id(zip_path)
    check("同一文件 id 稳定", a == b, f"{a} / {b}")
    check("不同文件 id 不同", a != source_id(ROOT / "samples" / "sample_manga_ja.zip"))
    check("大小写/斜杠不敏感", source_id(Path(str(zip_path).upper())) == a)


def main() -> int:
    app = QApplication(sys.argv)   # QPixmap needs an app
    tmp = Path(tempfile.mkdtemp(prefix="mgt_proj_"))
    try:
        test_op_roundtrip()
        test_progress_roundtrip(tmp)
        test_categories(tmp)
        test_remove_and_clear(tmp)
        test_missing_and_corrupt(tmp)
        test_source_id_stability()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        del app

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("断点记忆全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
