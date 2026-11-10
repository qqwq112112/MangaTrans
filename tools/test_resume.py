# -*- coding: utf-8 -*-
"""Full app-level test of 断点记忆: open -> translate -> quit -> relaunch -> resume.

Drives the real MainWindow, including closeEvent, so what is verified here is
exactly what a user experiences.

Run: python tools/test_resume.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangatrans.project_store import ProjectStore  # noqa: E402
from mangatrans.textrender import RegionOp  # noqa: E402
from mangatrans.theme import apply_theme  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def make_window(store: ProjectStore, data_dir: Path):
    """Build a MainWindow whose store writes into the temp dir."""
    import mangatrans.main_window as mw

    original = mw.ProjectStore
    mw.ProjectStore = lambda: ProjectStore(data_dir / "projects.json",
                                           data_dir / "thumbs")
    try:
        window = mw.MainWindow()
    finally:
        mw.ProjectStore = original
    window.store = store
    window._refresh_library_button()
    return window


def add_op_for(doc, page: int, text: str) -> None:
    op = RegionOp(
        rect=QRectF(0.15, 0.12, 0.60, 0.22),
        fill_color=QColor("#FFFFFF"),
        text=text,
        font_family="Noto Sans SC",
        auto_fit=True,
        fill_shape="ellipse",
    )
    doc.add_op(page, op)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    tmp = Path(tempfile.mkdtemp(prefix="mgt_resume_"))
    zip_path = ROOT / "samples" / "sample_manga.zip"

    try:
        print("[1] 首次打开 → 自动入库")
        store = ProjectStore(tmp / "projects.json", tmp / "thumbs")
        win = make_window(store, tmp)
        win.open_path(zip_path)
        app.processEvents()
        check("文档已载入", win.doc is not None and win.doc.page_count == 3)
        check("已生成项目 id", bool(win.project_id), str(win.project_id))
        project = store.get(win.project_id)
        check("项目已入库", project is not None)
        check("记录页数", project.page_count == 3, str(project.page_count))
        check("缩略图已存", store.thumbnail_path(project) is not None)
        # The label is deliberately short ("项目 1") so it never gets elided
        # in a narrow header; the full text lives in the tooltip.
        check("库按钮显示数量", "1" in win.btn_library.text(),
              win.btn_library.text())
        check("空状态有最近入口", len(win.empty._recent_projects) == 1)

        print("[2] 翻译两页 + 翻到第 2 页")
        add_op_for(win.doc, 0, "第一页的译文")
        add_op_for(win.doc, 0, "第一页第二处")
        add_op_for(win.doc, 1, "第二页的译文")
        win.canvas.refresh_page(0)
        win.canvas.refresh_page(1)
        win.canvas.go_to_page(1)
        app.processEvents()
        win.save_progress(silent=True)
        saved = store.get(win.project_id)
        check("页码已保存", saved.last_page == 1, str(saved.last_page))
        check("三处翻译已保存", saved.translated_regions == 3,
              str(saved.translated_regions))
        check("覆盖两页", saved.translated_pages == 2, str(saved.translated_pages))

        print("[3] 关闭窗口（closeEvent 自动保存）")
        win.canvas.go_to_page(2)
        app.processEvents()
        win.close()
        app.processEvents()
        after_close = ProjectStore(tmp / "projects.json", tmp / "thumbs")
        p2 = after_close.get(win.project_id)
        check("关闭时保存了最终页码", p2.last_page == 2, str(p2.last_page))
        pid = win.project_id

        print("[4] 重新启动 → 恢复断点")
        store2 = ProjectStore(tmp / "projects.json", tmp / "thumbs")
        win2 = make_window(store2, tmp)
        win2.open_path(zip_path, restore=True)
        app.processEvents()
        check("恢复到最后阅读页", win2.canvas.current == 2, str(win2.canvas.current))
        check("第 1 页 2 处译文", len(win2.doc.pages[0].ops) == 2,
              str(len(win2.doc.pages[0].ops)))
        check("第 2 页 1 处译文", len(win2.doc.pages[1].ops) == 1,
              str(len(win2.doc.pages[1].ops)))
        check("译文内容正确", win2.doc.pages[0].ops[0].text == "第一页的译文",
              win2.doc.pages[0].ops[0].text)
        check("恢复的不是撤销栈", not win2.doc.can_undo)
        check("同一项目 id", win2.project_id == pid, f"{win2.project_id} / {pid}")
        check("状态栏提示恢复", "恢复" in win2.statusBar().currentMessage(),
              win2.statusBar().currentMessage()[:40])

        print("[5] 从头打开（忽略进度）")
        win2.open_path(zip_path, restore=False)
        app.processEvents()
        check("从头打开不应用译文", len(win2.doc.pages[0].ops) == 0,
              str(len(win2.doc.pages[0].ops)))
        check("从头打开回到第 1 页", win2.canvas.current == 0, str(win2.canvas.current))
        # Opening without restore must NOT erase the saved progress on its own.
        check("进度未被清空", len(store2.get(pid).ops) == 2, str(len(store2.get(pid).ops)))

        print("[5b] 从头打开后真正编辑 → 才覆盖旧进度")
        add_op_for(win2.doc, 0, "全新的一版译文")
        win2.canvas.refresh_page(0)
        win2._edited_since_open = True
        win2.save_progress(silent=True)
        replaced = store2.get(pid)
        check("编辑后覆盖为新内容", replaced.translated_regions == 1,
              str(replaced.translated_regions))
        check("新译文生效",
              replaced.ops_for_page(0)[0].text == "全新的一版译文",
              replaced.ops_for_page(0)[0].text)
        win2.close()
        app.processEvents()

        print("[6] 切换文件时保存上一本")
        store3 = ProjectStore(tmp / "projects.json", tmp / "thumbs")
        win3 = make_window(store3, tmp)
        win3.open_path(zip_path)
        add_op_for(win3.doc, 0, "切换前加的译文")
        win3.canvas.go_to_page(1)
        app.processEvents()
        other = ROOT / "samples" / "sample_manga_ja.zip"
        win3.open_path(other)          # switching books
        app.processEvents()
        first = store3.get(pid)
        check("切书时保存了上一本", first.translated_regions >= 1,
              str(first.translated_regions))
        check("切书后是新项目", win3.project_id != pid)
        check("库里有两本", len(store3.projects) == 2, str(len(store3.projects)))
        win3.close()
        app.processEvents()

        print("[7] 项目库对话框")
        from mangatrans.library_dialog import LibraryDialog

        store4 = ProjectStore(tmp / "projects.json", tmp / "thumbs")
        dlg = LibraryDialog(store4)
        dlg.show()
        app.processEvents()
        check("列表有 2 个项目", dlg.project_list.count() == 2,
              str(dlg.project_list.count()))
        check("分类含全部+未分类", dlg.cat_list.count() == 2, str(dlg.cat_list.count()))
        dlg.search.setText("ja")
        app.processEvents()
        check("搜索过滤生效", dlg.project_list.count() == 1,
              str(dlg.project_list.count()))
        dlg.search.clear()
        app.processEvents()
        check("清空搜索恢复", dlg.project_list.count() == 2)
        dlg.project_list.setCurrentRow(0)
        check("有选中项目时可继续", dlg.btn_resume.isEnabled())
        dlg.close()

        print("[8] 文件被移走后")
        store5 = ProjectStore(tmp / "projects.json", tmp / "thumbs")
        missing_proj = next(p for p in store5.all())
        check("exists 判定可用", missing_proj.exists)
        missing_proj.source = str(tmp / "gone.zip")
        check("缺失后 exists 为假", not missing_proj.exists)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
        return 1
    print("断点记忆集成测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
