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
import json
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
ZIP_MULTI = "双话.zip"


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


def make_zip_multi():
    """包里有两话，用来验证「同一个包内接着读」"""
    zpath = os.path.join(SAMPLE, ZIP_MULTI)
    if os.path.exists(zpath):
        return zpath
    tmp = os.path.join(HERE, "_tmp_multi_page.png")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for tag in ("第1话", "第2话"):
            for p in range(1, 3):
                page_image("%s in %s" % (ZIP_MULTI, tag), p, (90, 150, 190)).save(tmp)
                z.write(tmp, "%s/p%d.png" % (tag, p))
    if os.path.exists(tmp):
        os.remove(tmp)
    print("    已生成多话压缩包：", zpath)
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


def make_batch_dir(n=12):
    """一批 12 张的临时目录，用来验证「一次只读 5 张、滚到附近再读」"""
    d = os.path.join(HERE, "_自检批次")
    if not os.path.isdir(d):
        os.makedirs(d)
    for p in range(1, n + 1):
        f = os.path.join(d, "p%02d.png" % p)
        if not os.path.exists(f):
            page_image("batch", p, (120, 160, 100)).save(f)
    return d


def check_final_order():
    """名字是「最终 / 最后」的条目默认排到最后"""
    d = os.path.join(HERE, "_自检排序")
    if not os.path.isdir(d):
        os.makedirs(d)
    for n in ("1", "2", "10", "最终", "最后", "第10话 最终",
              "最终话-后篇", "最终话-前篇", "第3话-某人的故事"):
        sub = os.path.join(d, n)
        if not os.path.isdir(sub):
            os.makedirs(sub)
    for n in ("a.png", "最终.png", "b.png"):
        f = os.path.join(d, n)
        if not os.path.exists(f):
            page_image("final", 1, (140, 120, 90)).save(f)
    got = [e[1] for e in mod.list_entries(d)]
    normal = [n for n in got if not mod.is_final_name(n)]
    finals = [n for n in got if mod.is_final_name(n)]
    print("[10] 收尾名称排最后：%s → 正常 %s / 收尾 %s" % (got, normal, finals))
    assert got[:len(normal)] == normal, got
    assert set(finals) == {"最终", "最后", "第10话 最终", "最终话-后篇", "最终话-前篇"}, got
    assert "第3话-某人的故事" in normal, "带数字的正常章节不能被误判成收尾"
    assert got[:3] == ["1", "2", "10"], got
    imgs = [os.path.basename(p) for p in mod.list_images(d)]
    print("     图片排序：%s（最终.png 在最后）" % imgs)
    assert imgs[-1] == "最终.png" and imgs[:2] == ["a.png", "b.png"], imgs


def check_exif():
    """EXIF 方向：默认不纠正，勾选后才按 EXIF 摆正"""
    d = os.path.join(HERE, "_自检EXIF")
    if not os.path.isdir(d):
        os.makedirs(d)
    p = os.path.join(d, "rotated.jpg")
    if not os.path.exists(p):
        im = Image.new("RGB", (300, 200), (200, 70, 70))
        ex = Image.Exif()
        ex[274] = 6                      # Orientation: 顺时针转 90°
        im.save(p, "JPEG", quality=90, exif=ex)
    mod.AUTO_EXIF = False
    off_size = mod.read_size(p)
    tf_off = mod.thumb_file(p)
    page_off = mod.load_page_image(p, 300)
    mod.AUTO_EXIF = True
    on_size = mod.read_size(p)
    tf_on = mod.thumb_file(p)
    page_on = mod.load_page_image(p, 300)
    print("[12] EXIF 方向：不勾 %s / 勾上 %s；缓存键 %s；页面高度 %d → %d"
          % (off_size, on_size, "不同" if tf_off != tf_on else "相同",
             page_off.size[1], page_on.size[1]))
    assert off_size == (300, 200), "不勾时应按文件原始方向（横图）"
    assert on_size == (200, 300), "勾上后应按 EXIF 变成竖图"
    assert tf_off != tf_on, "两种模式的缩略图缓存不能混用"
    assert page_on.size[1] > page_off.size[1]
    mod.AUTO_EXIF = False


