# -*- coding: utf-8 -*-
"""
连续看图工具 v1.7 —— 漫画 / 图集专用看图器（Windows 7 / Windows 10）

功能：
  1. 自然排序读取子文件夹：1 2 3、vol1 vol2 vol10、漫画01 漫画02、动漫a 动漫b ……不会出现 vol1 / vol10 / vol100 混排
  2. 左侧目录树（文件夹 + zip/rar/cbz/cbr/7z 压缩包）→ 中间缩略图（缓存写在程序目录 thumbcache）
     → 右侧连续长图浏览
  3. 右侧滚轮上下连续滚动，页面紧贴无间隙；支持左右旋转 90°、放大缩小

依赖：Python 3.8+（Windows 7 请用 Python 3.8.10）+ Pillow
      rar/cbr 解压需要 WinRAR（自动找 UnRAR.exe）或 7-Zip
"""

import os
import re
import sys
import json
import hashlib
import shutil
import subprocess
import threading
import queue
import zipfile

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk, ImageOps
    HAS_PIL = True
except Exception:
    HAS_PIL = False


# ---------------------------------------------------------------- 基础设置

def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()
CACHE_DIR = os.path.join(APP_DIR, "thumbcache")
WORK_DIR = os.path.join(APP_DIR, "extract_cache")
CFG_PATH = os.path.join(APP_DIR, "config.json")

IMG_EXT = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".bmp",
           ".gif", ".webp", ".tif", ".tiff"}
ARCH_EXT = {".zip", ".cbz", ".rar", ".cbr", ".7z"}

NUM_RE = re.compile(r"(\d+)")

FONT_UI = ("Microsoft YaHei", 9)
FONT_SMALL = ("Microsoft YaHei", 8)

CELL_W = 162          # 缩略图格子宽
CELL_H = 196          # 缩略图格子高
THUMB_MAX = 148       # 缩略图长边像素
BAND_H = 1000         # 超长页面分片显示的单片高度（避免一张图吃掉几百 MB）
MAX_BASE = 2          # 解码后的整页缓存数量
MAX_DEPTH = 12        # 解压后自动下钻的最大层数
BATCH = 5             # 一次只读这么多张，滚到附近再读下一批（省内存、秒开）


def resample_filter():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:            # 老版本 Pillow
        return Image.LANCZOS


def transpose_map():
    """90 = 顺时针右转，270 = 左转"""
    try:
        T = Image.Transpose
    except AttributeError:
        T = Image
    return {
        90: ("ROTATE_270", getattr(T, "ROTATE_270", getattr(Image, "ROTATE_270"))),
        180: ("ROTATE_180", getattr(T, "ROTATE_180", getattr(Image, "ROTATE_180"))),
        270: ("ROTATE_90", getattr(T, "ROTATE_90", getattr(Image, "ROTATE_90"))),
    }


_TRANS = None


def transpose(im, deg):
    global _TRANS
    deg = deg % 360
    if deg == 0:
        return im
    if _TRANS is None:
        _TRANS = transpose_map()
    return im.transpose(_TRANS[deg][1])


def natural_key(name):
    """自然排序键：数字段按数值比较（vol2 < vol10 < vol100）"""
    low = name.lower()
    parts = NUM_RE.split(low)
    key = []
    for p in parts:
        if p.isdigit():
            key.append((0, int(p), ""))
        elif p:
            key.append((1, 0, p))
    return (key, low)


FINAL_NAMES = ("最终", "最后", "完结", "大结局", "end", "the end", "final")
FINAL_WORDS = ("最终话", "最后话", "最终回", "最终章", "终章", "完结篇", "大结局")


def is_final_name(name, is_file=False):
    """名字里带「最终话 / 最后 / 完结」这类收尾标记 → 排序时永远排最后

    三种命中：整个名字就是收尾词；名字里含「最终话/最后话/终章…」；
    名字以「最终/最后/完结/大结局」结尾。
    """
    base = os.path.splitext(name)[0] if is_file else name
    base = (base or "").strip().lower()
    if not base:
        return False
    if base in FINAL_NAMES:
        return True
    for w in FINAL_WORDS:
        if w in base:
            return True
    return base.endswith(("最终", "最后", "完结", "大结局"))


def sort_key(name, is_file=False):
    """先按「是不是收尾标记」分组，再走自然排序"""
    return (1 if is_final_name(name, is_file) else 0, natural_key(name))


def is_image_name(name):
    return os.path.splitext(name)[1].lower() in IMG_EXT


def is_archive(path):
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in ARCH_EXT


def has_subdir(path):
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir():
                        n = e.name
                        if n.startswith(".") or n in ("thumbcache", "extract_cache"):
                            continue
                        return True
                except OSError:
                    pass
    except OSError:
        pass
    return False


def list_entries(path):
    """返回 [(kind, name, fullpath)]，kind: 'dir' / 'arch'；文件夹在前、压缩包在后，各自自然排序"""
    dirs = []
    archs = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    n = e.name
                    if n.startswith(".") or n in ("thumbcache", "extract_cache"):
                        continue
                    if e.is_dir():
                        dirs.append((n, e.path))
                    elif os.path.splitext(n)[1].lower() in ARCH_EXT:
                        archs.append((n, e.path))
                except OSError:
                    pass
    except OSError:
        pass
    dirs.sort(key=lambda t: sort_key(t[0]))
    archs.sort(key=lambda t: sort_key(t[0], True))
    out = [("dir", n, p) for (n, p) in dirs]
    out += [("arch", n, p) for (n, p) in archs]
    return out


def list_subdirs(path):
    names = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if not e.is_dir():
                        continue
                    n = e.name
                    if n.startswith(".") or n in ("thumbcache", "extract_cache"):
                        continue
                    names.append(n)
                except OSError:
                    pass
    except OSError:
        pass
    names.sort(key=lambda n: sort_key(n))
    return names


def list_images(path):
    names = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if not e.is_file():
                        continue
                    if is_image_name(e.name):
                        names.append(e.name)
                except OSError:
                    pass
    except OSError:
        pass
    names.sort(key=lambda n: sort_key(n, True))
    return [os.path.join(path, n) for n in names]


# ---------------------------------------------------------------- 缩略图缓存

def thumb_file(path):
    """缩略图缓存文件名：路径 + 修改时间 + 大小 的哈希"""
    try:
        st = os.stat(path)
        raw = "%s|%d|%d|%d|%d" % (os.path.abspath(path).lower(),
                                  st.st_mtime_ns if hasattr(st, "st_mtime_ns") else int(st.st_mtime),
                                  st.st_size, CELL_W, THUMB_MAX)
    except OSError:
        raw = os.path.abspath(path).lower()
    return os.path.join(CACHE_DIR, hashlib.md5(raw.encode("utf-8")).hexdigest() + ".jpg")


def make_thumb(path):
    """生成缩略图到 thumbcache 目录（已存在则直接复用）"""
    tf = thumb_file(path)
    if os.path.exists(tf) and os.path.getsize(tf) > 0:
        return tf
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        try:
            im.draft("RGB", (THUMB_MAX * 2, THUMB_MAX * 2))
        except Exception:
            pass
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((THUMB_MAX, THUMB_MAX), resample_filter())
        tmp = tf + ".%d.tmp" % threading.get_ident()
        im.save(tmp, "JPEG", quality=85)
    try:
        os.replace(tmp, tf)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return tf


