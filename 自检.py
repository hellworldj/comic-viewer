# -*- coding: utf-8 -*-
"""工具自检脚本（可重复运行）

    python 自检.py

依次校验：
  1. 生成/补齐「示例图库」（1 2 3 / vol1 vol2 vol10 / 漫画01-03 / 动漫a-b）和一个 zip 包
  2. 自然排序、图片扫描、缩略图缓存
  3. zip 解压读取、旋转 90°、放大缩小
  4. 无窗口启动一次主界面，检查三栏结构与连续长图排版
"""

import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from importlib.machinery import SourceFileLoader

mod = SourceFileLoader("viewer", os.path.join(HERE, "看图工具.pyw")).load_module()

from PIL import Image, ImageDraw

SAMPLE = os.path.join(HERE, "示例图库")
DIRS = ["1", "2", "3", "vol1", "vol2", "vol10", "漫画01", "漫画02", "漫画03",
        "动漫a", "动漫b"]
COLORS = [(210, 80, 80), (80, 160, 90), (80, 120, 200)]
ZIP_NAME = "vol2.zip"


def page_image(label, page, color=(80, 120, 200)):
    im = Image.new("RGB", (620, 880), (245, 245, 245))
    dr = ImageDraw.Draw(im)
    dr.rectangle([8, 8, 611, 871], outline=color, width=4)
    dr.rectangle([24, 24, 595, 90], fill=color)
    dr.text((40, 44), "%s  page %d" % (label, page), fill=(255, 255, 255))
    for k in range(8):
        y = 140 + k * 80
        dr.line([60, y, 560, y], fill=(190, 190, 190), width=2)
    return im


def make_sample():
    os.makedirs(SAMPLE, exist_ok=True)
    for d in DIRS:
        folder = os.path.join(SAMPLE, d)
        os.makedirs(folder, exist_ok=True)
        for p in range(1, 4):
            f = os.path.join(folder, "p%d.png" % p)
            if os.path.exists(f):
                continue
            page_image(d, p, COLORS[DIRS.index(d) % 3]).save(f)
    print("[1] 示例图库就绪：", SAMPLE)


def make_zip():
    zpath = os.path.join(SAMPLE, ZIP_NAME)
    if os.path.exists(zpath):
        return zpath
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in range(1, 4):
            tmp = os.path.join(HERE, "_tmp_zip_page.png")
            page_image("vol2.zip", p, (150, 90, 160)).save(tmp)
            z.write(tmp, "vol2/p%d.png" % p)      # 包里套一层同名文件夹，测自动下钻
            os.remove(tmp)
    print("    已生成测试压缩包：", zpath)
    return zpath


def check_sort():
    got = mod.list_subdirs(SAMPLE)
    print("[2] 扫描到的子文件夹顺序：", got)
    assert got[:6] == ["1", "2", "3", "vol1", "vol2", "vol10"], got
    assert got.index("漫画01") < got.index("漫画02") < got.index("漫画03")
    assert got.index("动漫a") < got.index("动漫b")
    entries = mod.list_entries(SAMPLE)
    kinds = [e[0] for e in entries]
    print("    目录树条目（文件夹在前、压缩包在后）：",
          ["%s:%s" % (e[0], e[1]) for e in entries])
    assert kinds.index("arch") == len([k for k in kinds if k == "dir"]), "压缩包应排在文件夹之后"

    imgs = mod.list_images(os.path.join(SAMPLE, "vol1"))
    assert [os.path.basename(i) for i in imgs] == ["p1.png", "p2.png", "p3.png"]
    print("    排序 OK：vol1 < vol2 < vol10，漫画01 < 02 < 03，动漫a < b")


def check_thumbs():
    imgs = mod.list_images(os.path.join(SAMPLE, "vol1"))
    t0 = time.time()
    for p in imgs:
        tf = mod.make_thumb(p)
        assert os.path.exists(tf) and os.path.getsize(tf) > 0
    t1 = time.time()
    for p in imgs:
        mod.make_thumb(p)
    t2 = time.time()
    print("[3] 缩略图生成 %.0f ms / 缓存复用 %.0f ms" % ((t1 - t0) * 1000, (t2 - t1) * 1000))
    assert t2 - t1 < max(t1 - t0, 0.05)


def check_archives():
    zpath = os.path.join(SAMPLE, ZIP_NAME)
    dest = mod.extract_dir_for(zpath)
    t0 = time.time()
    mod.extract_archive(zpath, dest)
    t1 = time.time()
    imgs = mod.list_images(os.path.join(dest, "vol2"))
    print("[4] zip 解压 %.0f ms → %s" % ((t1 - t0) * 1000, os.path.relpath(dest, HERE)))
    print("    包内图片：", [os.path.basename(i) for i in imgs])
    assert len(imgs) == 3
    t2 = time.time()
    mod.extract_archive(zpath, dest)
    assert time.time() - t2 < 0.2
    print("    rar 解压工具：%s" % (mod.find_unrar() or "未找到（请安装 WinRAR）"))
    print("    7z  解压工具：%s" % (mod.find_7z() or "未找到（请安装 7-Zip）"))

    for name in ("vol10.rar", "漫画01.7z"):
        p = os.path.join(SAMPLE, name)
        if not os.path.exists(p):
            print("    跳过 %s（文件不存在）" % name)
            continue
        d = mod.extract_dir_for(p)
        mod.extract_archive(p, d)
        found = []
        for root, dirs, files in os.walk(d):
            for f in files:
                if mod.is_image_name(f):
                    found.append(os.path.relpath(os.path.join(root, f), d))
        print("    %s → %s" % (name, sorted(found)))
        assert len(found) == 3