def check_gui():
    import tkinter as tk
    root = mod.make_root()
    root.withdraw()
    app = mod.ViewerApp(root)
    try:
        root.attributes("-alpha", 0.0)
    except Exception:
        pass
    root.deiconify()
    app.open_root(SAMPLE)
    wait(root, 2.0)
    assert app.view_mode and len(app.paned.panes()) == 1, "启动默认应是「浏览图」：只留图片区"

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
    print("[6] 连读：vol1 到底 → 已接 %d 段 / 共 %d 张，依次是 %s"
          % (len(app.albums), len(app.paths),
             [os.path.basename(a["folder"]) for a in app.albums]))
    assert len(app.albums) >= 2
    assert os.path.basename(app.albums[1]["folder"]) == "vol2", "vol1 之后应接 vol2"

    # 连读压缩包：漫画03 之后是 vol2.zip
    assert select_dir("漫画03"), "没找到 漫画03"
    wait(root, 2.5)
    app._goto_page(len(app.paths) - 1)
    wait(root, 0.3)
    app._strip_scroll(6000)
    wait(root, 4.0)
    print("    漫画03 到底 → 已接 %d 段，接上的是 %s"
          % (len(app.albums), [os.path.basename(a["src"]) for a in app.albums[1:]]))
    assert len(app.albums) >= 2
    assert any(a["kind"] == "arch" and os.path.basename(a["src"]).lower() == ZIP_NAME
               for a in app.albums), "漫画03 之后应接上 vol2.zip"

    # 选中父目录（自己没有图）→ 自动进第一个有图的子目录，并沿子目录顺序读完
    app.tree.selection_set(root_item)
    app.tree.focus(root_item)
    wait(root, 3.0)
    print("[7] 选中根目录 → 自动读到 %s（%d 张，%d 段）"
          % (os.path.basename(app.albums[0]["folder"]), len(app.paths), len(app.albums)))
    assert os.path.basename(app.albums[0]["folder"]) == "1"
    assert len(app.paths) == 3
    app._goto_page(len(app.paths) - 1)
    wait(root, 0.3)
    app._strip_scroll(6000)
    wait(root, 3.0)
    print("    1 到底 → 依次 %s（共 %d 段）"
          % ([os.path.basename(a["folder"]) for a in app.albums], len(app.albums)))
    assert len(app.albums) >= 2
    assert os.path.basename(app.albums[1]["folder"]) == "2", "应从同一层目录里接，不跳层"

    # 同一个包里有多话 → 包内接着读，而不是跳出包
    node2 = None
    for c in app.tree.get_children(root_item):
        if os.path.basename(app.tree_paths.get(c, "")).lower() == ZIP_MULTI:
            node2 = c
    assert node2, "目录树里没找到 %s" % ZIP_MULTI
    app.tree.selection_set(node2)
    app.tree.focus(node2)
    app._open_archive_node(node2)
    wait(root, 4.0)
    print("[8] 选中 %s → 读到包内 %s（%d 张）"
          % (ZIP_MULTI, os.path.basename(app.albums[0]["folder"]), len(app.paths)))
    assert os.path.basename(app.albums[0]["folder"]) == "第1话"
    app._goto_page(len(app.paths) - 1)
    wait(root, 0.3)
    app._strip_scroll(6000)
    wait(root, 4.0)
    print("    第1话 到底 → 接上 %s（%s，共 %d 段 / %d 张）"
          % ([os.path.basename(a["folder"]) for a in app.albums],
             app.albums[1]["kind"], len(app.albums), len(app.paths)))
    assert len(app.albums) >= 2 and len(app.paths) >= 4
    assert os.path.basename(app.albums[1]["folder"]) == "第2话"
    assert app.albums[1]["kind"] == "arch"

    # 分批读取：一次只进来 5 张，滚到附近自动补下一批，全部读完才收尾
    bdir = make_batch_dir(12)
    app.autonext.set(0)                     # 这一段只验分批，不接别的目录
    app.batch = 5
    app.batch_var.set("5")
    app.load_folder(bdir)
    wait(root, 2.0)
    print("[9] 分批：首屏载入 %d 张 / 共 %d 张，段数 %d，还剩 %d 张没读"
          % (len(app.paths), app.total_hint, len(app.albums), len(app.pending)))
    assert len(app.paths) == 5 and app.total_hint == 12
    assert len(app.pending) == 12 - 5
    got = [len(app.paths)]
    for _ in range(6):
        app._goto_page(len(app.paths) - 1)
        app._strip_scroll(8000)
        wait(root, 1.6)
        if len(app.paths) == got[-1] and not app.pending:
            break
        got.append(len(app.paths))
    print("    往下滚时逐步长：%s，最终 %d 张 / 待读 %d 张"
          % (got, len(app.paths), len(app.pending)))
    assert got[0] == mod.BATCH and got == sorted(got) and got[-1] == 12
    assert len(app.paths) == 12 and not app.pending and len(app.albums) == 1
    assert app.paths == mod.list_images(bdir), "分批拼出来的顺序必须和目录里一致，不能重复/漏页"
    app.batch_var.set("10")
    app._on_batch_change()
    assert app.batch == 10 and app.batch_box.get() == "10", "下拉换批次没生效"
    app.batch_var.set("5")
    app._on_batch_change()
    assert app.batch == 5
    print("    批次下拉 5 / 10 / 20 切换 OK（当前 %d，存在 config.json）" % app.batch)
    app.autonext.set(1)

    # 固定图片宽度 / 纯净看图 / 状态栏信息
    app.set_fixed_width_value(1400)
    wait(root, 0.6)
    print("[11] 固定宽度：dw=%d px，缩放标签 %s" % (app.dw, app.zoom_var.get()))
    assert app.dw == 1400 and "1400" in app.zoom_var.get()
    app._enter_view_mode()
    wait(root, 0.6)
    print("     只看图片：view_mode=%s，工具栏可见=%s，面板数=%d"
          % (app.view_mode, app.bar.winfo_ismapped(), len(app.paned.panes())))
    assert app.view_mode and app.bar.winfo_ismapped(), "工具栏（菜单栏）要保留"
    assert len(app.paned.panes()) == 1, "只看图片时应只留图片浏览区"
    assert not app.root.attributes("-fullscreen"), "不强制全屏，窗口还要能拖动改大小"
    app._exit_view_mode()
    wait(root, 0.6)
    assert not app.view_mode and app.bar.winfo_ismapped()
    assert len(app.paned.panes()) == 3, "退出后应恢复三栏"
    txt = app.info.cget("text")
    print("     状态栏：%s" % txt)
    assert "PNG" in txt.upper() and "x" in txt and ("B" in txt), "状态栏要显示尺寸/体积/格式"
    app.set_fixed_width_value(0)
    wait(root, 0.4)

    # 字号档位：小 / 标准 / 大 / 超大
    try:
        import tkinter.font as tkfont
        app.font_var.set("标准")
        app._on_font_change()
        wait(root, 0.4)
        px_std = mod.ui_px()
        rh_std = int(float(mod.ttk.Style(root).lookup("Treeview", "rowheight")))
        app.font_var.set("超大")
        app._on_font_change()
        wait(root, 0.5)
        px_xl = mod.ui_px()
        rh_xl = int(float(mod.ttk.Style(root).lookup("Treeview", "rowheight")))
        f_xl = tkfont.Font(root=root, name=mod.FONT_UI, exists=True)
        print("[13] 字号：标准 %dpx/行高 %d → 超大 %dpx/行高 %d，字体点数 %s，配置 %s"
              % (px_std, rh_std, px_xl, rh_xl, f_xl.cget("size"),
                 json.load(open(mod.CFG_PATH, encoding="utf-8")).get("font")))
        assert px_xl >= px_std + 3, "超大字号要比标准明显变大"
        assert rh_xl >= rh_std + 4, "左栏行高要跟着字号一起变大"
        assert abs(int(f_xl.cget("size"))) >= 16, "命名字体 PVUI 实际像素要变大"
        app.font_var.set("小")
        app._on_font_change()
        wait(root, 0.4)
        px_sm = mod.ui_px()
        app.font_var.set("标准")
        app._on_font_change()
        wait(root, 0.4)
        print("     小字号 %dpx → 标准 %dpx，四档可切换" % (px_sm, mod.ui_px()))
        assert px_sm < px_std < px_xl
        # 右键菜单也要跟着字号走（Tk 在 Windows 上默认给菜单写死 9pt，必须显式挂命名字体）
        app.font_var.set("大")
        app._on_font_change()
        wait(root, 0.3)
        app._show_menu()
        wait(root, 0.3)
        menu_font = str(app._menu.cget("font"))
        cfgv = root.tk.splitlist(root.tk.call("font", "configure", menu_font))
        px_menu = abs(int(dict(zip(cfgv[0::2], cfgv[1::2])).get("-size", 0)))
        app._menu.unpost()
        print("     右键菜单字体：%s，实际 %dpx（大档）" % (menu_font, px_menu))
        assert menu_font == mod.FONT_UI, "右键菜单必须挂 PVUI 命名字体"
        assert px_menu >= mod.ui_px() - 1, "右键菜单字号要跟界面字号一致"
    except AssertionError:
        raise
    except Exception as e:
        print("     字号检查跳过：%s" % e)

    app.shutdown()
    print("    三栏界面、旋转、缩放、zip 读取、连读（同级 / 包内 / 父目录下钻）、分批读取 —— 全部正常")

