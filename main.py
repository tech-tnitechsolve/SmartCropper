"""
╔══════════════════════════════════════════════════════════════════════╗
║  SMART SUBJECT CROPPER v3.4  (Crop-Only, Auto-Frame Edition)       ║
║                                                                      ║
║  • Ngưỡng loại nhỏ: 600px                                          ║
║  • Chỉ crop — KHÔNG scale, KHÔNG tạo canvas/nền giả               ║
║  • Auto-Frame: tự lấy tỷ lệ ảnh gốc làm frame crop               ║
║  • Subject fill: điều chỉnh độ chặt/lỏng vùng crop                ║
║  • Quét subfolder: mỗi subfolder xử lý độc lập (Done/ riêng)      ║
║  • Adaptive Performance: tự điều chỉnh tốc độ theo tải CPU/RAM     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys, os, gc, json, time, shutil, platform, subprocess
from math import gcd
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import OrderedDict
import concurrent.futures
import cv2
import numpy as np
import psutil
from PIL import Image as PILImage
from rembg import new_session, remove
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QProgressBar, QLabel, QTextEdit, QSplitter,
    QSizePolicy, QMessageBox, QGroupBox, QSpinBox, QComboBox,
    QCheckBox, QSlider, QFrame, QScrollArea, QGridLayout,
    QFileDialog, QTabWidget, QRadioButton, QButtonGroup,
    QLineEdit, QStatusBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition, QTimer
from PyQt6.QtGui import (
    QFont, QPixmap, QImage, QColor, QPainter, QPen,
    QPainterPath, QTextCursor,
)

# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 1 — CONSTANTS                                      ║
# ╚══════════════════════════════════════════════════════════════╝

APP_TITLE = "Smart Subject Cropper v3.4"
SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".jfif", ".raw", ".dng", ".heic", ".heif", ".avif", ".svg", ".jp2", ".exr", ".hdr" }
THUMB_PX = 128
PREVIEW_PX = 96
MASK_MAX_DIM = 1024
SETTINGS_FILE = Path(__file__).parent / "cropper_settings.json"

MAX_GRID_CARDS = 500
GC_EVERY_N = 25
RAM_THROTTLE_PCT = 85

# ╔══════════════════════════════════════════════════════════════╗
# ║  THUMBNAIL LOADER THREAD                                    ║
# ╚══════════════════════════════════════════════════════════════╝

class ThumbnailLoader(QThread):
    loaded = pyqtSignal(int, object)  # index, numpy array

    def __init__(self, files):
        super().__init__()
        self.files = files

    def run(self):
        for i, f in enumerate(self.files):
            if self.isInterruptionRequested():
                break
            try:
                with PILImage.open(str(f)) as img:
                    img = img.convert("RGB")
                    img.thumbnail((PREVIEW_PX, PREVIEW_PX), PILImage.LANCZOS)
                    arr = np.array(img)
                self.loaded.emit(i, arr)
            except Exception:
                pass  # Skip on error

# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 2 — SETTINGS                                       ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class CropSettings:
    model_name: str = "u2net"
    padding_px: int = 10
    padding_top_px: int = 10
    padding_bottom_px: int = 10
    padding_left_px: int = 10
    padding_right_px: int = 10
    use_uniform_padding: bool = True
    edge_threshold_pct: float = 2.5
    edge_gap_px: int = 5
    # ── Giữ tương thích file cũ (không dùng nữa) ──
    frame_index: int = 0
    target_width: int = 0
    target_height: int = 0
    auto_output_size: bool = True
    white_bg: bool = True
    max_upscale: float = 2.0
    # ────────────────────────────────────────────────
    png_compress: int = 9
    min_size_px: int = 700
    subject_fill: float = 92.0
    mask_threshold: int = 120
    output_folder: str = "Done"
    rejected_folder: str = "Loại bỏ"
    cpu_limit: float = 20.0
    scan_subfolders: bool = False
    adaptive_speed: bool = True
    parallel_mode: str = "auto"
    max_workers: int = 1

    def save(self, path: Path = SETTINGS_FILE):
        try:
            path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "CropSettings":
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                valid = {f.name for f in cls.__dataclass_fields__.values()}
                return cls(**{k: v for k, v in data.items() if k in valid})
        except Exception:
            pass
        return cls()

    @classmethod
    def defaults(cls) -> "CropSettings":
        return cls()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 3 — THEME                                          ║
# ╚══════════════════════════════════════════════════════════════╝

C = dict(
    bg1="#1a1a2e", bg2="#16213e", bg3="#0f3460",
    bg_in="#1c2541", bg_hov="#254068",
    acc="#00d2ff", acc_h="#00b4d8", acc_d="#0077b6",
    ok="#00c896", warn="#f4a261", err="#e63946", skip="#8d99ae",
    t1="#edf2f4", t2="#8d99ae", t_off="#4a5568",
    brd="#2d3a5c", brd_f="#00d2ff",
    dz_bg="#0d1b3e", th_bg="#0f1a3a",
)

def build_qss() -> str:
    return f"""
    QMainWindow,QWidget{{background:{C['bg1']};color:{C['t1']};font-family:"Segoe UI","Noto Sans",Arial,sans-serif;font-size:13px;}}
    QScrollArea{{border:none;background:transparent;}}
    QScrollBar:vertical{{background:{C['bg2']};width:8px;border-radius:4px;}}
    QScrollBar::handle:vertical{{background:{C['brd']};border-radius:4px;min-height:28px;}}
    QScrollBar::handle:vertical:hover{{background:{C['bg_hov']};}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
    QScrollBar:horizontal{{background:{C['bg2']};height:8px;border-radius:4px;}}
    QScrollBar::handle:horizontal{{background:{C['brd']};border-radius:4px;min-width:28px;}}
    QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}
    QGroupBox{{background:{C['bg2']};border:1px solid {C['brd']};border-radius:9px;margin-top:10px;padding:14px 10px 8px 10px;font-weight:600;font-size:12px;}}
    QGroupBox::title{{subcontrol-origin:margin;subcontrol-position:top left;left:12px;padding:1px 8px;color:{C['acc']};background:{C['bg2']};border-radius:4px;}}
    QPushButton{{background:{C['bg3']};color:{C['t1']};border:1px solid {C['brd']};border-radius:7px;padding:7px 14px;font-weight:600;min-height:14px;}}
    QPushButton:hover{{background:{C['bg_hov']};border-color:{C['acc']};}}
    QPushButton:pressed{{background:{C['acc_d']};}}
    QPushButton:disabled{{background:{C['bg_in']};color:{C['t_off']};}}
    QPushButton[class="primary"]{{background:{C['acc']};color:#000;border:none;font-weight:700;}}
    QPushButton[class="primary"]:hover{{background:{C['acc_h']};}}
    QPushButton[class="primary"]:pressed{{background:{C['acc_d']};color:#fff;}}
    QPushButton[class="danger"]{{background:{C['err']};color:#fff;border:none;}}
    QPushButton[class="danger"]:hover{{background:#ff4d5a;}}
    QPushButton[class="warn"]{{background:{C['warn']};color:#000;border:none;font-weight:700;}}
    QPushButton[class="warn"]:hover{{background:#e6924a;}}
    QSpinBox,QComboBox{{background:{C['bg_in']};color:{C['t1']};border:1px solid {C['brd']};border-radius:5px;padding:5px 8px;min-height:14px;font-size:12px;}}
    QSpinBox:focus{{border-color:{C['brd_f']};}}
    QSpinBox::up-button{{width:20px;border-left:1px solid {C['brd']};border-top-right-radius:5px;background:{C['bg3']};}}
    QSpinBox::down-button{{width:20px;border-left:1px solid {C['brd']};border-bottom-right-radius:5px;background:{C['bg3']};}}
    QComboBox::drop-down{{border-left:1px solid {C['brd']};width:26px;border-top-right-radius:5px;border-bottom-right-radius:5px;background:{C['bg3']};}}
    QComboBox QAbstractItemView{{background:{C['bg2']};color:{C['t1']};border:1px solid {C['brd']};selection-background-color:{C['acc_d']};padding:3px;}}
    QCheckBox{{color:{C['t1']};spacing:6px;font-size:12px;}}
    QCheckBox::indicator{{width:17px;height:17px;border-radius:3px;border:2px solid {C['brd']};background:{C['bg_in']};}}
    QCheckBox::indicator:checked{{background:{C['acc']};border-color:{C['acc']};}}
    QRadioButton{{color:{C['t1']};spacing:6px;font-size:12px;}}
    QRadioButton::indicator{{width:16px;height:16px;border-radius:8px;border:2px solid {C['brd']};background:{C['bg_in']};}}
    QRadioButton::indicator:checked{{background:{C['acc']};border-color:{C['acc']};}}
    QProgressBar{{background:{C['bg_in']};border:1px solid {C['brd']};border-radius:7px;text-align:center;color:{C['t1']};font-weight:600;min-height:18px;font-size:11px;}}
    QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {C['acc_d']},stop:1 {C['acc']});border-radius:6px;}}
    QTextEdit{{background:{C['bg_in']};color:{C['t1']};border:1px solid {C['brd']};border-radius:7px;padding:6px;font-family:"Cascadia Code","Consolas",monospace;font-size:11px;}}
    QLineEdit{{background:{C['bg_in']};color:{C['t1']};border:1px solid {C['brd']};border-radius:5px;padding:5px 8px;font-size:12px;}}
    QLineEdit:focus{{border-color:{C['brd_f']};}}
    QSlider::groove:horizontal{{background:{C['bg_in']};height:5px;border-radius:2px;}}
    QSlider::handle:horizontal{{background:{C['acc']};width:15px;height:15px;margin:-5px 0;border-radius:7px;}}
    QSlider::handle:horizontal:hover{{background:{C['acc_h']};}}
    QSlider::sub-page:horizontal{{background:{C['acc_d']};border-radius:2px;}}
    QTabWidget::pane{{border:1px solid {C['brd']};border-radius:7px;background:{C['bg2']};top:-1px;}}
    QTabBar::tab{{background:{C['bg_in']};color:{C['t2']};border:1px solid {C['brd']};border-bottom:none;padding:6px 14px;margin-right:1px;border-top-left-radius:7px;border-top-right-radius:7px;font-weight:600;font-size:11px;}}
    QTabBar::tab:selected{{background:{C['bg2']};color:{C['acc']};}}
    QTabBar::tab:hover:!selected{{background:{C['bg_hov']};color:{C['t1']};}}
    QToolTip{{background:{C['bg3']};color:{C['t1']};border:1px solid {C['acc']};border-radius:5px;padding:4px 7px;font-size:11px;}}
    QSplitter::handle{{background:{C['brd']};}}
    QSplitter::handle:vertical{{height:3px;}}
    QStatusBar{{background:{C['bg2']};color:{C['t2']};border-top:1px solid {C['brd']};font-size:11px;padding:2px 8px;}}
    QStatusBar QLabel{{color:{C['t2']};font-size:11px;padding:0 6px;font-family:"Cascadia Code","Consolas",monospace;}}
    """

# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 4 — SYSTEM                                         ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class SysInfo:
    os_name: str = ""
    cpu_name: str = ""
    cores_p: int = 1
    cores_l: int = 1
    ram_gb: float = 0
    gpu: str = "N/A"
    has_cuda: bool = False

def detect_system() -> SysInfo:
    cp = psutil.cpu_count(logical=False) or 1
    cl = psutil.cpu_count(logical=True) or 1
    ram = psutil.virtual_memory().total / (1024**3)
    cn = platform.processor() or ""
    if not cn and platform.system() == "Windows":
        try:
            r = subprocess.run(["wmic", "cpu", "get", "name"],
                               capture_output=True, text=True, timeout=5)
            ls = [l.strip() for l in r.stdout.split("\n") if l.strip()]
            if len(ls) > 1:
                cn = ls[1]
        except Exception:
            pass
    gpu, cuda = "N/A", False
    try:
        import onnxruntime as ort
        if "CUDAExecutionProvider" in ort.get_available_providers():
            cuda = True; gpu = "NVIDIA (CUDA)"
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    gpu = r.stdout.strip().split("\n")[0]
            except Exception:
                pass
    except ImportError:
        pass
    return SysInfo(os_name=f"{platform.system()} {platform.release()}",
                   cpu_name=cn or "N/A", cores_p=cp, cores_l=cl,
                   ram_gb=ram, gpu=gpu, has_cuda=cuda)

def lower_process_priority():
    try:
        p = psutil.Process(os.getpid())
        if platform.system() == "Windows":
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            p.nice(10)
    except Exception:
        pass


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 5 — ADAPTIVE PERFORMANCE CONTROLLER                ║
# ╚══════════════════════════════════════════════════════════════╝

class AdaptiveThrottle:
    """Bộ điều khiển tốc độ thích ứng — feedback loop CPU/RAM."""

    def __init__(self, cpu_target: float = 20.0, adaptive: bool = True):
        self.cpu_target = cpu_target
        self.adaptive = adaptive
        self._sleep_time = 0.0 if adaptive else 0.3
        self._min_sleep = 0.0
        self._max_sleep = 3.0
        self._history: list[float] = []
        self._warmup = 5
        self._count = 0
        self._last_cpu = 0.0
        self._last_ram = 0.0
        self._speed_label = "🚀 Tối đa"

    def tick(self) -> tuple[float, float, str]:
        cpu = psutil.cpu_percent(interval=0.08)
        ram = psutil.virtual_memory().percent
        self._last_cpu = cpu
        self._last_ram = ram
        self._count += 1

        if ram > RAM_THROTTLE_PCT:
            gc.collect(); time.sleep(3.0)
            self._speed_label = "🔴 RAM cao — chờ"
            return cpu, ram, self._speed_label

        if not self.adaptive:
            if cpu > self.cpu_target:
                ov = (cpu - self.cpu_target) / 100.0
                time.sleep(min(2.5, 0.2 + ov * 4.0))
                self._speed_label = f"⏳ Chờ (CPU {cpu:.0f}%)"
            else:
                self._speed_label = "▶️ Bình thường"
            return cpu, ram, self._speed_label

        self._history.append(cpu)
        if len(self._history) > 20:
            self._history = self._history[-20:]

        if self._count <= self._warmup:
            self._speed_label = f"🔄 Khởi động ({self._count}/{self._warmup})"
            time.sleep(0.1)
            return cpu, ram, self._speed_label

        recent = self._history[-5:] if len(self._history) >= 3 else [cpu]
        avg_cpu = sum(recent) / len(recent)
        target = self.cpu_target

        if avg_cpu < target * 0.5:
            self._sleep_time *= 0.5; self._speed_label = "🚀 Tối đa"
        elif avg_cpu < target * 0.7:
            self._sleep_time *= 0.7; self._speed_label = "⚡ Nhanh"
        elif avg_cpu < target * 0.9:
            self._speed_label = "✅ Tối ưu"
        elif avg_cpu < target * 1.1:
            self._sleep_time = max(self._sleep_time, 0.05)
            self._sleep_time *= 1.1; self._speed_label = "✅ Tối ưu"
        elif avg_cpu < target * 1.5:
            self._sleep_time = max(self._sleep_time, 0.1)
            self._sleep_time *= 1.3; self._speed_label = "⏳ Giảm tốc"
        else:
            self._sleep_time = max(self._sleep_time, 0.3)
            self._sleep_time *= 1.5; self._speed_label = "🐌 Tiết kiệm"

        self._sleep_time = max(self._min_sleep,
                               min(self._sleep_time, self._max_sleep))
        if self._sleep_time > 0.01:
            time.sleep(self._sleep_time)
        return cpu, ram, self._speed_label

    def reset(self):
        self._sleep_time = 0.0; self._history.clear(); self._count = 0

    @property
    def current_sleep(self) -> float:
        return self._sleep_time


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 6 — FILE SCANNER                                   ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class FolderGroup:
    folder: Path
    files: list[Path]
    rel_path: str

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def label(self) -> str:
        return self.rel_path if self.rel_path else "📂 (thư mục gốc)"


def scan_folder(root: str, recursive: bool = False) -> list[FolderGroup]:
    root_path = Path(root)
    groups: OrderedDict[str, FolderGroup] = OrderedDict()
    all_files = root_path.rglob("*") if recursive else root_path.iterdir()
    for f in all_files:
        if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXT:
            continue
        parts_lower = [p.lower() for p in f.relative_to(root_path).parts]
        if any(p in ("done", "loại bỏ", "loai bo") for p in parts_lower[:-1]):
            continue
        parent = f.parent
        key = str(parent)
        if key not in groups:
            try:
                rel = parent.relative_to(root_path)
                rel_str = str(rel) if str(rel) != "." else ""
            except ValueError:
                rel_str = str(parent)
            groups[key] = FolderGroup(
                folder=parent, files=[], rel_path=rel_str)
        groups[key].files.append(f)
    return list(groups.values())


class FolderScanner(QThread):
    scanned = pyqtSignal(list, str)
    error = pyqtSignal(str)

    def __init__(self, path: str, recursive: bool = False):
        super().__init__()
        self.path = path
        self.recursive = recursive

    def run(self):
        try:
            groups = scan_folder(self.path, self.recursive)
            self.scanned.emit(groups, self.path)
        except Exception as e:
            self.error.emit(str(e))


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 7 — AI CROPPER ENGINE  (Crop-Only, Auto-Frame)     ║
# ║                                                              ║
# ║  NGUYÊN TẮC:                                                ║
# ║  ┌──────────────────────────────────────────────────────┐   ║
# ║  │  1. Subject max(w,h) < 600px  → LOẠI ngay           │   ║
# ║  │  2. Subject ≥ 600px → CROP + giữ ratio ảnh gốc      │   ║
# ║  │  3. Chỉ EXPAND, không trim, không scale, không fake  │   ║
# ║  └──────────────────────────────────────────────────────┘   ║
# ║                                                              ║
# ║  VÍ DỤ: Ảnh gốc 1200×800 (3:2), crop ra 900×700           ║
# ║  → ratio gốc = 3:2 → cần 1050×700                          ║
# ║  → mở rộng width thêm 150px pixel gốc                      ║
# ║  → kết quả: 1050×700 (3:2) ✓                               ║
# ╚══════════════════════════════════════════════════════════════╝

class SmartCropper:
    def __init__(self, settings: CropSettings | None = None):
        self.settings = settings or CropSettings()
        self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = new_session(self.settings.model_name)
        return self._session

    def release(self):
        self._session = None; gc.collect()

    def _prepare_mask_image(self, img: PILImage.Image) -> tuple[PILImage.Image, float]:
        w, h = img.size
        max_dim = min(max(w, h), MASK_MAX_DIM)
        if max(w, h) <= MASK_MAX_DIM:
            return img.copy(), 1.0
        scale = max_dim / max(w, h)
        resized = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            PILImage.LANCZOS)
        return resized, scale

    # ── Mask generation ──────────────────────────────────────
    def _get_mask(self, img: PILImage.Image) -> np.ndarray:
        s = self.settings
        raw = remove(img, session=self.session, only_mask=True)
        mask = np.array(raw)
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_RGB2GRAY)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)
        _, sure = cv2.threshold(
            mask, s.mask_threshold, 255, cv2.THRESH_BINARY)
        _, prob = cv2.threshold(
            mask, max(25, s.mask_threshold - 55), 255, cv2.THRESH_BINARY)
        ks = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        kl = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        sure = cv2.morphologyEx(sure, cv2.MORPH_CLOSE, kl, iterations=3)
        sure = cv2.morphologyEx(sure, cv2.MORPH_OPEN, ks, iterations=1)
        combo = cv2.bitwise_or(sure, prob)
        combo = cv2.morphologyEx(combo, cv2.MORPH_CLOSE, ks, iterations=1)
        n_s, lb_s, st_s, _ = cv2.connectedComponentsWithStats(sure, 8)
        if n_s <= 1:
            return sure
        main_lbl = 1 + int(np.argmax(st_s[1:, cv2.CC_STAT_AREA]))
        main_mask = (lb_s == main_lbl).astype(np.uint8) * 255
        n_c, lb_c, _, _ = cv2.connectedComponentsWithStats(combo, 8)
        if n_c > 1:
            overlap = set(np.unique(lb_c[main_mask > 0]))
            overlap.discard(0)
            expanded = np.zeros_like(combo)
            for lbl in overlap:
                expanded[lb_c == lbl] = 255
            final = cv2.bitwise_or(main_mask, expanded)
            return cv2.morphologyEx(final, cv2.MORPH_CLOSE, ks, iterations=1)
        return main_mask

    @staticmethod
    def _bbox(mask):
        coords = np.argwhere(mask > 0)
        if len(coords) == 0:
            return None
        y1, x1 = coords.min(axis=0)
        y2, x2 = coords.max(axis=0)
        return int(x1), int(y1), int(x2), int(y2)

    def _detect_edges(self, mask, x1, y1, x2, y2, w, h):
        s = self.settings
        gap = s.edge_gap_px
        by = max(3, int(h * s.edge_threshold_pct / 100))
        bx = max(3, int(w * s.edge_threshold_pct / 100))
        mp = max(3, int(min(w, h) * 0.003))
        mt = int(np.sum(mask[0:by, :] > 0)) > mp
        mb = int(np.sum(mask[h - by:, :] > 0)) > mp
        ml = int(np.sum(mask[:, 0:bx] > 0)) > mp
        mr = int(np.sum(mask[:, w - bx:] > 0)) > mp
        gt, gb = y1 <= gap, y2 >= h - 1 - gap
        gl, gr = x1 <= gap, x2 >= w - 1 - gap
        edges = dict(top=mt or gt, bottom=mb or gb,
                     left=ml or gl, right=mr or gr)
        if edges["top"] and not gt and y1 > by * 3:
            edges["top"] = False
        if edges["bottom"] and not gb and y2 < h - 1 - by * 3:
            edges["bottom"] = False
        if edges["left"] and not gl and x1 > bx * 3:
            edges["left"] = False
        if edges["right"] and not gr and x2 < w - 1 - bx * 3:
            edges["right"] = False
        return edges

    # ──────────────────────────────────────────────────────────
    #  _expand_side: mở rộng 1 trục — KHÔNG BAO GIỜ TRIM
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def _expand_side(lo, hi, img_max, target_sz, edge_lo, edge_hi):
        current_sz = hi - lo
        if target_sz <= current_sz:
            return lo, hi

        extra = target_sz - current_sz
        if edge_lo and not edge_hi:
            hi = min(img_max, hi + extra)
        elif edge_hi and not edge_lo:
            lo = max(0, lo - extra)
        else:
            half = extra // 2
            lo = max(0, lo - half)
            hi = min(img_max, hi + (extra - half))

        actual = hi - lo
        if actual < target_sz:
            deficit = target_sz - actual
            if lo == 0:
                hi = min(img_max, hi + deficit)
            elif hi == img_max:
                lo = max(0, lo - deficit)

        return lo, hi

    # ──────────────────────────────────────────────────────────
    #  _expand_for_fill: subject chiếm ~fill% vùng crop
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def _expand_for_fill(cx1, cy1, cx2, cy2,
                         sx1, sy1, sx2, sy2,
                         img_w, img_h, fill_pct, edges):
        if fill_pct >= 100.0:
            return cx1, cy1, cx2, cy2
        fill = max(fill_pct / 100.0, 0.1)
        sw, sh = sx2 - sx1, sy2 - sy1
        cw, ch = cx2 - cx1, cy2 - cy1
        want_w = max(cw, int(sw / fill))
        want_h = max(ch, int(sh / fill))

        cx1, cx2 = SmartCropper._expand_side(
            cx1, cx2, img_w, want_w,
            edges["left"], edges["right"])
        cy1, cy2 = SmartCropper._expand_side(
            cy1, cy2, img_h, want_h,
            edges["top"], edges["bottom"])
        return cx1, cy1, cx2, cy2

    # ──────────────────────────────────────────────────────────
    #  _expand_to_ratio: mở rộng crop theo ratio cho trước
    #
    #  LUÔN EXPAND THEO CẠNH LỚN — KHÔNG TRIM, KHÔNG FAKE
    #
    #  VD: crop 812×752, ratio 1:1
    #    → cạnh lớn 812 → target 812×812
    #    → expand height +60px pixel gốc
    #
    #  VD: crop 600×800, ratio 3:2
    #    → option A: giữ w=600, h=400 → TRIM! bỏ
    #    → option B: giữ h=800, w=1200 → EXPAND ✓
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def _expand_to_ratio(cx1, cy1, cx2, cy2,
                         img_w, img_h, ratio_w, ratio_h, edges):
        if ratio_w <= 0 or ratio_h <= 0:
            return cx1, cy1, cx2, cy2
        cw, ch = cx2 - cx1, cy2 - cy1
        if cw <= 0 or ch <= 0:
            return cx1, cy1, cx2, cy2

        target_r = ratio_w / ratio_h
        current_r = cw / ch
        if abs(current_r - target_r) < 0.01:
            return cx1, cy1, cx2, cy2

        # Option A: giữ width, tính height → ha = cw / target_r
        ha = int(cw / target_r)
        # Option B: giữ height, tính width → wb = ch * target_r
        wb = int(ch * target_r)

        # Chỉ chọn option nào KHÔNG trim (kết quả >= hiện tại)
        ok_a = (ha >= ch)  # expand height hoặc giữ nguyên
        ok_b = (wb >= cw)  # expand width hoặc giữ nguyên

        if ok_a and ok_b:
            # Cả hai expand → chọn ít mở rộng hơn
            if cw * ha <= wb * ch:
                target_w, target_h = cw, ha
            else:
                target_w, target_h = wb, ch
        elif ok_a:
            target_w, target_h = cw, ha
        elif ok_b:
            target_w, target_h = wb, ch
        else:
            # Không option nào expand → lấy cạnh lớn làm gốc
            if cw >= ch:
                target_w, target_h = cw, max(ch, int(cw / target_r))
            else:
                target_w, target_h = max(cw, int(ch * target_r)), ch

        cx1, cx2 = SmartCropper._expand_side(
            cx1, cx2, img_w, target_w,
            edges["left"], edges["right"])
        cy1, cy2 = SmartCropper._expand_side(
            cy1, cy2, img_h, target_h,
            edges["top"], edges["bottom"])
        return cx1, cy1, cx2, cy2

    # ── Di chuyển ảnh lỗi ────────────────────────────────────
    def _move_rejected(self, path: Path) -> Path:
        d = path.parent / self.settings.rejected_folder
        d.mkdir(exist_ok=True)
        dest = d / path.name
        i = 1
        while dest.exists():
            dest = d / f"{path.stem}_{i}{path.suffix}"
            i += 1
        shutil.move(str(path), str(dest))
        return dest

    # ── XỬ LÝ CHÍNH ─────────────────────────────────────────
    def process(self, image_path: Path) -> dict:
        s = self.settings
        r = dict(status="error", reason="", input_path=image_path,
                 output_path=None, moved_path=None,
                 original_size=(0, 0), subject_size=(0, 0),
                 thumbnail=None, edges=None)
        try:
            img = PILImage.open(image_path).convert("RGB")
            w, h = img.size
            r["original_size"] = (w, h)

            # ── Tính ratio ảnh gốc ──
            g = gcd(w, h)
            orig_rw, orig_rh = w // g, h // g

            # ══ CHECK 1: ảnh gốc quá nhỏ → loại ngay ══
            if max(w, h) < s.min_size_px:
                img.close(); del img
                dest = self._move_rejected(image_path)
                r.update(
                    status="rejected",
                    reason=f"Ảnh nhỏ {w}×{h} (cần ≥{s.min_size_px}px)",
                    moved_path=dest)
                return r

            # ══ AI: tạo mask + tìm subject ══
            mask_img, scale = self._prepare_mask_image(img)
            mask = self._get_mask(mask_img)
            bbox = self._bbox(mask)
            if bbox is None:
                img.close(); del img, mask_img, mask
                r.update(status="skipped",
                         reason="Không tìm thấy chủ thể")
                return r

            x1, y1, x2, y2 = bbox
            sw, sh = int((x2 - x1) / scale), int((y2 - y1) / scale)
            x1 = min(max(int(round(x1 / scale)), 0), w - 1)
            y1 = min(max(int(round(y1 / scale)), 0), h - 1)
            x2 = min(max(int(round(x2 / scale)), x1 + 1), w)
            y2 = min(max(int(round(y2 / scale)), y1 + 1), h)
            sw, sh = x2 - x1, y2 - y1
            r["subject_size"] = (sw, sh)

            # ══ CHECK 2: subject quá nhỏ → loại ══
            if max(sw, sh) < s.min_size_px:
                img.close(); del img, mask
                dest = self._move_rejected(image_path)
                r.update(
                    status="rejected",
                    reason=f"Subject nhỏ {sw}×{sh} "
                           f"(cần ≥{s.min_size_px}px)",
                    moved_path=dest)
                return r

            # ══ Phát hiện cạnh sát biên ══
            edges = self._detect_edges(
                mask, int(x1 * scale), int(y1 * scale),
                int(x2 * scale), int(y2 * scale),
                mask.shape[1], mask.shape[0])
            r["edges"] = edges
            del mask, mask_img

            # ══ BƯỚC 1: Crop cơ bản (bbox + padding + edge) ══
            if s.use_uniform_padding:
                pt = pb = pl = pr = s.padding_px
            else:
                pt, pb = s.padding_top_px, s.padding_bottom_px
                pl, pr = s.padding_left_px, s.padding_right_px

            cy1 = 0 if edges["top"] else max(0, y1 - pt)
            cy2 = h if edges["bottom"] else min(h, y2 + pb)
            cx1 = 0 if edges["left"] else max(0, x1 - pl)
            cx2 = w if edges["right"] else min(w, x2 + pr)

            # ══ BƯỚC 2: Mở rộng theo subject_fill ══
            cx1, cy1, cx2, cy2 = self._expand_for_fill(
                cx1, cy1, cx2, cy2,
                x1, y1, x2, y2,
                w, h, s.subject_fill, edges)

            # ══ BƯỚC 3: Mở rộng theo RATIO ẢNH GỐC ══
            #  Ảnh gốc 1200×800 (3:2) → crop cũng phải 3:2
            #  Chỉ expand pixel gốc, không trim, không fake
            cx1, cy1, cx2, cy2 = self._expand_to_ratio(
                cx1, cy1, cx2, cy2,
                w, h, orig_rw, orig_rh, edges)

            # ── Clamp toạ độ ──
            cx1 = max(0, cx1)
            cy1 = max(0, cy1)
            cx2 = min(w, cx2)
            cy2 = min(h, cy2)
            cw, ch_ = cx2 - cx1, cy2 - cy1

            # ══ CHECK 3: crop quá nhỏ → loại ══
            if cw < 1 or ch_ < 1 or max(cw, ch_) < s.min_size_px:
                img.close(); del img
                dest = self._move_rejected(image_path)
                r.update(
                    status="rejected",
                    reason=f"Crop nhỏ {cw}×{ch_} "
                           f"(cần ≥{s.min_size_px}px)",
                    moved_path=dest)
                return r

            # ══ BƯỚC 4: Crop & lưu (100% pixel gốc) ══
            crop = img.crop((cx1, cy1, cx2, cy2))
            img.close(); del img

            out_dir = image_path.parent / s.output_folder
            out_dir.mkdir(exist_ok=True)
            out = out_dir / f"{image_path.stem}.png"
            crop.save(out, format="PNG", compress_level=s.png_compress)

            # ── Thumbnail ──
            thumb = crop.copy()
            thumb.thumbnail((PREVIEW_PX, PREVIEW_PX), PILImage.LANCZOS)
            thumb_data = np.array(thumb.convert("RGB")).copy()
            del crop, thumb

            # ── Log info ──
            evn = {"top": "trên", "bottom": "dưới",
                   "left": "trái", "right": "phải"}
            es = ", ".join(evn[k] for k, v in edges.items() if v) or "không"
            cg = gcd(cw, ch_)
            crop_ratio = f"{cw//cg}:{ch_//cg}" if cg > 0 else "?"
            actual_fill = (sw * sh) / max(cw * ch_, 1) * 100

            r.update(
                status="success",
                reason=f"{w}×{h}({orig_rw}:{orig_rh}) → "
                       f"{cw}×{ch_}({crop_ratio}) "
                       f"Fill:{actual_fill:.0f}% Biên:{es}",
                output_path=out, thumbnail=thumb_data)
            return r

        except Exception as e:
            r.update(status="error", reason=str(e))
            return r


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 8 — BATCH WORKER (Subfolder + Adaptive)            ║
# ╚══════════════════════════════════════════════════════════════╝

class BatchWorker(QThread):
    sig_progress = pyqtSignal(int, int, dict)
    sig_file_start = pyqtSignal(int, str)
    sig_finished = pyqtSignal(list)
    sig_log = pyqtSignal(str)
    sig_sysload = pyqtSignal(float, float, str)
    sig_folder_start = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self._mx = QMutex(); self._cond = QWaitCondition()
        self._paused = self._cancelled = False
        self.groups: list[FolderGroup] = []
        self.settings = CropSettings()
        self._cropper: SmartCropper | None = None

    @property
    def total_files(self) -> int:
        return sum(g.count for g in self.groups)

    def set_folder(self, path: str, recursive: bool = False):
        self.groups = scan_folder(path, recursive)

    def pause(self):
        self._mx.lock(); self._paused = True; self._mx.unlock()

    def resume(self):
        self._mx.lock(); self._paused = False
        self._cond.wakeAll(); self._mx.unlock()

    def cancel(self):
        self._mx.lock(); self._cancelled = True; self._paused = False
        self._cond.wakeAll(); self._mx.unlock()

    def release(self):
        if self._cropper:
            self._cropper.release(); self._cropper = None
        gc.collect()

    def _check_pause(self):
        self._mx.lock()
        while self._paused and not self._cancelled:
            self._cond.wait(self._mx)
        self._mx.unlock()

    def _calc_parallel_workers(self) -> int:
        mode = self.settings.parallel_mode
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False) or logical
        if mode == "off":
            return 1
        if mode == "on":
            return min(max(1, self.settings.max_workers), logical, physical)
        # auto
        if self.settings.cpu_limit < 35:
            return 1
        workers = min(4, logical, physical,
                      max(1, int(self.settings.cpu_limit // 25)))
        return workers

    def _process_file(self, fp: Path) -> dict:
        cropper = SmartCropper(self.settings)
        try:
            return cropper.process(fp)
        finally:
            cropper.release()

    def run(self):
        self._cancelled = self._paused = False
        total = self.total_files
        if total == 0:
            self.sig_log.emit("⚠️ Không có ảnh")
            self.sig_finished.emit([]); return

        lower_process_priority()
        n_groups = len(self.groups)

        self.sig_log.emit(
            f"🚀 Bắt đầu: {total:,} ảnh trong {n_groups} thư mục\n"
            f"   Model: {self.settings.model_name} │ "
            f"CPU ≤ {self.settings.cpu_limit:.0f}%\n"
            f"   Frame: AUTO (theo ảnh gốc) │ "
            f"Fill: {self.settings.subject_fill:.0f}%\n"
            f"   Loại nếu subject < {self.settings.min_size_px}px │ "
            f"Adaptive: "
            f"{'BẬT 🧠' if self.settings.adaptive_speed else 'TẮT'}\n"
            f"   Chế độ: CROP pixel gốc (không scale/nền giả)\n")

        parallel_workers = self._calc_parallel_workers()
        if parallel_workers > 1:
            self.sig_log.emit(
                f"   Batch mode: {parallel_workers} luồng song song nếu phần cứng cho phép")
        else:
            self._cropper = SmartCropper(self.settings)

        throttle = AdaptiveThrottle(
            cpu_target=self.settings.cpu_limit,
            adaptive=self.settings.adaptive_speed)

        cnt = dict(success=0, skipped=0, rejected=0, error=0)
        t0 = time.time()
        global_idx = 0

        for gi, group in enumerate(self.groups):
            if self._cancelled:
                break
            self.sig_log.emit(
                f"\n{'─'*50}\n"
                f"📂 [{gi+1}/{n_groups}] {group.label or '(gốc)'} "
                f"— {group.count} ảnh\n"
                f"   → Done: {group.folder / self.settings.output_folder}\n"
                f"   → Loại: "
                f"{group.folder / self.settings.rejected_folder}\n"
                f"{'─'*50}")
            self.sig_folder_start.emit(group.label, group.count)

            if parallel_workers > 1:
                with concurrent.futures.ThreadPoolExecutor(
                        max_workers=parallel_workers) as executor:
                    futures = {}
                    for fp in group.files:
                        if self._cancelled:
                            break
                        self._check_pause()
                        future = executor.submit(self._process_file, fp)
                        futures[future] = fp
                        self.sig_file_start.emit(
                            global_idx + len(futures) - 1, fp.name)

                    for future in concurrent.futures.as_completed(futures):
                        if self._cancelled:
                            self.sig_log.emit("🛑 Đã huỷ!"); break
                        self._check_pause()

                        cpu, ram, speed = throttle.tick()
                        self.sig_sysload.emit(cpu, ram, speed)

                        fp = futures[future]
                        try:
                            res = future.result()
                        except Exception as exc:
                            res = dict(status="error",
                                       reason=str(exc),
                                       input_path=fp,
                                       output_path=None)
                        cnt[res["status"]] = cnt.get(res["status"], 0) + 1

                        icon = dict(success="✅", skipped="⏭️",
                                    rejected="📦", error="❌").get(
                            res["status"], "❓")

                        if total > 1000:
                            if global_idx % 50 == 0 or res["status"] != "success":
                                self.sig_log.emit(
                                    f"{icon} [{global_idx+1:,}/{total:,}] "
                                    f"{fp.name} — {res['reason'][:60]}")
                        else:
                            self.sig_log.emit(
                                f"{icon} [{global_idx+1}/{total}] {fp.name}\n"
                                f"   └─ {res['reason']}")

                        self.sig_progress.emit(global_idx + 1, total, res)
                        global_idx += 1

                        if global_idx % GC_EVERY_N == 0:
                            gc.collect()
                    if self._cancelled:
                        break
            else:
                for fi, fp in enumerate(group.files):
                    if self._cancelled:
                        self.sig_log.emit("🛑 Đã huỷ!"); break
                    self._check_pause()
                    if self._cancelled:
                        break

                    cpu, ram, speed = throttle.tick()
                    self.sig_sysload.emit(cpu, ram, speed)
                    self.sig_file_start.emit(global_idx, fp.name)

                    res = self._cropper.process(fp)
                    cnt[res["status"]] = cnt.get(res["status"], 0) + 1

                    icon = dict(success="✅", skipped="⏭️",
                                rejected="📦", error="❌").get(
                        res["status"], "❓")

                    if total > 1000:
                        if global_idx % 50 == 0 or res["status"] != "success":
                            self.sig_log.emit(
                                f"{icon} [{global_idx+1:,}/{total:,}] "
                                f"{fp.name} — {res['reason'][:60]}")
                    else:
                        self.sig_log.emit(
                            f"{icon} [{global_idx+1}/{total}] {fp.name}\n"
                            f"   └─ {res['reason']}")

                    self.sig_progress.emit(global_idx + 1, total, res)
                    global_idx += 1

                    if global_idx % GC_EVERY_N == 0:
                        gc.collect()

        elapsed = time.time() - t0
        processed = sum(cnt.values())
        self.sig_log.emit(
            f"\n{'═'*54}\n🏁 HOÀN TẤT — {elapsed:.1f}s "
            f"(~{elapsed/max(processed,1):.2f}s/ảnh)\n"
            f"  ✅ Thành công: {cnt['success']:,}  "
            f"⏭️ Bỏ qua: {cnt['skipped']:,}\n"
            f"  📦 Loại bỏ: {cnt['rejected']:,}   "
            f"❌ Lỗi: {cnt['error']:,}\n"
            f"  📊 Tổng: {processed:,}/{total:,} │ "
            f"{n_groups} thư mục\n"
            f"  ⚡ Adaptive: sleep cuối = "
            f"{throttle.current_sleep*1000:.0f}ms\n"
            f"{'═'*54}")

        self._cropper.release(); self._cropper = None; gc.collect()
        self.sig_finished.emit([cnt])


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 9 — WIDGETS                                        ║
# ╚══════════════════════════════════════════════════════════════╝

class SliderRow(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, label, lo, hi, default, step=1, suffix="",
                 decimals=0, tip="", lw=125, parent=None):
        super().__init__(parent)
        self._m = 10 ** decimals; self._s = suffix; self._d = decimals
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(4)
        lbl = QLabel(label); lbl.setFixedWidth(lw)
        if tip:
            lbl.setToolTip(tip)
        lay.addWidget(lbl)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(lo * self._m))
        self.slider.setMaximum(int(hi * self._m))
        self.slider.setValue(int(default * self._m))
        self.slider.setSingleStep(int(step * self._m))
        lay.addWidget(self.slider, 1)
        self.vlbl = QLabel(); self.vlbl.setFixedWidth(46)
        self.vlbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.vlbl.setStyleSheet(
            f"color:{C['acc']};font-weight:600;font-size:11px;")
        lay.addWidget(self.vlbl)
        self._upd(self.slider.value())
        self.slider.valueChanged.connect(self._upd)

    def _upd(self, raw):
        v = raw / self._m
        self.vlbl.setText(
            f"{int(v)}{self._s}" if self._d == 0
            else f"{v:.{self._d}f}{self._s}")
        self.valueChanged.emit(v)

    def value(self):
        return self.slider.value() / self._m

    def setValue(self, v):
        self.slider.setValue(int(v * self._m))


class SpinRow(QWidget):
    def __init__(self, label, lo, hi, default, suffix="", tip="",
                 lw=125, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(4)
        lbl = QLabel(label); lbl.setFixedWidth(lw)
        if tip:
            lbl.setToolTip(tip)
        lay.addWidget(lbl)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi); self.spin.setValue(default)
        if suffix:
            self.spin.setSuffix(f" {suffix}")
        lay.addWidget(self.spin, 1)

    def value(self):
        return self.spin.value()

    def setValue(self, v):
        self.spin.setValue(v)


class TextRow(QWidget):
    def __init__(self, label, default="", lw=125, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(4)
        l = QLabel(label); l.setFixedWidth(lw); lay.addWidget(l)
        self.le = QLineEdit(default); lay.addWidget(self.le, 1)

    def value(self):
        return self.le.text().strip()

    def setValue(self, v):
        self.le.setText(v)


class Sep(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background:{C['brd']};")


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 10 — DROP ZONE                                     ║
# ╚══════════════════════════════════════════════════════════════╝

class DropZone(QWidget):
    folder_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True); self.setFixedHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hov = False; self._path = ""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m, w, h = 4, self.width(), self.height()
        bg = QColor(C["bg_hov"] if self._hov else C["dz_bg"])
        pp = QPainterPath()
        pp.addRoundedRect(m, m, w - 2*m, h - 2*m, 10, 10)
        p.fillPath(pp, bg)
        pen = QPen(QColor(C["acc"]))
        pen.setWidth(3 if self._hov else 2)
        pen.setStyle(
            Qt.PenStyle.SolidLine if self._hov else Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(m, m, w - 2*m, h - 2*m, 10, 10)
        p.setPen(QColor(C["acc"] if self._hov else C["t2"]))
        p.setFont(QFont("Segoe UI Emoji", 22))
        p.drawText(0, 0, w, int(h * 0.58),
                   Qt.AlignmentFlag.AlignHCenter |
                   Qt.AlignmentFlag.AlignBottom, "📂")
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        if self._path:
            p.setPen(QColor(C["ok"]))
            txt = f"✔  {Path(self._path).name}"
        else:
            txt = "Kéo thư mục ảnh vào đây — hoặc nhấn để chọn"
        p.drawText(8, int(h * 0.55), w - 16, int(h * 0.4),
                   Qt.AlignmentFlag.AlignHCenter |
                   Qt.AlignmentFlag.AlignTop, txt)
        p.end()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if Path(u.toLocalFile()).is_dir():
                    e.acceptProposedAction()
                    self._hov = True; self.update(); return
        e.ignore()

    def dragLeaveEvent(self, _):
        self._hov = False; self.update()

    def dropEvent(self, e):
        self._hov = False
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).is_dir():
                self._path = p
                self.folder_dropped.emit(p)
                self.update(); return
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            d = QFileDialog.getExistingDirectory(
                self, "Chọn thư mục chứa ảnh")
            if d:
                self._path = d
                self.folder_dropped.emit(d); self.update()

    def reset(self):
        self._path = ""; self.update()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 11 — THUMBNAIL GRID                                ║
# ╚══════════════════════════════════════════════════════════════╝

class ThumbCard(QFrame):
    _ST = {
        "success": ("✅", C["ok"]),
        "skipped": ("⏭️", C["skip"]),
        "rejected": ("📦", C["warn"]),
        "error": ("❌", C["err"]),
        "processing": ("⏳", C["acc"]),
        "waiting": ("", C["t_off"]),
    }

    def __init__(self, name=""):
        super().__init__()
        self.setFixedSize(THUMB_PX + 14, THUMB_PX + 44)
        self._sb(C["brd"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 2); lay.setSpacing(1)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label = QLabel()
        self.img_label.setFixedSize(THUMB_PX, THUMB_PX)
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet(
            f"background:{C['bg_in']};border-radius:5px;")
        lay.addWidget(self.img_label, 0, Qt.AlignmentFlag.AlignCenter)
        n = name if len(name) <= 18 else name[:8] + "…" + name[-7:]
        self.name_label = QLabel(n)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setMaximumWidth(THUMB_PX)
        self.name_label.setStyleSheet(f"color:{C['t2']};font-size:9px;")
        lay.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignCenter)

    def _sb(self, col):
        self.setStyleSheet(
            f"ThumbCard{{background:{C['th_bg']};"
            f"border:2px solid {col};border-radius:8px;}}")

    def set_px_path(self, path):
        px = QPixmap(str(path))
        if not px.isNull():
            self.img_label.setPixmap(px.scaled(
                THUMB_PX - 4, THUMB_PX - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def set_pixmap(self, px):
        if not px.isNull():
            self.img_label.setPixmap(px)

    def set_px_numpy(self, arr):
        if arr is None or arr.size == 0:
            return
        h, w = arr.shape[:2]
        if arr.ndim == 3:
            ch = arr.shape[2]
            fmt = (QImage.Format.Format_RGB888 if ch == 3
                   else QImage.Format.Format_RGBA8888)
            bpl = w * ch
        else:
            fmt = QImage.Format.Format_Grayscale8; bpl = w
        qimg = QImage(arr.data, w, h, bpl, fmt)
        px = QPixmap.fromImage(qimg)
        if not px.isNull():
            self.img_label.setPixmap(px.scaled(
                THUMB_PX - 4, THUMB_PX - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def set_status(self, status, detail=""):
        txt, col = self._ST.get(status, ("?", C["t2"]))
        self.status_label.setText(detail[:24] if detail else txt)
        self.status_label.setStyleSheet(
            f"color:{col};font-size:9px;font-weight:600;")
        bm = dict(success=C["ok"], error=C["err"], skipped=C["skip"],
                  rejected=C["warn"], processing=C["acc"])
        self._sb(bm.get(status, C["brd"]))


class ThumbGrid(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(4)
        self.setWidget(self._container)
        self._cards: list[ThumbCard] = []
        self._cols = 4; self._total = 0; self._is_large = False
        self.loader = None
        self._header = QLabel("")
        self._header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header.setStyleSheet(
            f"color:{C['acc']};font-size:11px;font-weight:600;"
            f"padding:4px;background:{C['bg_in']};"
            f"border:1px solid {C['brd']};border-radius:6px;")
        self._header.setVisible(False)

    def _ro(self):
        return 1 if self._header.isVisible() else 0

    def clear(self):
        if self.loader:
            self.loader.requestInterruption()
            self.loader.wait()
            self.loader = None
        self._grid.removeWidget(self._header)
        self._header.setVisible(False)
        self._header.setParent(None)
        for c in self._cards:
            self._grid.removeWidget(c); c.deleteLater()
        self._cards.clear()
        self._total = 0; self._is_large = False
        self._grid.addWidget(self._header, 0, 0, 1, 20)

    def populate(self, files, total: int | None = None):
        self.clear()
        self._total = total if total is not None else len(files)
        self._is_large = self._total > MAX_GRID_CARDS
        self._calc()
        if self._is_large:
            self._header.setVisible(True)
            self._header.setText(
                f"📊 {self._total:,} ảnh — "
                f"hiển thị {MAX_GRID_CARDS} gần nhất")
        else:
            self._header.setVisible(False)
            for i, f in enumerate(files):
                c = ThumbCard(f.name)
                self._grid.addWidget(
                    c, i // self._cols, i % self._cols,
                    Qt.AlignmentFlag.AlignTop)
                self._cards.append(c)
            self.loader = ThumbnailLoader(files)
            self.loader.loaded.connect(self._on_thumb_loaded)
            self.loader.start()

    def _on_thumb_loaded(self, index, data):
        if 0 <= index < len(self._cards):
            if isinstance(data, np.ndarray):
                self._cards[index].set_px_numpy(data)
            elif isinstance(data, QPixmap):
                self._cards[index].set_pixmap(data)

    def update_card(self, gi, result):
        if self._is_large:
            inp = result.get("input_path")
            name = inp.name if isinstance(inp, Path) else f"#{gi+1}"
            c = ThumbCard(name)
            c.set_status(result["status"], result.get("reason", ""))
            thumb = result.get("thumbnail")
            if (result["status"] == "success"
                    and isinstance(thumb, np.ndarray)):
                c.set_px_numpy(thumb)
            idx = len(self._cards); ro = self._ro()
            self._grid.addWidget(
                c, idx // self._cols + ro, idx % self._cols,
                Qt.AlignmentFlag.AlignTop)
            self._cards.append(c)
            if len(self._cards) > MAX_GRID_CARDS:
                excess = len(self._cards) - MAX_GRID_CARDS
                for _ in range(excess):
                    old = self._cards.pop(0)
                    self._grid.removeWidget(old)
                    old.deleteLater()
                self._relayout()
            self._header.setText(
                f"📊 {gi+1:,}/{self._total:,} — "
                f"{len(self._cards)} hiển thị")
        else:
            if 0 <= gi < len(self._cards):
                c = self._cards[gi]
                c.set_status(result["status"],
                             result.get("reason", ""))
                thumb = result.get("thumbnail")
                if (result["status"] == "success"
                        and isinstance(thumb, np.ndarray)):
                    c.set_px_numpy(thumb)
        if self._cards:
            self.ensureWidgetVisible(self._cards[-1], 50, 50)

    def mark_processing(self, gi):
        if not self._is_large and 0 <= gi < len(self._cards):
            self._cards[gi].set_status("processing")

    def _relayout(self):
        ro = self._ro()
        for i, c in enumerate(self._cards):
            self._grid.removeWidget(c)
            self._grid.addWidget(
                c, i // self._cols + ro, i % self._cols,
                Qt.AlignmentFlag.AlignTop)

    def _calc(self):
        w = self.viewport().width() - 8
        cw = THUMB_PX + 20
        self._cols = max(2, min(w // cw, 12))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        old = self._cols; self._calc()
        if old != self._cols and self._cards:
            self._relayout()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 12 — DASHBOARD                                     ║
# ╚══════════════════════════════════════════════════════════════╝

class Dashboard(QWidget):
    def __init__(self, sys_info: SysInfo):
        super().__init__()
        self.sys = sys_info
        self.setMinimumWidth(335); self.setMaximumWidth(390)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(4)
        ttl = QLabel("⚙️ Bảng điều khiển")
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ttl.setStyleSheet(
            f"font-size:15px;font-weight:700;"
            f"color:{C['acc']};padding:2px 0;")
        root.addWidget(ttl)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_tab_crop()
        self._build_tab_output()
        # Thêm nút Reset mặc định
        btn_reset_default = QPushButton("🔁 Reset mặc định")
        btn_reset_default.setProperty("class", "warn")
        btn_reset_default.setMinimumHeight(32)
        btn_reset_default.clicked.connect(self.reset_defaults)
        root.addWidget(btn_reset_default)
        self._apply_settings(CropSettings.load())

    # ── TAB 1: Crop ──────────────────────────────────────────
    def _build_tab_crop(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(6)

        # ── AI Model ──
        g1 = QGroupBox("🤖 Mô hình AI")
        g1l = QVBoxLayout(g1); g1l.setSpacing(4)
        mrow = QWidget()
        mr = QHBoxLayout(mrow)
        mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(4)
        mr.addWidget(self._lbl("Mô hình:"))
        self.cb_model = QComboBox()
        self.cb_model.addItems(
            ["u2net", "u2net_human_seg", "isnet-general-use"])
        mr.addWidget(self.cb_model, 1)
        g1l.addWidget(mrow)
        self.sp_mask = SpinRow(
            "Ngưỡng mask:", 25, 250, 120,
            tip="Thấp=nhiều chi tiết, Cao=ít chi tiết")
        g1l.addWidget(self.sp_mask)
        lay.addWidget(g1)

        # ── Padding ──
        g2 = QGroupBox("📐 Khoảng đệm (px)")
        g2l = QVBoxLayout(g2); g2l.setSpacing(4)
        note = QLabel(
            "💡 Cạnh sát biên tự bỏ padding → giữ bố cục gốc.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['t2']};font-size:10px;")
        g2l.addWidget(note); g2l.addWidget(Sep())
        self.chk_uniform = QCheckBox("  Đệm đều 4 cạnh")
        self.chk_uniform.setChecked(True)
        self.chk_uniform.toggled.connect(self._toggle_pad)
        g2l.addWidget(self.chk_uniform)
        self.sp_pad_all = SpinRow("Tất cả:", 0, 200, 10, suffix="px")
        g2l.addWidget(self.sp_pad_all)
        self.sp_pad_t = SpinRow("Trên:", 0, 200, 10, suffix="px")
        self.sp_pad_b = SpinRow("Dưới:", 0, 200, 10, suffix="px")
        self.sp_pad_l = SpinRow("Trái:", 0, 200, 10, suffix="px")
        self.sp_pad_r = SpinRow("Phải:", 0, 200, 10, suffix="px")
        for s in [self.sp_pad_t, self.sp_pad_b,
                  self.sp_pad_l, self.sp_pad_r]:
            g2l.addWidget(s); s.setVisible(False)
        g2l.addWidget(Sep())
        self.sl_edge = SliderRow(
            "Vùng biên:", 0, 10, 2.5,
            step=0.5, suffix="%", decimals=1)
        g2l.addWidget(self.sl_edge)
        self.sp_edge_gap = SpinRow(
            "Dung sai biên:", 0, 30, 5,
            suffix="px", tip="Bbox cách biên ≤ Npx → sát")
        g2l.addWidget(self.sp_edge_gap)
        lay.addWidget(g2)

        # ── Chủ thể + Auto-Frame ──
        g3 = QGroupBox("🎯 Crop & Frame")
        g3l = QVBoxLayout(g3); g3l.setSpacing(4)
        self.sl_fill = SliderRow(
            "Subject chiếm:", 50, 100, 92, suffix="%")
        self.sl_fill.setToolTip(
            "Subject chiếm bao nhiêu % vùng crop.\n"
            "Thấp hơn = crop rộng hơn.\n"
            "100% = crop sát nhất.")
        g3l.addWidget(self.sl_fill)
        g3l.addWidget(Sep())
        auto_frame_note = QLabel(
            "🖼️ Frame: TỰ ĐỘNG theo tỷ lệ ảnh gốc\n\n"
            "VD: Ảnh gốc 1200×800 (3:2)\n"
            "  → Crop cũng giữ tỷ lệ 3:2\n"
            "  → Mở rộng bằng pixel gốc\n"
            "  → Không trim, không tạo nền giả")
        auto_frame_note.setWordWrap(True)
        auto_frame_note.setStyleSheet(
            f"color:{C['t2']};font-size:10px;"
            f"padding:6px;background:{C['bg_in']};"
            f"border:1px solid {C['brd']};border-radius:5px;")
        g3l.addWidget(auto_frame_note)
        lay.addWidget(g3)

        # ── Hiệu năng ──
        g4 = QGroupBox("⚡ Hiệu năng")
        g4l = QVBoxLayout(g4); g4l.setSpacing(4)
        self.sl_cpu = SliderRow(
            "Giới hạn CPU:", 5, 80, 20, step=5, suffix="%")
        g4l.addWidget(self.sl_cpu)
        self.chk_adaptive = QCheckBox(
            "  🧠 Adaptive Speed (tự điều chỉnh)")
        self.chk_adaptive.setChecked(True)
        self.chk_adaptive.setToolTip(
            "BẬT: Tự tăng tốc khi rảnh, giảm khi nặng\n"
            "TẮT: Sleep cố định")
        g4l.addWidget(self.chk_adaptive)

        self.cb_parallel = QComboBox()
        self.cb_parallel.addItems([
            "Auto (tự phân phối)",
            "Bật (cố định số luồng)",
            "Tắt (1 luồng)"
        ])
        self.cb_parallel.setToolTip(
            "Auto: chọn luồng theo cấu hình máy và CPU limit.\n"
            "Bật: dùng số luồng cố định.\n"
            "Tắt: xử lý tuần tự.")
        g4l.addWidget(self.cb_parallel)

        self.sp_workers = SpinRow(
            "Số luồng tối đa:", 1, 8, 1)
        self.sp_workers.setVisible(False)
        g4l.addWidget(self.sp_workers)

        self.lbl_parallel = QLabel(
            f"Máy: {self.sys.cores_p}C / {self.sys.cores_l}T")
        self.lbl_parallel.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self.lbl_parallel.setStyleSheet(
            f"color:{C['acc']};font-size:11px;font-weight:600;"
            f"padding:4px;background:{C['bg_in']};"
            f"border:1px solid {C['brd']};border-radius:5px;")
        g4l.addWidget(self.lbl_parallel)

        self.cb_parallel.currentIndexChanged.connect(
            self._update_parallel_ui)
        self.cb_parallel.currentIndexChanged.connect(
            self._update_worker_label)
        self.sp_workers.spin.valueChanged.connect(
            self._update_worker_label)
        self.sl_cpu.valueChanged.connect(self._update_worker_label)

        self.lbl_speed = QLabel("⚡ Chờ bắt đầu...")
        self.lbl_speed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_speed.setStyleSheet(
            f"color:{C['acc']};font-size:11px;font-weight:600;"
            f"padding:4px;background:{C['bg_in']};"
            f"border:1px solid {C['brd']};border-radius:5px;")
        g4l.addWidget(self.lbl_speed)
        lay.addWidget(g4)

        lay.addStretch(1)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "🖼️ Crop")

    # ── TAB 2: Đầu ra ───────────────────────────────────────
    def _build_tab_output(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(6)

        # ── Subfolder ──
        g0 = QGroupBox("📁 Quét thư mục")
        g0l = QVBoxLayout(g0); g0l.setSpacing(4)
        self.chk_subfolder = QCheckBox(
            "  Quét cả thư mục con (subfolder)")
        self.chk_subfolder.setChecked(False)
        self.chk_subfolder.setToolTip(
            "BẬT: Quét đệ quy tất cả subfolder\n"
            "Mỗi subfolder có Done/ và Loại bỏ/ riêng")
        g0l.addWidget(self.chk_subfolder)
        sf_note = QLabel(
            "💡 Mỗi thư mục con có kết quả riêng.\n"
            "VD: category_A/Done/, category_B/Done/...")
        sf_note.setWordWrap(True)
        sf_note.setStyleSheet(f"color:{C['t2']};font-size:10px;")
        g0l.addWidget(sf_note)
        lay.addWidget(g0)

        # ── Chất lượng ──
        g2 = QGroupBox("📦 Chất lượng")
        g2l = QVBoxLayout(g2); g2l.setSpacing(4)
        self.sp_png = SpinRow("Nén PNG:", 0, 9, 9)
        g2l.addWidget(self.sp_png)
        lay.addWidget(g2)

        # ── Lọc & Thư mục ──
        g3 = QGroupBox("🗑️ Lọc & Thư mục")
        g3l = QVBoxLayout(g3); g3l.setSpacing(4)
        self.sp_min = SpinRow(
            "Loại nếu subject<", 0, 8000, 700, suffix="px")
        g3l.addWidget(self.sp_min)
        min_note = QLabel(
            "💡 Subject có cạnh lớn nhất < ngưỡng\n"
            "→ di chuyển vào thư mục loại bỏ.\n"
            "Check cả: ảnh gốc, subject, crop cuối.")
        min_note.setWordWrap(True)
        min_note.setStyleSheet(f"color:{C['t2']};font-size:10px;")
        g3l.addWidget(min_note)
        g3l.addWidget(Sep())
        self.txt_out = TextRow("TM kết quả:", "Done")
        g3l.addWidget(self.txt_out)
        self.txt_rej = TextRow("TM loại bỏ:", "Loại bỏ")
        g3l.addWidget(self.txt_rej)
        lay.addWidget(g3)

        lay.addStretch(1)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "📤 Đầu ra")

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _lbl(t, w=125):
        l = QLabel(t); l.setFixedWidth(w); return l

    def _toggle_pad(self, u):
        self.sp_pad_all.setVisible(u)
        for s in [self.sp_pad_t, self.sp_pad_b,
                  self.sp_pad_l, self.sp_pad_r]:
            s.setVisible(not u)

    def _update_parallel_ui(self, idx: int):
        mode = ["auto", "on", "off"][idx]
        self.sp_workers.setVisible(mode == "on")
        self._update_worker_label()

    def _update_worker_label(self):
        if not hasattr(self, "lbl_workers"):
            return

        settings = self.get_settings()
        logical = psutil.cpu_count(logical=True) or 1
        physical = psutil.cpu_count(logical=False) or logical
        if settings.parallel_mode == "off":
            workers = 1
        elif settings.parallel_mode == "on":
            workers = min(max(1, settings.max_workers), logical, physical)
        else:
            if settings.cpu_limit < 35:
                workers = 1
            else:
                workers = min(4, logical, physical,
                              max(1, int(settings.cpu_limit // 25)))

        if settings.parallel_mode == "off":
            text = "1 luồng (tuần tự)"
        elif settings.parallel_mode == "on":
            text = f"Cố định {workers} luồng"
        else:
            text = f"Tự động {workers} luồng"
        self.lbl_workers.setText(f"Workers: {text}")

    def get_settings(self) -> CropSettings:
        s = CropSettings(
            model_name=self.cb_model.currentText(),
            padding_px=self.sp_pad_all.value(),
            padding_top_px=self.sp_pad_t.value(),
            padding_bottom_px=self.sp_pad_b.value(),
            padding_left_px=self.sp_pad_l.value(),
            padding_right_px=self.sp_pad_r.value(),
            use_uniform_padding=self.chk_uniform.isChecked(),
            edge_threshold_pct=self.sl_edge.value(),
            edge_gap_px=self.sp_edge_gap.value(),
            png_compress=self.sp_png.value(),
            min_size_px=self.sp_min.value(),
            subject_fill=self.sl_fill.value(),
            mask_threshold=self.sp_mask.value(),
            output_folder=self.txt_out.value() or "Done",
            rejected_folder=self.txt_rej.value() or "Loại bỏ",
            cpu_limit=self.sl_cpu.value(),
            scan_subfolders=self.chk_subfolder.isChecked(),
            adaptive_speed=self.chk_adaptive.isChecked(),
            parallel_mode=["auto", "on", "off"][self.cb_parallel.currentIndex()],
            max_workers=self.sp_workers.value())
        s.save()
        return s

    def _apply_settings(self, s: CropSettings):
        models = ["u2net", "u2net_human_seg", "isnet-general-use"]
        self.cb_model.setCurrentIndex(
            models.index(s.model_name) if s.model_name in models else 0)
        self.sp_mask.setValue(s.mask_threshold)
        self.chk_uniform.setChecked(s.use_uniform_padding)
        self.sp_pad_all.setValue(s.padding_px)
        self.sp_pad_t.setValue(s.padding_top_px)
        self.sp_pad_b.setValue(s.padding_bottom_px)
        self.sp_pad_l.setValue(s.padding_left_px)
        self.sp_pad_r.setValue(s.padding_right_px)
        self.sl_edge.setValue(s.edge_threshold_pct)
        self.sp_edge_gap.setValue(s.edge_gap_px)
        self.sl_fill.setValue(s.subject_fill)
        self.sl_cpu.setValue(s.cpu_limit)
        self.chk_adaptive.setChecked(s.adaptive_speed)
        self.cb_parallel.setCurrentIndex(
            {"auto": 0, "on": 1, "off": 2}.get(s.parallel_mode, 0))
        self.sp_workers.setValue(max(1, s.max_workers))
        self._update_parallel_ui(self.cb_parallel.currentIndex())
        self.chk_subfolder.setChecked(s.scan_subfolders)
        self._update_worker_label()
        self.sp_png.setValue(s.png_compress)
        self.sp_min.setValue(s.min_size_px)
        self.txt_out.setValue(s.output_folder)
        self.txt_rej.setValue(s.rejected_folder)

    def reset_defaults(self):
        d = CropSettings.defaults()
        self._apply_settings(d); d.save()

    def update_speed(self, label: str):
        self.lbl_speed.setText(f"⚡ {label}")


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 13 — MAIN WINDOW                                   ║
# ╚══════════════════════════════════════════════════════════════╝

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"🔲 {APP_TITLE}")
        self.setMinimumSize(1060, 640)
        self.resize(1320, 760)
        self.sys = detect_system()
        self.worker = BatchWorker()
        self.worker.sig_progress.connect(self._on_progress)
        self.worker.sig_file_start.connect(self._on_file_start)
        self.worker.sig_finished.connect(self._on_finished)
        self.worker.sig_log.connect(self._on_log)
        self.worker.sig_sysload.connect(self._on_sysload)
        self.worker.sig_folder_start.connect(self._on_folder_start)
        self.scanner: FolderScanner | None = None
        self._busy = False
        self.setStyleSheet(build_qss())
        self._build(); self._setup_sb(); self._start_mon()

    def _build(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(8, 8, 8, 4); main.setSpacing(8)
        self.dash = Dashboard(self.sys)
        main.addWidget(self.dash)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(5)

        self.dz = DropZone()
        self.dz.folder_dropped.connect(self._on_folder)
        rl.addWidget(self.dz)

        ab = QWidget()
        al = QHBoxLayout(ab)
        al.setContentsMargins(0, 0, 0, 0); al.setSpacing(5)
        self.btn_start = QPushButton("▶  Bắt đầu")
        self.btn_start.setProperty("class", "primary")
        self.btn_start.setMinimumHeight(32)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_start.setEnabled(False)
        self.btn_pause = QPushButton("⏸  Dừng")
        self.btn_pause.setMinimumHeight(32)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_pause.setEnabled(False)
        self.btn_cancel = QPushButton("🛑  Huỷ")
        self.btn_cancel.setProperty("class", "danger")
        self.btn_cancel.setMinimumHeight(32)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)
        self.btn_reset = QPushButton("🔄  Làm mới")
        self.btn_reset.setProperty("class", "warn")
        self.btn_reset.setMinimumHeight(32)
        self.btn_reset.clicked.connect(self._on_reset)
        al.addWidget(self.btn_start)
        al.addWidget(self.btn_pause)
        al.addWidget(self.btn_cancel)
        al.addWidget(self.btn_reset)
        al.addStretch(1)
        self.lbl_count = QLabel("📁 Chưa chọn thư mục")
        self.lbl_count.setStyleSheet(
            f"color:{C['t2']};font-size:12px;")
        al.addWidget(self.lbl_count)
        rl.addWidget(ab)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m ảnh — %p%")
        rl.addWidget(self.progress)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setHandleWidth(4)
        self.thumbs = ThumbGrid()
        split.addWidget(self.thumbs)
        log_w = QWidget()
        ll = QVBoxLayout(log_w)
        ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(2)
        lh = QLabel("📋 Nhật ký")
        lh.setStyleSheet(
            f"color:{C['acc']};font-weight:700;font-size:11px;")
        ll.addWidget(lh)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Nhật ký...")
        self.log.document().setMaximumBlockCount(5000)
        ll.addWidget(self.log)
        split.addWidget(log_w)
        split.setStretchFactor(0, 6)
        split.setStretchFactor(1, 1)
        split.setSizes([550, 80])
        rl.addWidget(split, 1)
        main.addWidget(right, 1)

    def _setup_sb(self):
        sb = QStatusBar(); self.setStatusBar(sb)
        s = self.sys
        hw = [f"⚙ {s.cpu_name[:35]}",
              f"🧵 {s.cores_p}C/{s.cores_l}T",
              f"🧠 {s.ram_gb:.0f}GB"]
        if s.has_cuda:
            hw.append(f"🎮 {s.gpu[:25]}")
        self.lbl_hw = QLabel("  │  ".join(hw))
        self.lbl_hw.setStyleSheet(
            f"color:{C['t2']};font-size:10.5px;"
            f"font-family:'Cascadia Code','Consolas',monospace;")
        sb.addWidget(self.lbl_hw, 1)
        self.lbl_cpu = QLabel("CPU: --%")
        self.lbl_ram = QLabel("RAM: --%")
        for l in [self.lbl_cpu, self.lbl_ram]:
            l.setStyleSheet(
                f"color:{C['t2']};font-size:11px;font-weight:600;"
                f"font-family:'Cascadia Code',monospace;padding:0 4px;")
        sb.addPermanentWidget(self.lbl_cpu)
        sb.addPermanentWidget(self.lbl_ram)
        self.lbl_workers = QLabel("Workers: --")
        self.lbl_workers.setStyleSheet(
            f"color:{C['t2']};font-size:11px;font-weight:600;"
            f"font-family:'Cascadia Code',monospace;padding:0 4px;")
        sb.addPermanentWidget(self.lbl_workers)
        if hasattr(self, 'dash'):
            self.dash.lbl_workers = self.lbl_workers
            self.dash._update_worker_label()

    def _start_mon(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(2000); self._tick()

    def _tick(self):
        self._show_load(
            psutil.cpu_percent(interval=0),
            psutil.virtual_memory().percent)

    def _show_load(self, cpu, ram):
        cc = (C["ok"] if cpu <= 40
              else (C["warn"] if cpu <= 70 else C["err"]))
        rc = (C["ok"] if ram <= 60
              else (C["warn"] if ram <= 80 else C["err"]))
        self.lbl_cpu.setText(f"CPU: {cpu:.0f}%")
        self.lbl_cpu.setStyleSheet(
            f"color:{cc};font-size:11px;font-weight:600;"
            f"font-family:'Cascadia Code',monospace;padding:0 4px;")
        self.lbl_ram.setText(f"RAM: {ram:.0f}%")
        self.lbl_ram.setStyleSheet(
            f"color:{rc};font-size:11px;font-weight:600;"
            f"font-family:'Cascadia Code',monospace;padding:0 4px;")

    def _on_folder(self, path):
        settings = self.dash.get_settings()
        if self.scanner and self.scanner.isRunning():
            self.scanner.requestInterruption()
            self.scanner.wait()
            self.scanner = None

        self.lbl_count.setText("⏳ Đang quét thư mục...")
        self.btn_start.setEnabled(False)
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        self.thumbs.clear()

        self.scanner = FolderScanner(path, settings.scan_subfolders)
        self.scanner.scanned.connect(self._on_folder_scanned)
        self.scanner.error.connect(self._on_folder_scan_error)
        self.scanner.start()

    def _on_folder_scanned(self, groups, path):
        self.worker.groups = groups
        n = self.worker.total_files
        ng = len(groups)
        folder_info = (f"📁 {n:,} ảnh" +
                       (f" ({ng} thư mục)" if ng > 1 else ""))
        self.lbl_count.setText(
            folder_info if n else "⚠️ Không có ảnh")
        self.btn_start.setEnabled(n > 0)
        self.progress.setMaximum(max(n, 1))
        self.progress.setValue(0)
        if n:
            if n > MAX_GRID_CARDS:
                limited_files = []
                for g in groups:
                    for f in g.files:
                        limited_files.append(f)
                        if len(limited_files) >= MAX_GRID_CARDS:
                            break
                    if len(limited_files) >= MAX_GRID_CARDS:
                        break
                self.thumbs.populate(limited_files, total=n)
            else:
                all_files = [f for g in groups for f in g.files]
                self.thumbs.populate(all_files)
            log_msg = f"📂 {path}\n📁 {n:,} ảnh"
            if ng > 1:
                log_msg += f" trong {ng} thư mục:\n"
                for g in groups:
                    log_msg += (f"   📁 {g.label or '(gốc)'}: "
                                f"{g.count} ảnh\n")
            self._on_log(log_msg)
        else:
            self.thumbs.clear()
        self.scanner = None

    def _on_folder_scan_error(self, message):
        self._on_log(f"⚠️ Lỗi quét thư mục: {message}")
        self.lbl_count.setText("⚠️ Lỗi khi quét thư mục")
        self.scanner = None

    def _on_start(self):
        if self._busy:
            return
        self.worker.settings = self.dash.get_settings()
        self.progress.setValue(0); self.log.clear()
        self._set_busy(True); self.worker.start()

    def _on_pause(self):
        if not self._busy:
            return
        if "Dừng" in self.btn_pause.text():
            self.worker.pause()
            self.btn_pause.setText("▶  Tiếp tục")
            self.btn_pause.setProperty("class", "primary")
            self._on_log("⏸️ Tạm dừng")
        else:
            self.worker.resume()
            self.btn_pause.setText("⏸  Dừng")
            self.btn_pause.setProperty("class", "")
            self._on_log("▶️ Tiếp tục")
        self.btn_pause.style().unpolish(self.btn_pause)
        self.btn_pause.style().polish(self.btn_pause)

    def _on_cancel(self):
        if not self._busy:
            return
        if QMessageBox.question(
                self, "Xác nhận", "Huỷ bỏ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.worker.cancel()

    def _on_reset(self):
        if self._busy:
            if QMessageBox.question(
                    self, "Đang xử lý", "Huỷ và làm mới?",
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return
            self.worker.cancel()
            self.worker.wait(3000)
        self.worker.release()
        self.thumbs.clear(); self.log.clear()
        self.progress.setValue(0); self.progress.setMaximum(1)
        self.dz.reset()
        self.lbl_count.setText("📁 Chưa chọn thư mục")
        self.btn_start.setEnabled(False)
        # self.dash.reset_defaults()  # Đã bỏ, chỉ clear dữ liệu tạm thời
        self._set_busy(False); gc.collect()
        self._on_log("🔄 Làm mới — Bộ nhớ giải phóng")

    def _on_progress(self, cur, total, result):
        self.progress.setValue(cur)
        self.thumbs.update_card(cur - 1, result)

    def _on_file_start(self, idx, name):
        self.thumbs.mark_processing(idx)

    def _on_folder_start(self, label, count):
        self._on_log(
            f"\n📂 Đang xử lý: {label or '(gốc)'} — {count} ảnh")

    def _on_finished(self, summary):
        self._set_busy(False)
        self.dash.update_speed("Hoàn tất ✔")
        if summary:
            cnt = summary[0]
            s = self.dash.get_settings()
            QMessageBox.information(
                self, "Hoàn tất",
                f"✅ Xong!\n\n"
                f"Thành công: {cnt.get('success', 0):,} "
                f"→ '{s.output_folder}'\n"
                f"Loại bỏ: {cnt.get('rejected', 0):,} "
                f"→ '{s.rejected_folder}'\n"
                f"Bỏ qua: {cnt.get('skipped', 0):,}  "
                f"Lỗi: {cnt.get('error', 0):,}\n\n"
                f"Tổng: {sum(cnt.values()):,}")

    def _on_log(self, msg):
        self.log.append(msg)
        c = self.log.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(c)

    def _on_sysload(self, cpu, ram, speed):
        self._show_load(cpu, ram)
        self.dash.update_speed(speed)

    def _set_busy(self, busy):
        self._busy = busy
        self.btn_start.setEnabled(not busy)
        self.btn_pause.setEnabled(busy)
        self.btn_cancel.setEnabled(busy)
        self.dz.setEnabled(not busy)
        self.btn_reset.setEnabled(True)
        if not busy:
            self.btn_pause.setText("⏸  Dừng")

    def closeEvent(self, e):
        try:
            self.dash.get_settings()
        except Exception:
            pass
        if self._busy:
            self.worker.cancel()
            self.worker.wait(3000)
        self.worker.release(); gc.collect(); e.accept()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 14 — ENTRY                                         ║
# ╚══════════════════════════════════════════════════════════════╝

def main():
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    f = QFont("Segoe UI", 10)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(f)
    win = MainWindow(); win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
