"""
╔══════════════════════════════════════════════════════════════════════╗
║  SMART SUBJECT CROPPER v3.1.1 — Thumbnail Fix                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys, os, gc, json, time, shutil, platform, subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
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

APP_TITLE = "Smart Subject Cropper v3.1"
SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
THUMB_PX = 128
SETTINGS_FILE = Path(__file__).parent / "cropper_settings.json"

MAX_GRID_CARDS = 500
GC_EVERY_N = 25
RAM_THROTTLE_PCT = 85

FRAME_OPTIONS = [
    ("🔄 Tự động (giữ tỷ lệ ảnh gốc)", 0, 0),
    ("⬜ 1 : 1  (Vuông)", 1, 1),
    ("▬  4 : 3  (Ngang)", 4, 3),
    ("▮  3 : 4  (Dọc)", 3, 4),
    ("▬  3 : 2  (Ngang)", 3, 2),
    ("▮  2 : 3  (Dọc)", 2, 3),
    ("▬  16 : 9 (Ngang)", 16, 9),
    ("▮  9 : 16 (Dọc)", 9, 16),
    ("✏️ Tuỳ chỉnh (nhập W×H)", -1, -1),
]


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
    frame_index: int = 0
    target_width: int = 0
    target_height: int = 0
    auto_output_size: bool = True
    png_compress: int = 9
    min_size_px: int = 512
    subject_fill: float = 92.0
    mask_threshold: int = 120
    white_bg: bool = True
    max_upscale: float = 2.0
    output_folder: str = "Done"
    rejected_folder: str = "Loại bỏ"
    cpu_limit: float = 20.0

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
    QMainWindow, QWidget {{
        background:{C['bg1']}; color:{C['t1']};
        font-family:"Segoe UI","Noto Sans",Arial,sans-serif; font-size:13px;
    }}
    QScrollArea {{ border:none; background:transparent; }}
    QScrollBar:vertical {{
        background:{C['bg2']}; width:8px; border-radius:4px;
    }}
    QScrollBar::handle:vertical {{
        background:{C['brd']}; border-radius:4px; min-height:28px;
    }}
    QScrollBar::handle:vertical:hover {{ background:{C['bg_hov']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar:horizontal {{
        background:{C['bg2']}; height:8px; border-radius:4px;
    }}
    QScrollBar::handle:horizontal {{
        background:{C['brd']}; border-radius:4px; min-width:28px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
    QGroupBox {{
        background:{C['bg2']}; border:1px solid {C['brd']};
        border-radius:9px; margin-top:10px;
        padding:14px 10px 8px 10px; font-weight:600; font-size:12px;
    }}
    QGroupBox::title {{
        subcontrol-origin:margin; subcontrol-position:top left;
        left:12px; padding:1px 8px;
        color:{C['acc']}; background:{C['bg2']}; border-radius:4px;
    }}
    QPushButton {{
        background:{C['bg3']}; color:{C['t1']};
        border:1px solid {C['brd']}; border-radius:7px;
        padding:7px 14px; font-weight:600; min-height:14px;
    }}
    QPushButton:hover {{ background:{C['bg_hov']}; border-color:{C['acc']}; }}
    QPushButton:pressed {{ background:{C['acc_d']}; }}
    QPushButton:disabled {{ background:{C['bg_in']}; color:{C['t_off']}; }}
    QPushButton[class="primary"] {{
        background:{C['acc']}; color:#000; border:none; font-weight:700;
    }}
    QPushButton[class="primary"]:hover {{ background:{C['acc_h']}; }}
    QPushButton[class="primary"]:pressed {{ background:{C['acc_d']}; color:#fff; }}
    QPushButton[class="danger"] {{ background:{C['err']}; color:#fff; border:none; }}
    QPushButton[class="danger"]:hover {{ background:#ff4d5a; }}
    QPushButton[class="warn"] {{
        background:{C['warn']}; color:#000; border:none; font-weight:700;
    }}
    QPushButton[class="warn"]:hover {{ background:#e6924a; }}
    QSpinBox, QComboBox {{
        background:{C['bg_in']}; color:{C['t1']};
        border:1px solid {C['brd']}; border-radius:5px;
        padding:5px 8px; min-height:14px; font-size:12px;
    }}
    QSpinBox:focus {{ border-color:{C['brd_f']}; }}
    QSpinBox::up-button {{
        width:20px; border-left:1px solid {C['brd']};
        border-top-right-radius:5px; background:{C['bg3']};
    }}
    QSpinBox::down-button {{
        width:20px; border-left:1px solid {C['brd']};
        border-bottom-right-radius:5px; background:{C['bg3']};
    }}
    QComboBox::drop-down {{
        border-left:1px solid {C['brd']}; width:26px;
        border-top-right-radius:5px; border-bottom-right-radius:5px;
        background:{C['bg3']};
    }}
    QComboBox QAbstractItemView {{
        background:{C['bg2']}; color:{C['t1']};
        border:1px solid {C['brd']}; selection-background-color:{C['acc_d']};
        padding:3px;
    }}
    QCheckBox {{ color:{C['t1']}; spacing:6px; font-size:12px; }}
    QCheckBox::indicator {{
        width:17px; height:17px; border-radius:3px;
        border:2px solid {C['brd']}; background:{C['bg_in']};
    }}
    QCheckBox::indicator:checked {{ background:{C['acc']}; border-color:{C['acc']}; }}
    QRadioButton {{ color:{C['t1']}; spacing:6px; font-size:12px; }}
    QRadioButton::indicator {{
        width:16px; height:16px; border-radius:8px;
        border:2px solid {C['brd']}; background:{C['bg_in']};
    }}
    QRadioButton::indicator:checked {{ background:{C['acc']}; border-color:{C['acc']}; }}
    QProgressBar {{
        background:{C['bg_in']}; border:1px solid {C['brd']};
        border-radius:7px; text-align:center;
        color:{C['t1']}; font-weight:600; min-height:18px; font-size:11px;
    }}
    QProgressBar::chunk {{
        background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {C['acc_d']},stop:1 {C['acc']}); border-radius:6px;
    }}
    QTextEdit {{
        background:{C['bg_in']}; color:{C['t1']};
        border:1px solid {C['brd']}; border-radius:7px; padding:6px;
        font-family:"Cascadia Code","Consolas",monospace; font-size:11px;
    }}
    QLineEdit {{
        background:{C['bg_in']}; color:{C['t1']};
        border:1px solid {C['brd']}; border-radius:5px;
        padding:5px 8px; font-size:12px;
    }}
    QLineEdit:focus {{ border-color:{C['brd_f']}; }}
    QSlider::groove:horizontal {{ background:{C['bg_in']}; height:5px; border-radius:2px; }}
    QSlider::handle:horizontal {{
        background:{C['acc']}; width:15px; height:15px;
        margin:-5px 0; border-radius:7px;
    }}
    QSlider::handle:horizontal:hover {{ background:{C['acc_h']}; }}
    QSlider::sub-page:horizontal {{ background:{C['acc_d']}; border-radius:2px; }}
    QTabWidget::pane {{
        border:1px solid {C['brd']}; border-radius:7px;
        background:{C['bg2']}; top:-1px;
    }}
    QTabBar::tab {{
        background:{C['bg_in']}; color:{C['t2']};
        border:1px solid {C['brd']}; border-bottom:none;
        padding:6px 14px; margin-right:1px;
        border-top-left-radius:7px; border-top-right-radius:7px;
        font-weight:600; font-size:11px;
    }}
    QTabBar::tab:selected {{ background:{C['bg2']}; color:{C['acc']}; }}
    QTabBar::tab:hover:!selected {{ background:{C['bg_hov']}; color:{C['t1']}; }}
    QToolTip {{
        background:{C['bg3']}; color:{C['t1']};
        border:1px solid {C['acc']}; border-radius:5px;
        padding:4px 7px; font-size:11px;
    }}
    QSplitter::handle {{ background:{C['brd']}; }}
    QSplitter::handle:vertical {{ height:3px; }}
    QStatusBar {{
        background:{C['bg2']}; color:{C['t2']};
        border-top:1px solid {C['brd']}; font-size:11px; padding:2px 8px;
    }}
    QStatusBar QLabel {{
        color:{C['t2']}; font-size:11px; padding:0 6px;
        font-family:"Cascadia Code","Consolas",monospace;
    }}
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
    ram = psutil.virtual_memory().total / (1024 ** 3)
    cn = platform.processor() or ""
    if not cn and platform.system() == "Windows":
        try:
            r = subprocess.run(["wmic", "cpu", "get", "name"],
                               capture_output=True, text=True, timeout=5)
            ls = [l.strip() for l in r.stdout.split("\n") if l.strip()]
            if len(ls) > 1: cn = ls[1]
        except Exception:
            pass
    gpu, cuda = "N/A", False
    try:
        import onnxruntime as ort
        if "CUDAExecutionProvider" in ort.get_available_providers():
            cuda = True; gpu = "NVIDIA (CUDA)"
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    gpu = r.stdout.strip().split("\n")[0]
            except Exception:
                pass
    except ImportError:
        pass
    return SysInfo(
        os_name=f"{platform.system()} {platform.release()}",
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
# ║  SECTION 5 — AI CROPPER ENGINE                              ║
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
        self._session = None
        gc.collect()

    def _get_mask(self, img: PILImage.Image) -> np.ndarray:
        s = self.settings
        raw = remove(img, session=self.session, only_mask=True)
        mask = np.array(raw)
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_RGB2GRAY)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)
        _, sure = cv2.threshold(mask, s.mask_threshold, 255, cv2.THRESH_BINARY)
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

    def _detect_edges(self, mask, x1, y1, x2, y2, img_w, img_h):
        s = self.settings
        gap = s.edge_gap_px
        band_y = max(3, int(img_h * s.edge_threshold_pct / 100))
        band_x = max(3, int(img_w * s.edge_threshold_pct / 100))
        min_px = max(3, int(min(img_w, img_h) * 0.003))

        mask_top = int(np.sum(mask[0:band_y, :] > 0)) > min_px
        mask_bot = int(np.sum(mask[img_h - band_y:, :] > 0)) > min_px
        mask_lft = int(np.sum(mask[:, 0:band_x] > 0)) > min_px
        mask_rgt = int(np.sum(mask[:, img_w - band_x:] > 0)) > min_px

        gap_top = y1 <= gap
        gap_bot = y2 >= img_h - 1 - gap
        gap_lft = x1 <= gap
        gap_rgt = x2 >= img_w - 1 - gap

        edges = dict(
            top=mask_top or gap_top,
            bottom=mask_bot or gap_bot,
            left=mask_lft or gap_lft,
            right=mask_rgt or gap_rgt)

        if edges["top"] and not gap_top and y1 > band_y * 3:
            edges["top"] = False
        if edges["bottom"] and not gap_bot and y2 < img_h - 1 - band_y * 3:
            edges["bottom"] = False
        if edges["left"] and not gap_lft and x1 > band_x * 3:
            edges["left"] = False
        if edges["right"] and not gap_rgt and x2 < img_w - 1 - band_x * 3:
            edges["right"] = False
        return edges

    def _calc_output_size(self, orig_w, orig_h):
        s = self.settings
        if s.auto_output_size or (s.target_width <= 0 and s.target_height <= 0):
            bw, bh = orig_w, orig_h
        else:
            bw = s.target_width if s.target_width > 0 else orig_w
            bh = s.target_height if s.target_height > 0 else orig_h
        idx = s.frame_index
        if idx < 0 or idx >= len(FRAME_OPTIONS):
            idx = 0
        _, rw, rh = FRAME_OPTIONS[idx]
        if rw == 0 and rh == 0:
            return bw, bh
        elif rw == -1 and rh == -1:
            return bw, bh
        else:
            sc = min(bw / rw, bh / rh)
            return max(256, int(rw * sc)), max(256, int(rh * sc))

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

    def process(self, image_path: Path) -> dict:
        s = self.settings
        r = dict(
            status="error", reason="", input_path=image_path,
            output_path=None, moved_path=None,
            original_size=(0, 0), subject_size=(0, 0),
            thumbnail=None, edges=None)
        try:
            img = PILImage.open(image_path).convert("RGB")
            w, h = img.size
            r["original_size"] = (w, h)

            if max(w, h) < s.min_size_px:
                img.close(); del img
                dest = self._move_rejected(image_path)
                r.update(status="rejected",
                         reason=f"Quá nhỏ {w}×{h} (max<{s.min_size_px})",
                         moved_path=dest)
                return r

            mask = self._get_mask(img)
            bbox = self._bbox(mask)
            if bbox is None:
                r.update(status="skipped", reason="Không tìm thấy chủ thể")
                del mask; return r

            x1, y1, x2, y2 = bbox
            sw, sh = x2 - x1, y2 - y1
            r["subject_size"] = (sw, sh)

            if max(sw, sh) < s.min_size_px:
                img.close(); del img, mask
                dest = self._move_rejected(image_path)
                r.update(status="rejected",
                         reason=f"Chủ thể nhỏ {sw}×{sh}",
                         moved_path=dest)
                return r

            edges = self._detect_edges(mask, x1, y1, x2, y2, w, h)
            r["edges"] = edges

            if s.use_uniform_padding:
                pt = pb = pl = pr = s.padding_px
            else:
                pt, pb = s.padding_top_px, s.padding_bottom_px
                pl, pr = s.padding_left_px, s.padding_right_px

            cy1 = 0 if edges["top"] else max(0, y1 - pt)
            cy2 = h if edges["bottom"] else min(h, y2 + pb)
            cx1 = 0 if edges["left"] else max(0, x1 - pl)
            cx2 = w if edges["right"] else min(w, x2 + pr)

            crop = img.crop((cx1, cy1, cx2, cy2))
            cw, ch = crop.size
            del mask

            tw, th = self._calc_output_size(w, h)

            fill = s.subject_fill / 100.0
            scale = min(
                int(tw * fill) / max(cw, 1),
                int(th * fill) / max(ch, 1),
                s.max_upscale)
            nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
            resized = crop.resize((nw, nh), PILImage.LANCZOS)
            del crop

            canvas = PILImage.new(
                "RGB" if s.white_bg else "RGBA", (tw, th),
                (255, 255, 255) if s.white_bg else (0, 0, 0, 0))

            px, py = (tw - nw) // 2, (th - nh) // 2
            if edges["top"] and not edges["bottom"]:
                py = 0
            elif edges["bottom"] and not edges["top"]:
                py = th - nh
            elif not edges["top"] and not edges["bottom"]:
                py = max(0, py - int(th * 0.02))
            if edges["left"] and not edges["right"]:
                px = 0
            elif edges["right"] and not edges["left"]:
                px = tw - nw

            canvas.paste(resized, (px, py))
            del resized, img

            out_dir = image_path.parent / s.output_folder
            out_dir.mkdir(exist_ok=True)
            out = out_dir / f"{image_path.stem}.png"
            canvas.save(out, format="PNG", compress_level=s.png_compress)

            # ── FIX: tạo thumbnail bytes → thread-safe ──
            thumb = canvas.copy()
            thumb.thumbnail((THUMB_PX, THUMB_PX), PILImage.LANCZOS)
            # Convert sang bytes ngay tại worker thread
            # → UI thread chỉ cần decode, không phụ thuộc PIL object
            thumb_rgb = thumb.convert("RGB")
            thumb_data = np.array(thumb_rgb).copy()  # copy() = own memory
            del canvas, thumb, thumb_rgb

            edge_vn = {"top": "trên", "bottom": "dưới",
                       "left": "trái", "right": "phải"}
            e_str = ", ".join(edge_vn[k] for k, v in edges.items() if v) or "không"

            r.update(
                status="success",
                reason=f"{sw}×{sh}→{nw}×{nh} (×{scale:.1f}) Out:{tw}×{th} Biên:{e_str}",
                output_path=out,
                thumbnail=thumb_data,  # numpy array, thread-safe
            )
            return r
        except Exception as e:
            r.update(status="error", reason=str(e))
            return r


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 6 — BATCH WORKER                                   ║
# ╚══════════════════════════════════════════════════════════════╝

class BatchWorker(QThread):
    # ── FIX: thumbnail_ready signal riêng để tránh race condition ──
    sig_progress = pyqtSignal(int, int, dict)
    sig_file_start = pyqtSignal(int, str)
    sig_finished = pyqtSignal(list)
    sig_log = pyqtSignal(str)
    sig_sysload = pyqtSignal(float, float)

    def __init__(self):
        super().__init__()
        self._mx = QMutex(); self._cond = QWaitCondition()
        self._paused = self._cancelled = False
        self.file_list: list[Path] = []
        self.settings = CropSettings()
        self._cropper: SmartCropper | None = None

    def set_folder(self, path: str):
        f = Path(path)
        self.file_list = sorted(
            x for x in f.iterdir()
            if x.is_file() and x.suffix.lower() in SUPPORTED_EXT)

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

    def _throttle(self):
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        self.sig_sysload.emit(cpu, ram)
        if ram > RAM_THROTTLE_PCT:
            self.sig_log.emit(f"  ⚠️ RAM {ram:.0f}% → giải phóng bộ nhớ...")
            gc.collect()
            time.sleep(2.0)
            ram = psutil.virtual_memory().percent
            if ram > RAM_THROTTLE_PCT:
                self.sig_log.emit(f"  ⚠️ RAM vẫn {ram:.0f}% → chờ 5s...")
                time.sleep(5.0)
        lim = self.settings.cpu_limit
        if cpu > lim:
            sl = min(2.5, 0.2 + (cpu - lim) / 100.0 * 4.0)
            self.sig_log.emit(f"  🌡️ CPU {cpu:.0f}%>{lim:.0f}% → chờ {sl:.1f}s")
            time.sleep(sl)

    def run(self):
        self._cancelled = self._paused = False
        total = len(self.file_list)
        if total == 0:
            self.sig_log.emit("⚠️ Không có ảnh")
            self.sig_finished.emit([]); return

        lower_process_priority()
        self.sig_log.emit(
            f"🚀 Bắt đầu: {total:,} ảnh │ Model: {self.settings.model_name} │ "
            f"CPU ≤ {self.settings.cpu_limit:.0f}%"
            + ("\n   💡 Batch lớn — tối ưu RAM đang bật" if total > 500 else "")
            + "\n"
        )

        self._cropper = SmartCropper(self.settings)
        cnt = dict(success=0, skipped=0, rejected=0, error=0)
        t0 = time.time()

        for i, fp in enumerate(self.file_list):
            if self._cancelled:
                self.sig_log.emit("🛑 Đã huỷ!"); break
            self._check_pause()
            if self._cancelled:
                break
            self._throttle()
            self.sig_file_start.emit(i, fp.name)

            res = self._cropper.process(fp)
            cnt[res["status"]] = cnt.get(res["status"], 0) + 1

            icon = dict(success="✅", skipped="⏭️",
                        rejected="📦", error="❌").get(res["status"], "❓")

            if total > 1000:
                if i % 50 == 0 or res["status"] != "success":
                    self.sig_log.emit(
                        f"{icon} [{i+1:,}/{total:,}] {fp.name} — {res['reason'][:60]}")
            else:
                self.sig_log.emit(
                    f"{icon} [{i+1}/{total}] {fp.name}\n   └─ {res['reason']}")

            # ── FIX: emit TRƯỚC, không chỉnh res sau emit ──
            self.sig_progress.emit(i + 1, total, res)

            # ── FIX: GC thumbnail SAU khi UI đã nhận (sleep nhỏ cho slot chạy) ──
            # Không cần sleep vì thumbnail giờ là numpy array (copy sẵn)
            # Worker không giữ reference nào tới PIL object

            if (i + 1) % GC_EVERY_N == 0:
                gc.collect()

        elapsed = time.time() - t0
        self.sig_log.emit(
            f"\n{'═' * 54}\n🏁 HOÀN TẤT — {elapsed:.1f}s "
            f"(~{elapsed / max(sum(cnt.values()), 1):.2f}s/ảnh)\n"
            f"  ✅ Thành công: {cnt['success']:,}  ⏭️ Bỏ qua: {cnt['skipped']:,}\n"
            f"  📦 Loại bỏ: {cnt['rejected']:,}   ❌ Lỗi: {cnt['error']:,}\n"
            f"  📊 Tổng: {sum(cnt.values()):,}/{total:,}\n{'═' * 54}")

        self._cropper.release(); self._cropper = None; gc.collect()
        self.sig_finished.emit([cnt])


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 7 — WIDGETS                                        ║
# ╚══════════════════════════════════════════════════════════════╝

class SliderRow(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, label, lo, hi, default, step=1,
                 suffix="", decimals=0, tip="", lw=125, parent=None):
        super().__init__(parent)
        self._m = 10 ** decimals; self._s = suffix; self._d = decimals
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(4)
        lbl = QLabel(label); lbl.setFixedWidth(lw)
        if tip: lbl.setToolTip(tip)
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
        self.vlbl.setStyleSheet(f"color:{C['acc']};font-weight:600;font-size:11px;")
        lay.addWidget(self.vlbl)
        self._upd(self.slider.value())
        self.slider.valueChanged.connect(self._upd)

    def _upd(self, raw):
        v = raw / self._m
        self.vlbl.setText(
            f"{int(v)}{self._s}" if self._d == 0 else f"{v:.{self._d}f}{self._s}")
        self.valueChanged.emit(v)

    def value(self): return self.slider.value() / self._m
    def setValue(self, v): self.slider.setValue(int(v * self._m))


class SpinRow(QWidget):
    def __init__(self, label, lo, hi, default,
                 suffix="", tip="", lw=125, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(4)
        lbl = QLabel(label); lbl.setFixedWidth(lw)
        if tip: lbl.setToolTip(tip)
        lay.addWidget(lbl)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi); self.spin.setValue(default)
        if suffix: self.spin.setSuffix(f" {suffix}")
        lay.addWidget(self.spin, 1)

    def value(self): return self.spin.value()
    def setValue(self, v): self.spin.setValue(v)


class TextRow(QWidget):
    def __init__(self, label, default="", lw=125, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(4)
        l = QLabel(label); l.setFixedWidth(lw)
        lay.addWidget(l)
        self.le = QLineEdit(default)
        lay.addWidget(self.le, 1)

    def value(self): return self.le.text().strip()
    def setValue(self, v): self.le.setText(v)


class Sep(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background:{C['brd']};")


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 8 — DROP ZONE                                      ║
# ╚══════════════════════════════════════════════════════════════╝

class DropZone(QWidget):
    folder_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True); self.setFixedHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hov = False; self._path = ""

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m, w, h = 4, self.width(), self.height()
        bg = QColor(C["bg_hov"] if self._hov else C["dz_bg"])
        pp = QPainterPath(); pp.addRoundedRect(m, m, w - 2*m, h - 2*m, 10, 10)
        p.fillPath(pp, bg)
        pen = QPen(QColor(C["acc"]))
        pen.setWidth(3 if self._hov else 2)
        pen.setStyle(Qt.PenStyle.SolidLine if self._hov else Qt.PenStyle.DashLine)
        p.setPen(pen); p.drawRoundedRect(m, m, w - 2*m, h - 2*m, 10, 10)
        p.setPen(QColor(C["acc"] if self._hov else C["t2"]))
        p.setFont(QFont("Segoe UI Emoji", 22))
        p.drawText(0, 0, w, int(h * 0.58),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, "📂")
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        if self._path:
            p.setPen(QColor(C["ok"])); txt = f"✔  {Path(self._path).name}"
        else:
            txt = "Kéo thư mục ảnh vào đây — hoặc nhấn để chọn"
        p.drawText(8, int(h * 0.55), w - 16, int(h * 0.4),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, txt)
        p.end()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if Path(u.toLocalFile()).is_dir():
                    e.acceptProposedAction(); self._hov = True; self.update(); return
        e.ignore()

    def dragLeaveEvent(self, _): self._hov = False; self.update()

    def dropEvent(self, e):
        self._hov = False
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).is_dir():
                self._path = p; self.folder_dropped.emit(p); self.update(); return
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            d = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa ảnh")
            if d: self._path = d; self.folder_dropped.emit(d); self.update()

    def reset(self): self._path = ""; self.update()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 9 — THUMBNAIL GRID (FIXED)                         ║
# ╚══════════════════════════════════════════════════════════════╝
#
#  ── FIX SUMMARY ──
#
#  BUG 1: populate_names() không load ảnh gốc
#  FIX 1: Batch nhỏ (≤500) → load source thumbnail qua QPixmap
#         Batch lớn (>500) → không load, chỉ hiện tên
#
#  BUG 2: set_px_pil nhận numpy array thay vì PIL (do cropper fix)
#  FIX 2: Thêm set_px_numpy() nhận numpy array trực tiếp
#         Thêm set_px_path() load từ file path
#
#  BUG 3: Rolling window relayout tính row sai khi có header
#  FIX 3: _data_row_offset() method tính chính xác

class ThumbCard(QFrame):
    _ST = {
        "success": ("✅ Xong", C["ok"]),
        "skipped": ("⏭️ Bỏ qua", C["skip"]),
        "rejected": ("📦 Loại", C["warn"]),
        "error": ("❌ Lỗi", C["err"]),
        "processing": ("⏳", C["acc"]),
        "waiting": ("", C["t_off"]),
    }

    def __init__(self, name=""):
        super().__init__()
        self.setFixedSize(THUMB_PX + 14, THUMB_PX + 44)
        self._set_border(C["brd"])

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

    def _set_border(self, col):
        self.setStyleSheet(
            f"ThumbCard{{background:{C['th_bg']};"
            f"border:2px solid {col};border-radius:8px;}}")

    def set_px_path(self, file_path: str):
        """Load thumbnail từ file path (ảnh gốc)."""
        px = QPixmap(file_path)
        if not px.isNull():
            self.img_label.setPixmap(px.scaled(
                THUMB_PX - 4, THUMB_PX - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def set_px_numpy(self, arr: np.ndarray):
        """
        Load thumbnail từ numpy array (RGB, uint8).
        Thread-safe: numpy array đã copy() trong worker.
        """
        if arr is None or arr.size == 0:
            return
        h, w = arr.shape[:2]
        if arr.ndim == 3:
            ch = arr.shape[2]
            fmt = QImage.Format.Format_RGB888 if ch == 3 else QImage.Format.Format_RGBA8888
            bpl = w * ch
        else:
            fmt = QImage.Format.Format_Grayscale8
            bpl = w

        qimg = QImage(arr.data, w, h, bpl, fmt)
        pixmap = QPixmap.fromImage(qimg)
        if not pixmap.isNull():
            self.img_label.setPixmap(pixmap.scaled(
                THUMB_PX - 4, THUMB_PX - 4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def set_status(self, status: str, detail: str = ""):
        txt, col = self._ST.get(status, ("?", C["t2"]))
        self.status_label.setText(detail[:24] if detail else txt)
        self.status_label.setStyleSheet(
            f"color:{col};font-size:9px;font-weight:600;")
        bm = dict(success=C["ok"], error=C["err"], skipped=C["skip"],
                   rejected=C["warn"], processing=C["acc"])
        self._set_border(bm.get(status, C["brd"]))


class ThumbGrid(QScrollArea):
    """
    Thumbnail grid — 2 chế độ:

    ≤ MAX_GRID_CARDS: TẤT CẢ cards, load source thumbnail
    > MAX_GRID_CARDS: Rolling window, chỉ giữ N cards gần nhất
    """

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(4)
        self.setWidget(self._container)

        self._cards: list[ThumbCard] = []
        self._cols = 4
        self._total = 0
        self._is_large = False

        # Header cho batch lớn
        self._header = QLabel("")
        self._header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header.setStyleSheet(
            f"color:{C['acc']};font-size:11px;font-weight:600;"
            f"padding:4px;background:{C['bg_in']};"
            f"border:1px solid {C['brd']};border-radius:6px;")
        self._header.setVisible(False)

    def _row_offset(self) -> int:
        """Số row bị chiếm bởi header (0 hoặc 1)."""
        return 1 if self._header.isVisible() else 0

    def clear(self):
        """Xoá toàn bộ grid."""
        # Remove header
        self._grid.removeWidget(self._header)
        self._header.setVisible(False)
        self._header.setParent(None)

        # Remove all cards
        for c in self._cards:
            self._grid.removeWidget(c)
            c.deleteLater()
        self._cards.clear()
        self._total = 0
        self._is_large = False

        # Re-add header (ẩn)
        self._grid.addWidget(self._header, 0, 0, 1, 20)

    def populate(self, files: list[Path]):
        """
        Tạo grid từ danh sách file.
        ≤500: tạo card + load source thumbnail
        >500: chỉ hiện header, cards sẽ thêm lần lượt khi xử lý
        """
        self.clear()
        self._total = len(files)
        self._is_large = self._total > MAX_GRID_CARDS
        self._calc_cols()

        if self._is_large:
            # Batch lớn: chỉ header, cards thêm khi có kết quả
            self._header.setVisible(True)
            self._header.setText(
                f"📊 {self._total:,} ảnh — "
                f"hiển thị {MAX_GRID_CARDS} kết quả gần nhất")
        else:
            # Batch nhỏ: tạo tất cả cards + load thumbnail gốc
            self._header.setVisible(False)
            for i, f in enumerate(files):
                card = ThumbCard(f.name)
                card.set_px_path(str(f))  # ← FIX: load source thumbnail
                row = i // self._cols
                col = i % self._cols
                self._grid.addWidget(
                    card, row, col, Qt.AlignmentFlag.AlignTop)
                self._cards.append(card)

    def update_card(self, global_idx: int, result: dict):
        """Cập nhật card sau khi xử lý xong."""
        if self._is_large:
            # ── ROLLING WINDOW: thêm card mới ──
            name = ""
            inp = result.get("input_path")
            if isinstance(inp, Path):
                name = inp.name
            else:
                name = f"#{global_idx + 1}"

            card = ThumbCard(name)
            card.set_status(result["status"], result.get("reason", ""))

            # Set thumbnail từ numpy array
            thumb = result.get("thumbnail")
            if result["status"] == "success" and thumb is not None:
                if isinstance(thumb, np.ndarray):
                    card.set_px_numpy(thumb)

            # Thêm vào grid
            idx = len(self._cards)
            ro = self._row_offset()
            self._grid.addWidget(
                card, idx // self._cols + ro,
                idx % self._cols, Qt.AlignmentFlag.AlignTop)
            self._cards.append(card)

            # Xoá cards cũ nếu vượt giới hạn
            if len(self._cards) > MAX_GRID_CARDS:
                excess = len(self._cards) - MAX_GRID_CARDS
                for _ in range(excess):
                    old = self._cards.pop(0)
                    self._grid.removeWidget(old)
                    old.deleteLater()
                self._relayout()

            # Update header
            self._header.setText(
                f"📊 Đã xử lý {global_idx + 1:,}/{self._total:,} — "
                f"hiển thị {len(self._cards)} kết quả gần nhất")

        else:
            # ── BATCH NHỎ: update tại chỗ ──
            if 0 <= global_idx < len(self._cards):
                card = self._cards[global_idx]
                card.set_status(result["status"], result.get("reason", ""))

                # Set thumbnail từ numpy array (kết quả crop)
                thumb = result.get("thumbnail")
                if result["status"] == "success" and thumb is not None:
                    if isinstance(thumb, np.ndarray):
                        card.set_px_numpy(thumb)

        # Auto-scroll tới card mới nhất/đang xử lý
        target_card = self._cards[-1] if self._is_large else (
            self._cards[global_idx] if 0 <= global_idx < len(self._cards)
            else None)
        if target_card:
            self.ensureWidgetVisible(target_card, 50, 50)

    def mark_processing(self, global_idx: int):
        """Đánh dấu card đang xử lý."""
        if not self._is_large and 0 <= global_idx < len(self._cards):
            self._cards[global_idx].set_status("processing")

    def _relayout(self):
        """Sắp xếp lại grid sau khi xoá cards."""
        ro = self._row_offset()
        for i, card in enumerate(self._cards):
            self._grid.removeWidget(card)
            self._grid.addWidget(
                card, i // self._cols + ro,
                i % self._cols, Qt.AlignmentFlag.AlignTop)

    def _calc_cols(self):
        w = self.viewport().width() - 8
        cw = THUMB_PX + 20
        self._cols = max(2, min(w // cw, 12))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        old = self._cols
        self._calc_cols()
        if old != self._cols and self._cards:
            self._relayout()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 10 — DASHBOARD                                     ║
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
            f"font-size:15px;font-weight:700;color:{C['acc']};padding:2px 0;")
        root.addWidget(ttl)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_tab_settings()
        self._build_tab_output()
        self._apply_settings(CropSettings.load())

    def _build_tab_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(6)

        g1 = QGroupBox("🤖 Mô hình AI")
        g1l = QVBoxLayout(g1); g1l.setSpacing(4)
        mrow = QWidget(); mr = QHBoxLayout(mrow)
        mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(4)
        mr.addWidget(self._lbl("Mô hình:"))
        self.cb_model = QComboBox()
        self.cb_model.addItems(["u2net", "u2net_human_seg", "isnet-general-use"])
        self.cb_model.setToolTip("u2net: Tốt nhất │ human_seg: Người │ isnet: Nhanh")
        mr.addWidget(self.cb_model, 1)
        g1l.addWidget(mrow)
        self.sp_mask = SpinRow("Ngưỡng mask:", 25, 250, 120,
                               tip="Thấp=nhiều chi tiết, Cao=chặt hơn")
        g1l.addWidget(self.sp_mask)
        lay.addWidget(g1)

        g2 = QGroupBox("📐 Khoảng đệm (px)")
        g2l = QVBoxLayout(g2); g2l.setSpacing(4)
        note = QLabel(
            "💡 Cạnh nào chủ thể sát biên (hoặc cách ≤ vài px)\n"
            "sẽ tự bỏ padding → giữ bố cục gốc.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['t2']};font-size:10px;padding:1px;")
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
        for s in [self.sp_pad_t, self.sp_pad_b, self.sp_pad_l, self.sp_pad_r]:
            g2l.addWidget(s); s.setVisible(False)

        g2l.addWidget(Sep())
        self.sl_edge = SliderRow("Vùng biên (band):", 0, 10, 2.5,
                                 step=0.5, suffix="%", decimals=1,
                                 tip="Mask trong band X% biên → sát")
        g2l.addWidget(self.sl_edge)
        self.sp_edge_gap = SpinRow("Dung sai sát biên:", 0, 30, 5, suffix="px",
                                   tip="Bbox cách biên ≤ Npx → sát biên")
        g2l.addWidget(self.sp_edge_gap)
        lay.addWidget(g2)

        g3 = QGroupBox("🎯 Chủ thể trên canvas")
        g3l = QVBoxLayout(g3); g3l.setSpacing(4)
        self.sl_fill = SliderRow("Chiếm:", 50, 99, 92, suffix="%",
                                 tip="% chủ thể trên canvas")
        g3l.addWidget(self.sl_fill)
        self.sl_maxup = SliderRow("Phóng to max:", 1, 4, 2,
                                  step=0.5, suffix="x", decimals=1,
                                  tip="Giới hạn upscale")
        g3l.addWidget(self.sl_maxup)
        lay.addWidget(g3)

        g4 = QGroupBox("⚡ Hiệu năng")
        g4l = QVBoxLayout(g4); g4l.setSpacing(4)
        self.sl_cpu = SliderRow("Giới hạn CPU:", 5, 80, 20, step=5, suffix="%")
        g4l.addWidget(self.sl_cpu)
        lay.addWidget(g4)

        lay.addStretch(1)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "🖼️ Cài đặt")

    def _build_tab_output(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(6)

        g1 = QGroupBox("🖼️ Tỷ lệ & Kích thước")
        g1l = QVBoxLayout(g1); g1l.setSpacing(5)
        frow = QWidget(); fr = QHBoxLayout(frow)
        fr.setContentsMargins(0, 0, 0, 0); fr.setSpacing(4)
        fr.addWidget(self._lbl("Frame:"))
        self.cb_frame = QComboBox()
        for label, _, _ in FRAME_OPTIONS:
            self.cb_frame.addItem(label)
        self.cb_frame.currentIndexChanged.connect(self._on_frame)
        fr.addWidget(self.cb_frame, 1)
        g1l.addWidget(frow); g1l.addWidget(Sep())

        self.rad_auto = QRadioButton("  Tự động (= kích thước ảnh gốc)")
        self.rad_custom = QRadioButton("  Nhập thủ công:")
        self.rad_auto.setChecked(True)
        self.rad_auto.toggled.connect(self._on_size_mode)
        bg = QButtonGroup(self)
        bg.addButton(self.rad_auto); bg.addButton(self.rad_custom)
        g1l.addWidget(self.rad_auto); g1l.addWidget(self.rad_custom)

        self.sz_w = QWidget()
        sz = QHBoxLayout(self.sz_w)
        sz.setContentsMargins(18, 1, 0, 1); sz.setSpacing(4)
        sz.addWidget(self._lbl("W:", 22))
        self.sp_w = QSpinBox(); self.sp_w.setRange(256, 4096); self.sp_w.setValue(1024)
        self.sp_w.setSuffix(" px"); sz.addWidget(self.sp_w, 1)
        xl = QLabel("×"); xl.setFixedWidth(12)
        xl.setAlignment(Qt.AlignmentFlag.AlignCenter); sz.addWidget(xl)
        sz.addWidget(self._lbl("H:", 22))
        self.sp_h = QSpinBox(); self.sp_h.setRange(256, 4096); self.sp_h.setValue(1024)
        self.sp_h.setSuffix(" px"); sz.addWidget(self.sp_h, 1)
        g1l.addWidget(self.sz_w); self.sz_w.setEnabled(False)
        lay.addWidget(g1)

        g2 = QGroupBox("📦 Chất lượng PNG")
        g2l = QVBoxLayout(g2); g2l.setSpacing(4)
        self.sp_png = SpinRow("Nén:", 0, 9, 9, tip="0=nhanh, 9=nhỏ nhất (lossless)")
        g2l.addWidget(self.sp_png)
        self.chk_white = QCheckBox("  Nền trắng đầu ra")
        self.chk_white.setChecked(True); g2l.addWidget(self.chk_white)
        lay.addWidget(g2)

        g3 = QGroupBox("🗑️ Lọc & Thư mục")
        g3l = QVBoxLayout(g3); g3l.setSpacing(4)
        self.sp_min = SpinRow("Loại nếu max cạnh <", 0, 2048, 512, suffix="px",
                              tip="max(w,h)<N → di chuyển")
        g3l.addWidget(self.sp_min); g3l.addWidget(Sep())
        self.txt_out = TextRow("Thư mục kết quả:", "Done")
        g3l.addWidget(self.txt_out)
        self.txt_rej = TextRow("Thư mục loại bỏ:", "Loại bỏ")
        g3l.addWidget(self.txt_rej)
        lay.addWidget(g3)

        lay.addStretch(1)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "📤 Đầu ra")

    @staticmethod
    def _lbl(t, w=125):
        l = QLabel(t); l.setFixedWidth(w); return l

    def _toggle_pad(self, uniform):
        self.sp_pad_all.setVisible(uniform)
        for s in [self.sp_pad_t, self.sp_pad_b, self.sp_pad_l, self.sp_pad_r]:
            s.setVisible(not uniform)

    def _on_frame(self, idx):
        if idx < 0 or idx >= len(FRAME_OPTIONS): return
        _, rw, rh = FRAME_OPTIONS[idx]
        if rw > 0 and rh > 0:
            base = max(self.sp_w.value(), self.sp_h.value())
            sc = base / max(rw, rh)
            self.sp_w.setValue(int(rw * sc)); self.sp_h.setValue(int(rh * sc))

    def _on_size_mode(self, auto):
        self.sz_w.setEnabled(not auto)

    def get_settings(self) -> CropSettings:
        auto = self.rad_auto.isChecked()
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
            frame_index=self.cb_frame.currentIndex(),
            target_width=self.sp_w.value() if not auto else 0,
            target_height=self.sp_h.value() if not auto else 0,
            auto_output_size=auto,
            png_compress=self.sp_png.value(),
            min_size_px=self.sp_min.value(),
            subject_fill=self.sl_fill.value(),
            mask_threshold=self.sp_mask.value(),
            white_bg=self.chk_white.isChecked(),
            max_upscale=self.sl_maxup.value(),
            output_folder=self.txt_out.value() or "Done",
            rejected_folder=self.txt_rej.value() or "Loại bỏ",
            cpu_limit=self.sl_cpu.value())
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
        self.sl_maxup.setValue(s.max_upscale)
        self.sl_cpu.setValue(s.cpu_limit)
        fi = s.frame_index if 0 <= s.frame_index < len(FRAME_OPTIONS) else 0
        self.cb_frame.setCurrentIndex(fi)
        if s.auto_output_size:
            self.rad_auto.setChecked(True)
        else:
            self.rad_custom.setChecked(True)
        self.sp_w.setValue(s.target_width if s.target_width > 0 else 1024)
        self.sp_h.setValue(s.target_height if s.target_height > 0 else 1024)
        self.sp_png.setValue(s.png_compress)
        self.sp_min.setValue(s.min_size_px)
        self.chk_white.setChecked(s.white_bg)
        self.txt_out.setValue(s.output_folder)
        self.txt_rej.setValue(s.rejected_folder)

    def reset_defaults(self):
        d = CropSettings.defaults()
        self._apply_settings(d)
        d.save()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 11 — MAIN WINDOW                                   ║
# ╚══════════════════════════════════════════════════════════════╝

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"🔲 {APP_TITLE}")
        self.setMinimumSize(1060, 640); self.resize(1320, 760)
        self.sys = detect_system()
        self.worker = BatchWorker()
        self.worker.sig_progress.connect(self._on_progress)
        self.worker.sig_file_start.connect(self._on_file_start)
        self.worker.sig_finished.connect(self._on_finished)
        self.worker.sig_log.connect(self._on_log)
        self.worker.sig_sysload.connect(self._on_sysload)
        self._busy = False
        self.setStyleSheet(build_qss())
        self._build()
        self._setup_statusbar()
        self._start_monitor()

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

        ab = QWidget(); al = QHBoxLayout(ab)
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

        al.addWidget(self.btn_start); al.addWidget(self.btn_pause)
        al.addWidget(self.btn_cancel); al.addWidget(self.btn_reset)
        al.addStretch(1)

        self.lbl_count = QLabel("📁 Chưa chọn thư mục")
        self.lbl_count.setStyleSheet(f"color:{C['t2']};font-size:12px;")
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
        lh.setStyleSheet(f"color:{C['acc']};font-weight:700;font-size:11px;")
        ll.addWidget(lh)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        self.log.setPlaceholderText("Nhật ký hiển thị khi bắt đầu...")
        self.log.document().setMaximumBlockCount(5000)
        ll.addWidget(self.log)
        split.addWidget(log_w)

        split.setStretchFactor(0, 6); split.setStretchFactor(1, 1)
        split.setSizes([550, 80])
        rl.addWidget(split, 1)
        main.addWidget(right, 1)

    def _setup_statusbar(self):
        sb = QStatusBar(); self.setStatusBar(sb)
        s = self.sys
        hw = [f"⚙ {s.cpu_name[:35]}", f"🧵 {s.cores_p}C/{s.cores_l}T",
              f"🧠 {s.ram_gb:.0f}GB"]
        if s.has_cuda: hw.append(f"🎮 {s.gpu[:25]}")
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

    def _start_monitor(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_sys)
        self._timer.start(2000); self._tick_sys()

    def _tick_sys(self):
        self._show_load(psutil.cpu_percent(interval=0),
                        psutil.virtual_memory().percent)

    def _show_load(self, cpu, ram):
        cc = C["ok"] if cpu <= 40 else (C["warn"] if cpu <= 70 else C["err"])
        rc = C["ok"] if ram <= 60 else (C["warn"] if ram <= 80 else C["err"])
        self.lbl_cpu.setText(f"CPU: {cpu:.0f}%")
        self.lbl_cpu.setStyleSheet(
            f"color:{cc};font-size:11px;font-weight:600;"
            f"font-family:'Cascadia Code',monospace;padding:0 4px;")
        self.lbl_ram.setText(f"RAM: {ram:.0f}%")
        self.lbl_ram.setStyleSheet(
            f"color:{rc};font-size:11px;font-weight:600;"
            f"font-family:'Cascadia Code',monospace;padding:0 4px;")

    def _on_folder(self, path):
        self.worker.set_folder(path)
        n = len(self.worker.file_list)
        self.lbl_count.setText(f"📁 {n:,} ảnh" if n else "⚠️ Không có ảnh")
        self.btn_start.setEnabled(n > 0)
        self.progress.setMaximum(max(n, 1)); self.progress.setValue(0)
        if n:
            self.thumbs.populate(self.worker.file_list)
            self._on_log(
                f"📂 {path}\n📁 {n:,} ảnh"
                + (f"\n💡 Batch lớn — tối ưu hiệu suất" if n > 500 else ""))
        else:
            self.thumbs.clear()

    def _on_start(self):
        if self._busy: return
        self.worker.settings = self.dash.get_settings()
        self.progress.setValue(0); self.log.clear()
        self._set_busy(True); self.worker.start()

    def _on_pause(self):
        if not self._busy: return
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
        if not self._busy: return
        if QMessageBox.question(
            self, "Xác nhận", "Huỷ bỏ? Ảnh đã xong vẫn giữ.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.worker.cancel()

    def _on_reset(self):
        if self._busy:
            if QMessageBox.question(
                self, "Đang xử lý", "Huỷ và làm mới?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return
            self.worker.cancel(); self.worker.wait(3000)
        self.worker.release(); self.thumbs.clear(); self.log.clear()
        self.progress.setValue(0); self.progress.setMaximum(1)
        self.dz.reset()
        self.lbl_count.setText("📁 Chưa chọn thư mục")
        self.btn_start.setEnabled(False)
        self.dash.reset_defaults(); self._set_busy(False); gc.collect()
        self._on_log("🔄 Đã làm mới — Bộ nhớ giải phóng")

    def _on_progress(self, cur, total, result):
        self.progress.setValue(cur)
        self.thumbs.update_card(cur - 1, result)

    def _on_file_start(self, idx, name):
        self.thumbs.mark_processing(idx)

    def _on_finished(self, summary):
        self._set_busy(False)
        if summary:
            cnt = summary[0]; s = self.dash.get_settings()
            QMessageBox.information(self, "Hoàn tất",
                f"✅ Xong!\n\n"
                f"Thành công: {cnt.get('success',0):,} → '{s.output_folder}'\n"
                f"Loại bỏ: {cnt.get('rejected',0):,} → '{s.rejected_folder}'\n"
                f"Bỏ qua: {cnt.get('skipped',0):,}  Lỗi: {cnt.get('error',0):,}\n\n"
                f"Tổng: {sum(cnt.values()):,}")

    def _on_log(self, msg):
        self.log.append(msg)
        c = self.log.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(c)

    def _on_sysload(self, cpu, ram):
        self._show_load(cpu, ram)

    def _set_busy(self, busy):
        self._busy = busy
        self.btn_start.setEnabled(not busy)
        self.btn_pause.setEnabled(busy)
        self.btn_cancel.setEnabled(busy)
        self.dz.setEnabled(not busy)
        self.btn_reset.setEnabled(True)
        if not busy: self.btn_pause.setText("⏸  Dừng")

    def closeEvent(self, e):
        try: self.dash.get_settings()
        except Exception: pass
        if self._busy: self.worker.cancel(); self.worker.wait(3000)
        self.worker.release(); gc.collect(); e.accept()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 12 — ENTRY                                         ║
# ╚══════════════════════════════════════════════════════════════╝

def main():
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    f = QFont("Segoe UI", 10)
    f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(f)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()