def check_smooth():
    """滚动不能卡：解码在后台线程，主线程只贴图；滚轮事件合并绘制"""
    import tkinter as tk
    bdir = make_batch_dir(12)
    root = mod.make_root()
    root.withdraw()
    app = mod.ViewerApp(root)
    root.deiconify()
    app.open_root(bdir)
    wait(root, 2.5)
    assert len(app.paths) >= 5 and app.total_hint == 12
    # 首屏应该已经贴出来（后台解码 + 主线程贴图）
    drawn = len(app.page_photos)
    print("[14] 首屏已贴 %d 片，待解码 %d 个任务" % (drawn, app.band_q.qsize()))
    assert drawn >= 1, "后台解码完要把图贴到画布上"

    # 连续 40 次滚轮事件：处理函数本身必须很快（不能在这里解码图片）
    t0 = time.time()
    for _ in range(40):
        app._strip_scroll(120)
        root.update()
    per = (time.time() - t0) / 40 * 1000
    print("     连续 40 次滚轮：平均每次 %.1f ms（含 update）" % per)
    assert per < 30, "单次滚动处理超过 30ms 就会感觉卡"

    wait(root, 2.0)
    # 滚到底以后画布上应该还有图（不是滚一路黑）
    assert len(app.page_photos) >= 1, "滚动过程中要持续有图贴上"
    # 到末尾之前的预取 / 分批还在正常跑
    print("     滚动后已贴 %d 片、已载入 %d 张、待读 %d 张"
          % (len(app.page_photos), len(app.paths), len(app.pending)))
    app.shutdown()