def load_page_image(path, dw, deg=0):
    """整页解码，按旋转后的宽度缩放到 dw"""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        try:
            im.draft("RGB", (max(1, dw * 2), max(1, dw * 2)))
        except Exception:
            pass
        if deg % 360:
            im = transpose(im, deg)
        w, h = im.size
        if w <= 0 or h <= 0:
            raise ValueError("empty image")
        dh = max(1, int(round(h * float(dw) / float(w))))
        return im.resize((max(1, int(dw)), dh), resample_filter())


def read_size(path):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


# ---------------------------------------------------------------- 压缩包

def find_tool(cands, reg_names=()):
    for name in reg_names:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s" % name)
            p = winreg.QueryValue(key, "")
            if p and os.path.isfile(p):
                return p
        except Exception:
            pass
    for p in cands:
        if p and os.path.isfile(p):
            return p
    for name in ("unrar", "UnRAR", "7z", "7za"):
        w = shutil.which(name)
        if w:
            return w
    return None


_UNRAR = []
_SEVENZ = []


def _tool_from_registry(app_exe, wanted):
    """从 App Paths 注册项推出同目录下的命令行程式（WinRAR.exe → UnRAR.exe 等）"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s" % app_exe)
        p = winreg.QueryValue(key, "")
        folder = os.path.dirname(p)
        for name in wanted:
            q = os.path.join(folder, name)
            if os.path.isfile(q):
                return q
    except Exception:
        pass
    return None


def find_unrar():
    """只要命令行版的 UnRAR.exe / Rar.exe，绝不返回 GUI 的 WinRAR.exe"""
    if not _UNRAR:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        found = find_tool(
            [os.path.join(pf, "WinRAR", "UnRAR.exe"),
             os.path.join(pf86, "WinRAR", "UnRAR.exe"),
             os.path.join(pf, "WinRAR", "Rar.exe"),
             os.path.join(pf86, "WinRAR", "Rar.exe"),
             r"D:\tool\WinRAR\UnRAR.exe"],
            reg_names=("UnRAR.exe", "Rar.exe"))
        if not found or os.path.basename(found).lower() == "winrar.exe":
            found = (_tool_from_registry("WinRAR.exe", ("UnRAR.exe", "Rar.exe"))
                     or _tool_from_registry("UnRAR.exe", ("UnRAR.exe",)))
        _UNRAR.append(found)
    return _UNRAR[0]


def find_7z():
    if not _SEVENZ:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        found = find_tool(
            [os.path.join(pf, "7-Zip", "7z.exe"),
             os.path.join(pf86, "7-Zip", "7z.exe"),
             r"D:\tool\7-Zip\7z.exe",
             r"D:\tools\7-Zip\7z.exe",
             r"D:\7-Zip\7z.exe",
             r"C:\7-Zip\7z.exe",
             os.path.join(pf, "7-Zip", "7za.exe")],
            reg_names=("7z.exe", "7zFM.exe"))
        if not found or os.path.basename(found).lower() == "7zfm.exe":
            found = _tool_from_registry("7zFM.exe", ("7z.exe",))
        _SEVENZ.append(found)
    return _SEVENZ[0]


def extract_dir_for(path):
    """解压缓存目录：路径+修改时间+大小 的哈希"""
    try:
        st = os.stat(path)
        raw = "%s|%d|%d" % (os.path.abspath(path).lower(),
                            st.st_mtime_ns if hasattr(st, "st_mtime_ns") else int(st.st_mtime),
                            st.st_size)
    except OSError:
        raw = os.path.abspath(path).lower()
    return os.path.join(WORK_DIR, hashlib.md5(raw.encode("utf-8")).hexdigest())


def _zip_member_name(info):
    """修正 Windows 下打包的 zip 中文文件名（cp437 → gbk/utf-8）"""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except Exception:
        return name
    for enc in ("gbk", "utf-8", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return name


def _safe_join(root, name):
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    if not parts or ":" in parts[0]:
        return None
    return os.path.join(root, *parts)


def extract_archive(path, dest):
    """把压缩包里的图片解到 dest（已解压过则直接返回）"""
    marker = os.path.join(dest, ".done")
    if os.path.exists(marker):
        return dest
    if not os.path.isdir(dest):
        os.makedirs(dest)
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".zip", ".cbz"):
            count = _extract_zip(path, dest)
            if count == 0:
                raise RuntimeError("压缩包里没有找到图片")
        else:
            _extract_external(path, ext, dest)
            if not _has_any_image(dest):
                raise RuntimeError("压缩包里没有找到图片")
    except Exception:
        # 失败时别留下半成品缓存
        shutil.rmtree(dest, ignore_errors=True)
        raise
    with open(marker, "w") as f:
        f.write("ok")
    return dest


def _has_any_image(folder):
    for root, dirs, files in os.walk(folder):
        for f in files:
            if is_image_name(f):
                return True
    return False


def _extract_zip(path, dest):
    count = 0
    with zipfile.ZipFile(path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = _zip_member_name(info)
            if not is_image_name(name):
                continue
            out = _safe_join(dest, name)
            if not out:
                continue
            parent = os.path.dirname(out)
            if parent and not os.path.isdir(parent):
                try:
                    os.makedirs(parent)
                except OSError:
                    pass
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 128)
            count += 1
    return count


def _extract_external(path, ext, dest):
    """rar/cbr 优先用 WinRAR 的 UnRAR.exe，没有就退到 7-Zip；7z 只能靠 7-Zip"""
    if ext in (".rar", ".cbr"):
        unrar = find_unrar()
        if unrar:
            base = [unrar, "x", "-o+", "-y"]
            if os.path.basename(unrar).lower() == "unrar.exe":
                base.append("-idq")
            cmd = base + ["-p-", path, dest]
        else:
            seven = find_7z()
            if not seven:
                raise RuntimeError("没有找到 UnRAR.exe 或 7z.exe，无法解压 rar/cbr。\n"
                                   "装个 WinRAR 或 7-Zip 后重试。")
            cmd = [seven, "x", "-y", "-o" + dest, path]
    else:
        seven = find_7z()
        if not seven:
            raise RuntimeError("没有找到 7z.exe，无法解压 7z 压缩包。\n"
                               "请安装 7-Zip（本机可放在 D:\\tool\\7-Zip）后重试。")
        cmd = [seven, "x", "-y", "-o" + dest, path]
    flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=flags, timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("解压超时（10 分钟），压缩包可能太大")
    if proc.returncode not in (0, 1):
        msg = proc.stdout.decode("mbcs" if sys.platform == "win32" else "utf-8", "ignore")
        raise RuntimeError("解压失败（返回码 %d）：\n%s" % (proc.returncode, msg[-500:]))


def find_first_image_dir(root, max_depth=MAX_DEPTH):
    """解压后若根目录没有图片，往下找第一个有图片的目录"""
    if list_images(root):
        return root
    node = root
    for _ in range(max_depth):
        subs = list_subdirs(node)
        if not subs:
            return None
        node = os.path.join(node, subs[0])
        if list_images(node):
            return node
    return None


def dirs_with_images(root):
    """root 子树里所有「直接含有图片」的目录，按树的先序（含 root 自己）"""
    if list_images(root):
        yield root
    for name in list_subdirs(root):
        for d in dirs_with_images(os.path.join(root, name)):
            yield d


def first_dir_with_images(root):
    for d in dirs_with_images(root):
        return d
    return None


def next_dir_after(root, current):
    """root 子树内 current 的先序后继目录（含图），没有则 None"""
    cur = os.path.normcase(os.path.abspath(current))
    found = False
    for d in dirs_with_images(root):
        if found:
            return d
        if os.path.normcase(os.path.abspath(d)) == cur:
            found = True
    return None


# ---------------------------------------------------------------- 主程序

class ViewerApp(object):

    def __init__(self, root):
        self.root = root
        self.root.title("连续看图工具 v1.7")
        self.q = queue.Queue()
        self.token = 0
        self.root_dir = ""

        self.tree_paths = {}

        self.cur_folder = None
        self.paths = []
        self.sizes = []

        self.thumb_photos = {}
        self.thumb_cell = {}
        self.thumb_rect = {}
        self.thumb_cols = 1
        self.thumb_total = 0

        self.rot = {}                 # 路径 -> 0/90/180/270（视角旋转）
        self.zoom = 1.0               # 1.0 = 适应宽度
        self.dw = 700
        self.off_x = 0

        # 连读（读到最后一页自动接下一个文件夹/压缩包）
        self.albums = []              # [{kind, src, folder, start, end}]
        self.cur_src = None           # 当前来源 ('dir'|'arch', path)
        self.archive_map = {}         # 解压目录 -> 原始压缩包路径
        self._appending = False
        self._append_tries = 0
        self._attempted = set()       # 本次阅读里已经尝试过的接续目标
        self.last_src = None          # 最近一次接上的来源，避免重复接同一个
        self.pending = []             # 当前这一本还没读进来的图片路径（每次只取 batch 张）
        self._loading = False         # 正在后台量下一批尺寸 / 正在接下一本
        self.total_hint = 0           # 当前这本总共多少张（只用于状态提示）
        self.batch = BATCH            # 每批读多少张（工具栏下拉 5 / 10 / 20）

        self.geom = []
        self.ys = []
        self.strip_total = 1
        self.cur_index = -1

        self.page_items = {}
        self.page_photos = {}
        self.base_cache = {}
        self.base_order = []

        self._resize_job = None
        self._build_job = None
        self._more_job = None          # 快到末尾时的预取定时器
        self._closing = False

        for d in (CACHE_DIR, WORK_DIR):
            if not os.path.isdir(d):
                try:
                    os.makedirs(d)
                except OSError:
                    pass

        self._build_ui()
        self._load_cfg()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self._poll)
        self.root.after(200, self._auto_open)

    # ------------------------------------------------------------ 界面

    def _build_ui(self):
        bar = tk.Frame(self.root)
        bar.pack(side="top", fill="x")

        self.btn_open = tk.Button(bar, text="打开目录", command=self.choose_dir, font=FONT_UI)
        self.btn_open.pack(side="left", padx=(8, 4), pady=5)

        self.btn_refresh = tk.Button(bar, text="刷新", command=self.refresh, font=FONT_UI)
        self.btn_refresh.pack(side="left", padx=4, pady=5)

        tk.Label(bar, text="｜", fg="#bbb").pack(side="left")

        tk.Button(bar, text="↺ 左转", command=lambda: self.rotate_page(-90),
                  font=FONT_UI).pack(side="left", padx=2, pady=5)
        tk.Button(bar, text="↻ 右转", command=lambda: self.rotate_page(90),
                  font=FONT_UI).pack(side="left", padx=2, pady=5)
        self.apply_all = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="整本", variable=self.apply_all,
                       font=FONT_UI).pack(side="left", padx=2)

        tk.Label(bar, text="｜", fg="#bbb").pack(side="left")

        tk.Button(bar, text="－", width=3, command=lambda: self.zoom_by(0.8),
                  font=FONT_UI).pack(side="left", padx=2, pady=5)
        self.zoom_var = tk.StringVar(value="100%")
        tk.Label(bar, textvariable=self.zoom_var, width=5,
                 font=FONT_UI).pack(side="left")
        tk.Button(bar, text="＋", width=3, command=lambda: self.zoom_by(1.25),
                  font=FONT_UI).pack(side="left", padx=2, pady=5)
        tk.Button(bar, text="适应", command=self.zoom_fit,
                  font=FONT_UI).pack(side="left", padx=(2, 6), pady=5)

        self.autonext = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="连读下一个", variable=self.autonext,
                       font=FONT_UI).pack(side="left", padx=2)

        tk.Label(bar, text="每批", font=FONT_UI).pack(side="left", padx=(8, 2))
        self.batch_var = tk.StringVar(value=str(self.batch))
        self.batch_box = ttk.Combobox(bar, textvariable=self.batch_var, width=4,
                                      values=("5", "10", "20"), state="readonly",
                                      font=FONT_UI)
        self.batch_box.pack(side="left", padx=2, pady=4)
        self.batch_box.bind("<<ComboboxSelected>>", self._on_batch_change)
        tk.Label(bar, text="张", font=FONT_UI).pack(side="left")

        self.pos_var = tk.StringVar(value="第 0 / 0 页")
        tk.Label(bar, textvariable=self.pos_var, width=13, anchor="w",
                 font=FONT_UI).pack(side="left", padx=6)

        self.path_var = tk.StringVar(value="请选择漫画根目录")
        tk.Label(bar, textvariable=self.path_var, font=FONT_SMALL,
                 fg="#666", anchor="w").pack(side="left", fill="x", expand=True, padx=6)

        tk.Label(bar, text="滚轮上下连续浏览 · Ctrl+滚轮缩放", font=FONT_SMALL,
                 fg="#888").pack(side="right", padx=10)

        paned = tk.PanedWindow(self.root, orient="horizontal",
                               sashwidth=6, sashrelief="raised", bd=0)
        paned.pack(side="top", fill="both", expand=True)

        # 左：目录树
        left = tk.Frame(paned, bg="#f0f0f0")
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        tvb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tvb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tvb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        paned.add(left, width=230, minsize=150, stretch="never")

        # 中：缩略图
        mid = tk.Frame(paned, bg="#2b2b2b")
        self.thumb_canvas = tk.Canvas(mid, bg="#2b2b2b", highlightthickness=0,
                                      bd=0, yscrollincrement=0)
        tvsb = ttk.Scrollbar(mid, orient="vertical", command=self.thumb_canvas.yview)
        self.thumb_canvas.configure(yscrollcommand=tvsb.set)
        self.thumb_canvas.pack(side="left", fill="both", expand=True)
        tvsb.pack(side="right", fill="y")
        self.thumb_canvas.bind("<MouseWheel>", self._on_thumb_wheel)
        self.thumb_canvas.bind("<Button-1>", self._on_thumb_click)
        self.thumb_canvas.bind("<Configure>", self._on_thumb_config)
        self.thumb_canvas.bind("<Button-4>", lambda e: self._thumb_scroll(-100))
        self.thumb_canvas.bind("<Button-5>", lambda e: self._thumb_scroll(100))
        paned.add(mid, width=340, minsize=180)

        # 右：连续长图
        right = tk.Frame(paned, bg="#111111")
        self.strip = tk.Canvas(right, bg="#111111", highlightthickness=0,
                               bd=0, yscrollincrement=1)
        svb = ttk.Scrollbar(right, orient="vertical", command=self.strip.yview)
        hsb = ttk.Scrollbar(right, orient="horizontal", command=self.strip.xview)
        self.strip.configure(yscrollcommand=svb.set, xscrollcommand=hsb.set)
        svb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.strip.pack(side="left", fill="both", expand=True)
        self.strip.bind("<MouseWheel>", self._on_strip_wheel)
        self.strip.bind("<Button-4>", lambda e: self._strip_scroll(-120))
        self.strip.bind("<Button-5>", lambda e: self._strip_scroll(120))
        self.strip.bind("<Configure>", self._on_strip_config)
        self.strip.bind("<Button-1>", lambda e: self.strip.focus_set())
        for seq, handler in (("<Up>", self._key_up), ("<Down>", self._key_down),
                             ("<Prior>", self._page_up), ("<Next>", self._page_down),
                             ("<Home>", self._key_home), ("<End>", self._key_end)):
            self.root.bind(seq, handler)
        paned.add(right, width=760, minsize=300)

        self.status = tk.Label(self.root, text="就绪", anchor="w", font=FONT_SMALL,
                               fg="#555", bd=1, relief="sunken")
        self.status.pack(side="bottom", fill="x")

        style = ttk.Style()
        try:
            style.theme_use("vista" if sys.platform == "win32" else "clam")
        except Exception:
            pass
        style.configure("Treeview", font=FONT_UI, rowheight=22)

    # ------------------------------------------------------------ 配置

    def _load_cfg(self):
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        geo = cfg.get("geometry")
        if isinstance(geo, str) and "x" in geo:
            try:
                self.root.geometry(geo)
            except Exception:
                self.root.geometry("1360x880")
        else:
            self.root.geometry("1360x880")
        self.root.minsize(960, 600)
        try:
            self.batch = max(1, int(cfg.get("batch", BATCH)))
        except Exception:
            self.batch = BATCH
        if self.batch not in (5, 10, 20):
            self.batch = BATCH
        try:
            self.batch_var.set(str(self.batch))
        except Exception:
            pass

    def _on_batch_change(self, event=None):
        """下拉里换批次大小：下一批马上按新值读，不用重开这本"""
        try:
            n = int(self.batch_var.get())
        except Exception:
            n = BATCH
        self.batch = max(1, n)
        self._save_cfg()
        self.status.configure(text="每批改为 %d 张，后面的批次按新值读取" % self.batch)
        if self.pending or self.paths:
            self._maybe_more()

    def _save_cfg(self):
        try:
            cfg = {"geometry": self.root.winfo_geometry(), "root_dir": self.root_dir,
                   "batch": self.batch}
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------ 目录树

    def choose_dir(self):
        init = self.root_dir if os.path.isdir(self.root_dir) else APP_DIR
        d = filedialog.askdirectory(title="选择漫画根目录", initialdir=init)
        if d:
            self.open_root(d)

    def open_root(self, folder):
        if not os.path.isdir(folder):
            messagebox.showwarning("提示", "目录不存在：\n%s" % folder)
            return
        self.root_dir = folder
        self._save_cfg()
        self.path_var.set(folder)
        self.tree.delete(*self.tree.get_children(""))
        self.tree_paths.clear()
        name = os.path.basename(os.path.normpath(folder)) or folder
        root_item = self.tree.insert("", "end", text=name, open=True)
        self.tree_paths[root_item] = folder
        self._fill_node(root_item, folder)
        self.tree.selection_set(root_item)
        self.tree.focus(root_item)
        self.load_folder(folder)

    def _fill_node(self, iid, path):
        self.tree.delete(*self.tree.get_children(iid))
        for kind, name, full in list_entries(path):
            if kind == "dir":
                child = self.tree.insert(iid, "end", text=name, open=False)
                if has_subdir(full) or list_entries(full):
                    self.tree.insert(child, "end", text="loading…")
            else:
                child = self.tree.insert(iid, "end", text="▤ " + name, open=False)
                self.tree.insert(child, "end", text="loading…")
            self.tree_paths[child] = full

    def _ensure_children(self, iid):
        children = self.tree.get_children(iid)
        if len(children) == 1 and self.tree.item(children[0], "text").startswith("loading"):
            path = self.tree_paths.get(iid)
            if path and os.path.isdir(path):
                self._fill_node(iid, path)

    def _on_tree_open(self, event=None):
        iid = self.tree.focus()
        if not iid:
            return
        self._ensure_children(iid)
        if is_archive(self.tree_paths.get(iid, "")):
            self._open_archive_node(iid)

    def _on_tree_select(self, event=None):
        iid = self.tree.focus()
        if not iid:
            return
        path = self.tree_paths.get(iid)
        if not path:
            return
        if os.path.isdir(path):
            self.load_folder(path)
        elif is_archive(path):
            self._open_archive_node(iid)

    def refresh(self):
        if self.cur_folder and os.path.isdir(self.cur_folder):
            self.load_folder(self.cur_folder)
        elif self.root_dir and os.path.isdir(self.root_dir):
            self.open_root(self.root_dir)

    def _auto_open(self):
        try:
            if os.path.exists(CFG_PATH):
                with open(CFG_PATH, "r", encoding="utf-8") as f:
                    last = json.load(f).get("root_dir")
                if last and os.path.isdir(last):
                    self.open_root(last)
                    return
        except Exception:
            pass
        self.status.configure(text="点左上角「打开目录」选择漫画文件夹")

    # ------------------------------------------------------------ 压缩包节点

    def _open_archive_node(self, iid):
        path = self.tree_paths.get(iid)
        if not path or not is_archive(path):
            return
        dest = extract_dir_for(path)
        if os.path.exists(os.path.join(dest, ".done")):
            self._attach_archive(iid, path, dest)
            return
        self.token += 1
        token = self.token
        self._clear_views()
        self.status.configure(text="正在解压：%s …" % os.path.basename(path))
        t = threading.Thread(target=self._extract_worker,
                             args=(token, iid, path, dest), daemon=True)
        t.start()

    def _extract_worker(self, token, iid, path, dest):
        try:
            extract_archive(path, dest)
            self.q.put(("archive", token, iid, path, dest, None))
        except Exception as e:
            self.q.put(("archive", token, iid, path, dest, str(e)))

    def _attach_archive(self, iid, path, dest):
        self.tree_paths[iid] = dest
        self.archive_map[os.path.abspath(dest)] = path
        try:
            self.tree.item(iid, text="▤ " + os.path.basename(path))
        except Exception:
            pass
        self._fill_node(iid, dest)
        try:
            self.tree.item(iid, open=True)
        except Exception:
            pass
        # 包里通常先套一层同名文件夹，顺着先序第一个有图的目录展开
        target = first_dir_with_images(dest) or dest
        rel = os.path.relpath(target, dest)
        node = iid
        if rel not in (".", ""):
            for part in rel.split(os.sep):
                self._ensure_children(node)
                found = None
                for c in self.tree.get_children(node):
                    if self.tree.item(c, "text") == part:
                        found = c
                        break
                if not found:
                    break
                node = found
                try:
                    self.tree.item(node, open=True)
                except Exception:
                    pass
        self.tree.selection_set(node)
        self.tree.focus(node)
        self.load_folder(self.tree_paths.get(node, target), src=("arch", path))

    def open_archive_path(self, path):
        """命令行直接打开某个压缩包：先打开它所在目录，再选中并解压这个包"""
        parent = os.path.dirname(os.path.abspath(path))
        self.open_root(parent)
        root_item = self.tree.get_children("")
        if not root_item:
            return
        node = root_item[0]
        self._ensure_children(node)
        for child in self.tree.get_children(node):
            p = self.tree_paths.get(child, "")
            if p and os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path)):
                self.tree.selection_set(child)
                self.tree.focus(child)
                self._open_archive_node(child)
                return

    # ------------------------------------------------------------ 读取某个文件夹

    def _clear_views(self):
        self.paths = []
        self.sizes = []
        self.albums = []
        self.cur_src = None
        self._appending = False
        self._append_tries = 0
        self._attempted = set()
        self.last_src = None
        self.pending = []
        self._loading = False
        self.total_hint = 0
        self._more_job = None
        self.thumb_photos.clear()
        self.thumb_cell.clear()
        self.thumb_rect.clear()
        self.page_items.clear()
        self.page_photos.clear()
        self.base_cache.clear()
        self.base_order = []
        self.geom = []
        self.ys = []
        self.strip_total = 1
        self.cur_index = -1
        self.pos_var.set("第 0 / 0 页")
        self.thumb_canvas.configure(scrollregion=(0, 0, 1, 1))
        self.thumb_canvas.delete("all")
        self.strip.delete("all")
        self.strip.configure(scrollregion=(0, 0, 1, 1))

    def load_folder(self, folder, src=None):
        self.token += 1
        token = self.token
        self.cur_folder = folder
        self._clear_views()
        if src is None:
            src = self._src_of(folder)
        self.cur_src = src
        short = os.path.basename(os.path.normpath(folder)) or folder
        self.status.configure(text="正在读取：%s …" % short)
        t = threading.Thread(target=self._scan_worker, args=(folder, token), daemon=True)
        t.start()

    def _src_of(self, folder):
        """这个目录属于哪个「树节点」：压缩包解出来的目录要回溯到压缩包"""
        p = os.path.normcase(os.path.abspath(folder))
        for base, arch in self.archive_map.items():
            b = os.path.normcase(os.path.abspath(base))
            if p == b or p.startswith(b + os.sep):
                return ("arch", arch)
        return ("dir", folder)

    def _scan_worker(self, folder, token):
        try:
            paths = list_images(folder)
            if not paths:
                # 选中的父目录里没有直接图片：自动先进去第一个有图的子目录
                inner = first_dir_with_images(folder)
                if inner:
                    folder = inner
                    paths = list_images(folder)
        except Exception:
            paths = []
        sizes = [read_size(p) for p in paths[:self.batch]]   # 只量首批，其余等滚到再量
        self.q.put(("scan", token, folder, paths, sizes))

    def _thumb_worker(self, token, paths, offset=0):
        for i, p in enumerate(paths):
            if token != self.token:
                return
            try:
                make_thumb(p)
            except Exception:
                continue
            self.q.put(("thumb", token, i + offset))
        self.q.put(("thumb_done", token, len(self.paths)))

    # ------------------------------------------------------------ 消息循环

    def _poll(self):
        if self._closing:
            return
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "scan":
                    _, token, folder, paths, sizes = msg
                    if token == self.token:
                        self._on_scan_done(folder, paths, sizes)
                elif kind == "thumb":
                    _, token, idx = msg
                    if token == self.token:
                        self._on_thumb_ready(idx)
                elif kind == "thumb_done":
                    _, token, n = msg
                    if token == self.token:
                        self.status.configure(text="已载入 %d 张图片（%d 段）· 缩略图缓存 %d 张"
                                              % (len(self.paths), max(1, len(self.albums)),
                                                 len(self.thumb_photos)))
                elif kind == "append":
                    _, token, kind2, src, folder, chunk, sizes, rest, err = msg
                    if token == self.token:
                        self._on_append_done(kind2, src, folder, chunk, sizes, rest, err)
                elif kind == "grow":
                    _, token, mode, kind2, src, folder, chunk, sizes, err = msg
                    if token == self.token:
                        self._on_grow(mode, kind2, src, folder, chunk, sizes, err)
                elif kind == "archive":
                    _, token, iid, path, dest, err = msg
                    if token == self.token:
                        if err:
                            self.status.configure(text="解压失败：%s" % os.path.basename(path))
                            messagebox.showerror("解压失败", "%s\n\n%s"
                                                 % (os.path.basename(path), err))
                        else:
                            self._attach_archive(iid, path, dest)
        except queue.Empty:
            pass
        except Exception:
            pass
        self.root.after(60, self._poll)

    def _batch_worker(self, token, chunk, mode, kind, src, folder):
        """只把这一批的尺寸量出来（不读像素），量完就交给主线程拼接"""
        try:
            sizes = [read_size(p) for p in chunk]
            err = None
        except Exception as e:
            sizes = [(0, 0)] * len(chunk)
            err = str(e)
        self.q.put(("grow", token, mode, kind, src, folder, chunk, sizes, err))

    def _on_scan_done(self, folder, paths, sizes):
        if not paths:
            self.status.configure(text="这个位置没有图片：%s（如果是压缩包，展开左栏点进去）"
                                  % folder)
            return
        total = len(paths)
        self.paths = paths[:self.batch]
        self.sizes = sizes[:self.batch]
        self.pending = paths[self.batch:]
        self.albums = [{"kind": self.cur_src[0], "src": self.cur_src[1], "folder": folder,
                        "start": 0, "end": len(self.paths)}]
        self._appending = False
        self._loading = False
        self._append_tries = 0
        self.last_src = self.cur_src
        self.total_hint = total
        self.status.configure(text="%d 张图片 · 先读前 %d 张，正在生成缩略图…"
                              % (total, len(self.paths)))
        self._build_thumb_cells()
        self._layout_strip()
        self.strip.yview_moveto(0.0)
        self._strip_sync(force=True)
        t = threading.Thread(target=self._thumb_worker, args=(self.token, self.paths),
                             daemon=True)
        t.start()

    # ------------------------------------------------------------ 缩略图区

    def _clear_job(self, name):
        job = getattr(self, name)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
            setattr(self, name, None)

    def _on_thumb_config(self, event=None):
        self._clear_job("_build_job")
        self._build_job = self.root.after(120, self._rebuild_thumbs)

    def _rebuild_thumbs(self):
        self._build_job = None
        if not self.paths:
            return
        top = self.thumb_canvas.canvasy(0)
        self._build_thumb_cells()
        self.thumb_canvas.yview_moveto(top / max(1.0, float(self.thumb_total)))

    def _build_thumb_cells(self):
        c = self.thumb_canvas
        c.delete("all")
        self.thumb_cell.clear()
        self.thumb_rect.clear()
        n = len(self.paths)
        if n == 0:
            c.configure(scrollregion=(0, 0, 1, 1))
            self.thumb_total = 1
            return
        w = max(c.winfo_width(), CELL_W)
        cols = max(1, int(w // CELL_W))
        self.thumb_cols = cols
        rows = (n + cols - 1) // cols
        self.thumb_total = rows * CELL_H + 8
        c.configure(scrollregion=(0, 0, w, self.thumb_total))
        for i in range(n):
            r, col = divmod(i, cols)
            x0 = col * CELL_W
            y0 = r * CELL_H
            rect = c.create_rectangle(x0 + 3, y0 + 3, x0 + CELL_W - 3, y0 + CELL_H - 3,
                                      outline="#404040", width=1, fill="#232323")
            self.thumb_rect[i] = rect
            c.create_text(x0 + CELL_W // 2, y0 + CELL_H - 12, text=str(i + 1),
                          fill="#9a9a9a", font=FONT_SMALL)
            ph = c.create_text(x0 + CELL_W // 2, y0 + (CELL_H - 20) // 2,
                               text="…", fill="#5c5c5c", font=FONT_UI)
            self.thumb_cell[i] = [x0, y0, ph]
            if i in self.thumb_photos:
                self._place_thumb(i)

    def _place_thumb(self, i):
        cell = self.thumb_cell.get(i)
        photo = self.thumb_photos.get(i)
        if not cell or photo is None:
            return
        c = self.thumb_canvas
        x0, y0, item = cell
        try:
            c.delete(item)
        except Exception:
            pass
        cell[2] = c.create_image(x0 + CELL_W // 2, y0 + 6, anchor="n", image=photo)

    def _make_thumb_photo(self, idx):
        deg = self.rot.get(self.paths[idx], 0)
        with Image.open(thumb_file(self.paths[idx])) as im:
            im = im.convert("RGB")
            if deg % 360:
                im = transpose(im, deg)
            im.thumbnail((CELL_W - 16, CELL_H - 44), resample_filter())
            return ImageTk.PhotoImage(im)

    def _on_thumb_ready(self, idx):
        if idx >= len(self.paths):
            return
        try:
            self.thumb_photos[idx] = self._make_thumb_photo(idx)
        except Exception:
            return
        self._place_thumb(idx)

    def _rotate_thumb(self, idx):
        try:
            self.thumb_photos[idx] = self._make_thumb_photo(idx)
        except Exception:
            self.thumb_photos.pop(idx, None)
        self._place_thumb(idx)

    def _on_thumb_wheel(self, event):
        delta = event.delta
        if delta == 0:
            return "break"
        self._thumb_scroll(-int(delta / 120) * 60 if abs(delta) >= 120 else (-1 if delta > 0 else 1) * 60)
        return "break"

    def _thumb_scroll(self, dy):
        c = self.thumb_canvas
        top = c.canvasy(0)
        new = max(0, min(self.thumb_total - c.winfo_height(), top + dy))
        c.yview_moveto(new / max(1.0, float(self.thumb_total)))

    def _on_thumb_click(self, event):
        if not self.paths:
            return
        x = self.thumb_canvas.canvasx(event.x)
        y = self.thumb_canvas.canvasy(event.y)
        row = int(y // CELL_H)
        col = int(x // CELL_W)
        col = min(col, self.thumb_cols - 1)
        idx = row * self.thumb_cols + col
        if 0 <= idx < len(self.paths):
            self._goto_page(idx)

    # ------------------------------------------------------------ 旋转 / 缩放

    def rotate_page(self, delta):
        """delta: -90 左转，+90 右转；勾选「整本」则整本一起转"""
        if not self.paths:
            return
        keep = self.cur_index if self.cur_index >= 0 else 0
        if self.apply_all.get():
            album = self._album_of(keep)
            if album:
                targets = range(album["start"], album["end"])
            else:
                targets = range(len(self.paths))
        else:
            targets = [keep]
        for j in targets:
            self.rot[self.paths[j]] = (self.rot.get(self.paths[j], 0) + delta) % 360
            if j in self.thumb_photos:
                self._rotate_thumb(j)
        self._invalidate_strip()
        self._goto_page(keep)
        deg = self.rot.get(self.paths[keep], 0)
        self.status.configure(text="已旋转 %s（%d 张）当前角度 %d°"
                             % ("整本" if self.apply_all.get() else "本页",
                                len(list(targets)), deg))

    def zoom_by(self, factor):
        new = max(0.4, min(4.0, self.zoom * factor))
        if abs(new - self.zoom) < 1e-3:
            return
        self._apply_zoom(new)

    def zoom_fit(self):
        if abs(self.zoom - 1.0) < 1e-3:
            return
        self._apply_zoom(1.0)

    def _apply_zoom(self, new):
        keep = self.cur_index if self.cur_index >= 0 else 0
        self.zoom = new
        self.zoom_var.set("%d%%" % int(round(new * 100)))
        self._invalidate_strip()
        self.strip.xview_moveto(0.0)
        self._goto_page(keep)
        self.status.configure(text="缩放 %d%%（Ctrl+滚轮也可以调）" % int(round(new * 100)))

    def _invalidate_strip(self):
        for item in self.page_items.values():
            try:
                self.strip.delete(item)
            except Exception:
                pass
        self.page_items.clear()
        self.page_photos.clear()
        self.base_cache.clear()
        self.base_order = []
        if self.paths:
            self._layout_strip()

    # ------------------------------------------------------------ 连读：读到最后一页自动接下一个

    def _bottom_reached(self):
        try:
            return (self.strip.canvasy(0) + self.strip.winfo_height()
                    >= self.strip_total - 2)
        except Exception:
            return False

    def _near_bottom(self):
        """离底部不足两张的高度（算「快到结尾」）"""
        try:
            top = self.strip.canvasy(0)
            vh = self.strip.winfo_height()
            page = self.strip_total / max(1, len(self.paths))
            return top + vh >= self.strip_total - 2 * page - 40
        except Exception:
            return False

    def _inner_root(self, kind, src):
        return extract_dir_for(src) if kind == "arch" else src

    def _next_target(self):
        """下一个要读的位置：(kind, src, folder)；folder=None 表示进这个条目的第一个有图目录"""
        if not self.albums:
            return None
        last = self.albums[-1]
        root = self._inner_root(last["kind"], last["src"])
        nxt = next_dir_after(root, last["folder"])
        if nxt:
            return (last["kind"], last["src"], nxt)
        return self._outer_successor(last["kind"], last["src"])

    def _outer_successor(self, kind, path):
        """在当前条目之后，按树的先序找下一个条目（同级之后 → 逐层上溯）"""
        node = os.path.abspath(path)
        rt = os.path.normcase(os.path.abspath(self.root_dir)) if self.root_dir else None
        for _ in range(10):
            if rt and os.path.normcase(node) == rt:
                return None
            parent = os.path.dirname(node)
            if not parent or os.path.normcase(parent) == os.path.normcase(node):
                return None
            entries = list_entries(parent)
            cur = os.path.normcase(node)
            idx = -1
            for i, e in enumerate(entries):
                if os.path.normcase(os.path.abspath(e[2])) == cur:
                    idx = i
                    break
            if idx >= 0:
                for e in entries[idx + 1:]:
                    return (e[0], e[2], None)
            node = parent
        return None

    def _maybe_more(self, near=False):
        """还有没读进来的图就读下一批；这一本读完了就按目录树接下一本"""
        if self._loading or not self.paths:
            return
        if self.pending:
            chunk = self.pending[:self.batch]
            self.pending = self.pending[self.batch:]
            self._loading = True
            self.status.configure(text="读取中…（本批 %d 张，这本还剩 %d 张没读）"
                                  % (len(chunk), len(self.pending)))
            threading.Thread(target=self._batch_worker,
                             args=(self.token, chunk, "same", None, None, None),
                             daemon=True).start()
            return
        if near or self._bottom_reached():
            if near and not self._bottom_reached() and not self._near_bottom():
                return
            self._maybe_append()

    def _maybe_append(self):
        if not self.autonext.get() or not self.paths or self._loading or not self.albums:
            return
        if self._append_tries > 8:
            return
        target = self._next_target()
        if not target:
            return
        kind, src, folder = target
        key = (kind, os.path.normcase(os.path.abspath(src)),
               os.path.normcase(os.path.abspath(folder)) if folder else "<auto>")
        if key in self._attempted:
            return
        self._attempted.add(key)
        self._append_tries += 1
        self._loading = True
        self._appending = True
        name = os.path.basename(os.path.normpath(folder or src))
        self.status.configure(text="正在接下一个：%s …" % name)
        threading.Thread(target=self._append_worker,
                         args=(self.token, kind, src, folder), daemon=True).start()

    def _append_worker(self, token, kind, src, folder):
        """接下一本：只解压 / 扫名字 / 量前 batch 张尺寸，剩下的留到后面再读"""
        try:
            root = extract_dir_for(src) if kind == "arch" else src
            if kind == "arch" and not os.path.exists(os.path.join(root, ".done")):
                extract_archive(src, root)
            if folder is None:
                folder = first_dir_with_images(root)
            all_paths = list_images(folder) if folder else []
            chunk = all_paths[:self.batch]
            sizes = [read_size(p) for p in chunk]
            self.q.put(("append", token, kind, src, folder, chunk, sizes,
                        all_paths[self.batch:], None))
        except Exception as e:
            self.q.put(("append", token, kind, src, None, [], [], [], str(e)))

    def _on_append_done(self, kind, src, folder, chunk, sizes, rest, err):
        self._loading = False
        self._appending = False
        if err:
            self.status.configure(text="接下一个失败：%s" % str(err).splitlines()[0])
            return
        if not chunk:
            self.status.configure(text="跳过没有图片的位置：%s"
                                  % os.path.basename(os.path.normpath(folder or src)))
            self._maybe_append()
            return
        start = len(self.paths)
        self.paths.extend(chunk)
        self.sizes.extend(sizes)
        self.albums.append({"kind": kind, "src": src, "folder": folder,
                            "start": start, "end": len(self.paths)})
        if kind == "arch":
            self.archive_map[os.path.abspath(extract_dir_for(src))] = src
        self.last_src = (kind, src)
        self._append_tries = 0
        self.pending = rest
        self._extend_layout(start)
        self._append_thumb_cells(start)
        self._strip_sync()
        threading.Thread(target=self._thumb_worker, args=(self.token, chunk, start),
                         daemon=True).start()
        self.status.configure(text="已接上：%s（+%d 张，读到的共 %d 张 / %d 段）"
                              % (os.path.basename(os.path.normpath(folder)),
                                 len(chunk), len(self.paths), len(self.albums)))

    def _on_grow(self, mode, kind, src, folder, chunk, sizes, err):
        """同一本的后一批 / 另一本的第一批已经量好尺寸，接进长图"""
        self._loading = False
        if err or not chunk:
            if mode == "same":
                self.pending = []
            return
        start = len(self.paths)
        self.paths.extend(chunk)
        self.sizes.extend(sizes)
        if mode == "same" and self.albums:
            self.albums[-1]["end"] = len(self.paths)
        else:
            self.albums.append({"kind": kind, "src": src, "folder": folder,
                                "start": start, "end": len(self.paths)})
            if kind == "arch":
                self.archive_map[os.path.abspath(extract_dir_for(src))] = src
            self.last_src = (kind, src)
        self._extend_layout(start)
        self._append_thumb_cells(start)
        self._strip_sync()
        threading.Thread(target=self._thumb_worker, args=(self.token, chunk, start),
                         daemon=True).start()
        left = len(self.pending)
        self.status.configure(text="已载入 %d 张%s" % (
            len(self.paths), ("，这本还剩 %d 张" % left) if left else "（这本读完）"))

    def _extend_layout(self, start):
        c = self.strip
        try:
            keep_top = c.canvasy(0)      # 追加内容时保住当前滚动位置，别让视图跳走
        except Exception:
            keep_top = 0
        cw = max(40, c.winfo_width())
        y = self.strip_total
        for i in range(start, len(self.sizes)):
            w, h = self.sizes[i]
            if w <= 0 or h <= 0:
                self.ys.append(y)
                self.geom.append((y, self.dw, 0))
                continue
            deg = self.rot.get(self.paths[i], 0)
            rw, rh = (h, w) if deg % 180 else (w, h)
            dh = max(1, int(round(rh * float(self.dw) / float(rw))))
            self.ys.append(y)
            self.geom.append((y, self.dw, dh))
            y += dh
        self.strip_total = max(1, y)
        c.configure(scrollregion=(0, 0, max(cw, self.dw), self.strip_total))
        try:
            c.yview_moveto(min(keep_top, max(0, self.strip_total - 1))
                           / max(1.0, float(self.strip_total)))
        except Exception:
            pass

    def _append_thumb_cells(self, start):
        c = self.thumb_canvas
        w = max(c.winfo_width(), CELL_W)
        cols = max(1, int(w // CELL_W))
        if cols != self.thumb_cols:
            self._build_thumb_cells()
            return
        for i in range(start, len(self.paths)):
            r, col = divmod(i, cols)
            x0 = col * CELL_W
            y0 = r * CELL_H
            rect = c.create_rectangle(x0 + 3, y0 + 3, x0 + CELL_W - 3, y0 + CELL_H - 3,
                                      outline="#404040", width=1, fill="#232323")
            self.thumb_rect[i] = rect
            c.create_text(x0 + CELL_W // 2, y0 + CELL_H - 12, text=str(i + 1),
                          fill="#9a9a9a", font=FONT_SMALL)
            ph = c.create_text(x0 + CELL_W // 2, y0 + (CELL_H - 20) // 2,
                               text="…", fill="#5c5c5c", font=FONT_UI)
            self.thumb_cell[i] = [x0, y0, ph]
            if i in self.thumb_photos:
                self._place_thumb(i)
        rows = (len(self.paths) + cols - 1) // cols
        self.thumb_total = rows * CELL_H + 8
        c.configure(scrollregion=(0, 0, w, self.thumb_total))

    def _album_of(self, idx):
        for a in self.albums:
            if a["start"] <= idx < a["end"]:
                return a
        return self.albums[-1] if self.albums else None

    # ------------------------------------------------------------ 右侧连续浏览

    def _layout_strip(self):
        c = self.strip
        cw = max(40, c.winfo_width())
        self.dw = max(40, int(round(cw * self.zoom)))
        content_w = max(cw, self.dw)
        self.off_x = (cw - self.dw) // 2 if self.dw < cw else 0
        self.geom = []
        self.ys = []
        y = 0
        for i, (w, h) in enumerate(self.sizes):
            if w <= 0 or h <= 0:
                self.geom.append((y, self.dw, 0))
                self.ys.append(y)
                continue
            deg = self.rot.get(self.paths[i], 0) if i < len(self.paths) else 0
            rw, rh = (h, w) if deg % 180 else (w, h)
            dh = max(1, int(round(rh * float(self.dw) / float(rw))))
            self.ys.append(y)
            self.geom.append((y, self.dw, dh))
            y += dh
        self.strip_total = max(1, y)
        c.configure(scrollregion=(0, 0, content_w, self.strip_total), yscrollincrement=1)

    def _on_strip_config(self, event=None):
        self._clear_job("_resize_job")
        self._resize_job = self.root.after(120, self._relayout_strip)

    def _relayout_strip(self):
        self._resize_job = None
        if not self.paths:
            return
        frac = self.strip.canvasy(0) / max(1.0, float(self.strip_total))
        self._invalidate_strip()
        self.strip.yview_moveto(frac)
        self._strip_sync(force=True)

    def _on_strip_wheel(self, event):
        delta = event.delta
        if delta == 0:
            return "break"
        if event.state & 0x0004:                    # Ctrl 按下 → 缩放
            self.zoom_by(1.15 if delta > 0 else 0.87)
            return "break"
        if abs(delta) >= 120:
            self._strip_scroll(-int(delta / 120) * 100)
        else:
            self._strip_scroll(-delta)
        return "break"

    def _key_ok(self):
        """按键滚动时若焦点在目录树，就让树自己处理方向键"""
        try:
            focus = self.root.focus_get()
        except Exception:
            focus = None
        return focus is not self.tree

    def _key_up(self, event=None):
        if self._key_ok():
            self._strip_scroll(-90)
        return "break"

    def _key_down(self, event=None):
        if self._key_ok():
            self._strip_scroll(90)
        return "break"

    def _page_up(self, event=None):
        if self._key_ok():
            self._strip_scroll(-int(self.strip.winfo_height() * 0.9))
        return "break"

    def _page_down(self, event=None):
        if self._key_ok():
            self._strip_scroll(int(self.strip.winfo_height() * 0.9))
        return "break"

    def _key_home(self, event=None):
        if self._key_ok():
            self._goto_page(0)
        return "break"

    def _key_end(self, event=None):
        if self._key_ok() and self.paths:
            self._goto_page(len(self.paths) - 1)
        return "break"

    def _strip_scroll(self, dy):
        c = self.strip
        top = c.canvasy(0)
        vh = c.winfo_height()
        new = max(0, min(self.strip_total - vh, top + dy))
        c.yview_moveto(new / max(1.0, float(self.strip_total)))
        self._strip_sync()
        if dy > 0:
            self._maybe_more()
        return "break"

    def _goto_page(self, idx):
        if not self.paths:
            return
        idx = max(0, min(len(self.paths) - 1, idx))
        y = self.ys[idx] if idx < len(self.ys) else 0
        self.strip.yview_moveto(y / max(1.0, float(self.strip_total)))
        self._strip_sync(force=True)
        cell = self.thumb_cell.get(idx)
        if cell:
            ty = cell[1]
            self.thumb_canvas.yview_moveto(
                max(0, ty - self.thumb_canvas.winfo_height() // 3)
                / max(1.0, float(self.thumb_total)))

    def _first_visible(self, top):
        ys = self.ys
        if not ys:
            return -1
        lo, hi = 0, len(ys) - 1
        if top < ys[0]:
            return 0
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if ys[mid] <= top:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def _strip_sync(self, force=False):
        c = self.strip
        if not self.paths or not self.geom:
            return
        top = c.canvasy(0)
        vh = c.winfo_height()
        first = self._first_visible(top)
        if first < 0:
            return

        cur = first
        i = first + 1
        while i < len(self.geom) and self.geom[i][0] < top + 40:
            cur = i
            i += 1
        self._set_current(cur)

        need = set()
        idx = max(0, first - 1)
        while idx < len(self.geom) and self.geom[idx][0] < top + vh + 300:
            y0, w, h = self.geom[idx]
            if h <= 0:
                idx += 1
                continue
            if h <= BAND_H:
                need.add((idx, 0))
            else:
                vis_top = max(0, top - y0)
                vis_bot = min(h, top + vh + 300 - y0)
                b0 = int(vis_top // BAND_H)
                b1 = int(max(b0, (vis_bot - 1) // BAND_H))
                for b in range(b0, b1 + 1):
                    need.add((idx, b))
            idx += 1

        for key in list(self.page_photos.keys()):
            if key not in need:
                item = self.page_items.pop(key, None)
                if item is not None:
                    try:
                        c.delete(item)
                    except Exception:
                        pass
                self.page_photos.pop(key, None)

        for key in sorted(need):
            if key in self.page_photos:
                continue
            self._draw_page_band(key)

        if force:
            for key in list(self.page_items.keys()):
                if key not in need:
                    try:
                        c.delete(self.page_items.pop(key))
                    except Exception:
                        pass
                    self.page_photos.pop(key, None)

        # 快到这一本末尾（还差 3 张以内）就提前备好下一批 / 下一本，滑到底没有等待
        top = c.canvasy(0)
        if self.pending:
            if cur >= len(self.paths) - 3:
                self._schedule_more()
        elif self.autonext.get() and top > 1 and self._near_bottom():
            self._schedule_more()

    def _schedule_more(self):
        if self._more_job is not None:
            return

        def run():
            self._more_job = None
            self._maybe_more(near=True)

        try:
            self._more_job = self.root.after(80, run)
        except Exception:
            self._more_job = None

    def _draw_page_band(self, key):
        i, b = key
        if i >= len(self.paths):
            return
        y0, dw, dh = self.geom[i]
        path = self.paths[i]
        base = None
        if dh > BAND_H:
            base = self._get_base(i, path, dw)
        try:
            if base is None:
                photo = ImageTk.PhotoImage(
                    load_page_image(path, dw, self.rot.get(path, 0)))
            else:
                top = b * BAND_H
                box = (0, top, base.size[0], min(base.size[1], top + BAND_H))
                if box[3] - box[1] <= 0:
                    return
                photo = ImageTk.PhotoImage(base.crop(box))
        except Exception:
            try:
                photo = ImageTk.PhotoImage(self._error_image(dw, min(dh, 120)))
            except Exception:
                return
        item = self.strip.create_image(self.off_x, y0 + b * BAND_H,
                                       anchor="nw", image=photo)
        self.page_photos[key] = photo
        self.page_items[key] = item

    def _get_base(self, i, path, dw):
        deg = self.rot.get(path, 0)
        ck = (i, deg, dw)
        base = self.base_cache.get(ck)
        if base is None:
            try:
                base = load_page_image(path, dw, deg)
            except Exception:
                return None
            self.base_cache[ck] = base
            self.base_order.append(ck)
            while len(self.base_order) > MAX_BASE:
                old = self.base_order.pop(0)
                if old in self.base_cache and old != ck:
                    self.base_cache.pop(old, None)
        return base

    def _error_image(self, w, h):
        return Image.new("RGB", (max(1, w), max(1, h)), (60, 20, 20))

    def _set_current(self, idx):
        if idx == self.cur_index:
            return
        prev = self.cur_index
        self.cur_index = idx
        for i in (prev, idx):
            r = self.thumb_rect.get(i)
            if r:
                try:
                    self.thumb_canvas.itemconfigure(
                        r, outline="#e8a33d" if i == idx else "#404040",
                        width=2 if i == idx else 1)
                except Exception:
                    pass
        self.pos_var.set("第 %d / %d 页%s" % (
            idx + 1 if idx >= 0 else 0, len(self.paths),
            ("（后面还有 %d 张没读）" % len(self.pending)) if self.pending else ""))

    # ------------------------------------------------------------ 关闭

    def on_close(self):
        self._closing = True
        self._save_cfg()
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    if not HAS_PIL:
        root.withdraw()
        messagebox.showerror("缺少依赖",
                             "本工具需要 Pillow 库。\n\n请在命令行执行：\n\n"
                             "pip install pillow\n\n安装后重新打开。")
        return
    try:
        if sys.platform == "win32":
            from ctypes import windll
            windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    app = ViewerApp(root)
    # 支持命令行直接带目录/压缩包：看图工具.exe "D:\漫画\某作品"  /  "D:\漫画\vol1.zip"
    if len(sys.argv) > 1:
        target = sys.argv[1]
        if os.path.isdir(target):
            root.after(120, lambda: app.open_root(target))
        elif is_archive(target):
            root.after(200, lambda: app.open_archive_path(target))
    root.mainloop()


if __name__ == "__main__":
    main()