def wait(root, sec):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def check_gui():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    app = mod.ViewerApp(root)
    try:
        root.attributes("-alpha", 0.0)
    except Exception:
        pass
    root.deiconify()
    app.open_root(SAMPLE)
    wait(root, 2.0)

    # 选中 vol10 文件夹
    root_item = app.tree.get_children("")[0]
    app._ensure_children(root_item)
    node = None
    for c in app.tree.get_children(root_item):
        if os.path.basename(app.tree_paths.get(c, "")) == "vol10":
            node = c
    app.tree.selection_set(node)
    app.tree.focus(node)
    wait(root, 3.0)
    n = len(app.paths)
    h1 = app.strip_total
    print("[5] vol10：%d 张，连续长图总高 %d px，缩略图 %d 张，缩放 %s"
          % (n, h1, len(app.thumb_photos), app.zoom_var.get()))
    assert n == 3 and h1 > 1000

    # 旋转 90°（整本）：竖图 620x880 转成 880x620，总高度应变小
    app.rotate_page(90)
    wait(root, 0.6)
    h2 = app.strip_total
    print("    整本右转 90° → 总高 %d px，首张角度 %d°"
          % (h2, app.rot.get(app.paths[0], 0)))
    assert app.rot.get(app.paths[0]) == 90
    assert h2 < h1, "旋转后应换成横向、页面变矮"
    app.rotate_page(-90)
    wait(root, 0.4)

    # 放大 / 缩小
    d1 = app.dw
    app.zoom_by(1.25)
    wait(root, 0.5)
    d2 = app.dw
    print("    放大：宽 %d → %d px（%s），总高 %d px" % (d1, d2, app.zoom_var.get(), app.strip_total))
    assert d2 > d1 * 1.15
    app.zoom_by(0.8)
    wait(root, 0.4)
    app.zoom_fit()
    wait(root, 0.4)
    assert abs(app.zoom - 1.0) < 1e-3
    print("    缩小 / 适应宽度 OK（当前 %s）" % app.zoom_var.get())

    # 点缩略图跳页 + 滚轮
    app._strip_scroll(900)
    app._goto_page(1)
    wait(root, 0.4)
    assert app.cur_index == 1

    # 选中 zip 包节点 → 自动解压并读取
    node = None
    for c in app.tree.get_children(root_item):
        p = app.tree_paths.get(c, "")
        if os.path.basename(p).lower() == ZIP_NAME:
            node = c
    if node is None:                      # zip 还没进树，展开一次根节点
        app._fill_node(root_item, SAMPLE)
        for c in app.tree.get_children(root_item):
            p = app.tree_paths.get(c, "")
            if os.path.basename(p).lower() == ZIP_NAME:
                node = c
    assert node, "目录树里没找到 %s" % ZIP_NAME
    app.tree.selection_set(node)
    app.tree.focus(node)
    app._open_archive_node(node)
    wait(root, 4.0)
    print("    选中 %s → 图片 %d 张，来源目录 %s"
          % (ZIP_NAME, len(app.paths), app.cur_folder))
    assert len(app.paths) == 3
    assert app.cur_folder and app.cur_folder.startswith(mod.WORK_DIR)

    # 连读：读到最后一页自动接下一个文件夹（vol1 → vol2）
    def select_dir(name):
        for c in app.tree.get_children(root_item):
            if os.path.basename(app.tree_paths.get(c, "")) == name:
                app.tree.selection_set(c)
                app.tree.focus(c)
                return True
        return False

    assert select_dir("vol1"), "没找到 vol1"
    wait(root, 2.5)
    assert len(app.paths) == 3 and len(app.albums) == 1
    app._goto_page(len(app.paths) - 1)
    wait(root, 0.3)
    app._strip_scroll(6000)                 # 滚到最底 → 触发接下一个
    wait(root, 3.0)
    print("[6] 连读：vol1 到底 → 已接 %d 段 / 共 %d 张，第二段是 %s"
          % (len(app.albums), len(app.paths),
             os.path.basename(app.albums[-1]["folder"])))
    assert len(app.albums) == 2 and len(app.paths) == 6
    assert os.path.basename(app.albums[-1]["folder"]) == "vol2"

    # 连读压缩包：漫画03 之后是 vol2.zip
    assert select_dir("漫画03"), "没找到 漫画03"
    wait(root, 2.5)
    app._goto_page(len(app.paths) - 1)
    wait(root, 0.3)
    app._strip_scroll(6000)
    wait(root, 4.0)
    print("    漫画03 到底 → 已接 %d 段 / 共 %d 张，末段来源 %s（%s）"
          % (len(app.albums), len(app.paths), app.albums[-1]["kind"],
             os.path.basename(app.albums[-1]["src"])))
    assert len(app.albums) >= 2
    assert app.albums[-1]["kind"] == "arch"
    assert os.path.basename(app.albums[-1]["src"]).lower() == ZIP_NAME

    root.destroy()
    print("    三栏界面、旋转、缩放、zip 读取、连读 —— 全部正常")


if __name__ == "__main__":
    make_sample()
    make_zip()
    check_sort()
    check_thumbs()
    check_archives()
    check_gui()
    print("\n自检通过 ✔")