def check_drop():
    """拖拽：窗口要能被注册成接受拖放，拖进来的图要打开它所在目录并跳到这张"""
    import tkinter as tk
    bdir = make_batch_dir(12)
    root = mod.make_root()
    app = mod.ViewerApp(root)
    wait(root, 1.2)
    assert app._drop_cb is not None, "窗口没能注册拖放：%s" % getattr(app, "_drop_err", "?")
    assert getattr(mod, "HAS_DND", False), "tkinterdnd2 没装上，拖拽不可用"
    app.open_root(os.path.dirname(bdir))
    wait(root, 2.0)
    # 别的目录里的一张图，模拟 tkdnd 送来的 <<Drop>> 事件（数据是 {路径} 形式）
    other = os.path.join(SAMPLE, "vol10", "p2.png")
    if not os.path.exists(other):
        other = os.path.join(os.path.dirname(bdir), "p2.png")
    assert os.path.exists(other), other

    class Ev(object):
        data = "{%s}" % other
        action = "copy"

    app._on_dnd_event(Ev())
    wait(root, 2.5)
    assert app.cur_folder and os.path.basename(os.path.abspath(app.cur_folder)) == \
        os.path.basename(os.path.dirname(other)), "没切到这张图所在目录"
    assert app.paths and os.path.basename(app.paths[app.cur_index]) == os.path.basename(other), \
        "没跳到拖进来的那张图"
    print("[15] 拖放已就绪（%d 个控件注册），拖入图片后目录切到 %s、跳到 %s"
          % (getattr(app, "_drop_hwnd", 0) or 0, os.path.basename(app.cur_folder),
             os.path.basename(other)))
    app.shutdown()


if __name__ == "__main__":
    make_sample()
    make_zip()
    make_zip_multi()
    check_sort()
    check_final_order()
    check_exif()
    check_thumbs()
    check_archives()
    check_gui()
    check_smooth()
    check_drop()
    print("\n自检通过 ✔")

