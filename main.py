"""
╔══════════════════════════════════════════════════════════════════════╗
║  SMART SUBJECT CROPPER v2.5 — AI-Powered Batch Image Cropping      ║
║                                                                      ║
║  Core Logic:                                                         ║
║  • Output giữ ĐÚNG frame ratio & kích thước ảnh gốc                ║
║  • Chủ thể sát nền nhất có thể (padding cố định ~10px)             ║
║  • Edge-aware: nếu chủ thể sát biên ảnh → KHÔNG thêm padding      ║
║  • Loại bỏ chỉ khi CẢ HAI cạnh < ngưỡng (max > ngưỡng → giữ)     ║
║  • AI mask 3 lớp: rembg → morpho → connected component + refine    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys, os, gc, time, shutil, platform, subprocess
from pathlib import Path
from dataclasses import dataclass
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
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition
from PyQt6.QtGui import (
    QFont, QPixmap, QImage, QColor, QPainter, QPen,
    QPainterPath, QTextCursor,
)


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 1 — CONSTANTS                                      ║
# ╚══════════════════════════════════════════════════════════════╝

APP_TITLE = "Smart Subject Cropper v2.5"
SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
THUMB_PX = 128

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


@dataclass
class CropSettings:
    model_name: str = "u2net"
    # Padding cố định (pixel) — mặc định sát nền nhất
    padding_px: int = 10
    padding_top_px: int = 10
    padding_bottom_px: int = 10
    padding_left_px: int = 10
    padding_right_px: int = 10
    use_uniform_padding: bool = True
    # Edge detection: % cạnh ảnh để coi là "sát biên"
    edge_threshold_pct: float = 3.0
    # Frame
    frame_index: int = 0
    target_width: int = 0              # 0 = auto theo ảnh gốc
    target_height: int = 0
    # Quality
    png_compress: int = 9
    min_size_px: int = 512             # Loại nếu CẢ HAI cạnh < giá trị này
    subject_fill: float = 92.0         # % chủ thể chiếm canvas
    mask_threshold: int = 120
    white_bg: bool = True
    max_upscale: float = 2.0
    # Folders
    output_folder: str = "Done"
    rejected_folder: str = "Loại bỏ"
    # Output size mode
    auto_output_size: bool = True      # True = theo ảnh gốc


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 2 — THEME                                          ║
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
        border-radius:10px; margin-top:11px;
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
        padding:7px 16px; font-weight:600; min-height:14px;
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
    """


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 3 — SYSTEM                                         ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class SysProfile:
    os_name: str = ""
    cpu_name: str = ""
    cores_p: int = 1
    cores_l: int = 1
    ram_gb: float = 0
    ram_free: float = 0
    gpu: str = "Không phát hiện"
    has_cuda: bool = False
    rec_workers: int = 1
    cpu_target: float = 20.0

    def text(self) -> str:
        return (
            f"🖥  HĐH :  {self.os_name}\n"
            f"⚙  CPU :  {self.cpu_name}\n"
            f"🧵  Nhân:  {self.cores_p} vật lý / {self.cores_l} logic\n"
            f"🧠  RAM :  {self.ram_gb:.1f} GB (trống {self.ram_free:.1f} GB)\n"
            f"🎮  GPU :  {self.gpu}\n"
            f"⚡  CUDA:  {'Có ✔' if self.has_cuda else 'Không'}"
        )


def detect_system(cpu_target=20.0) -> SysProfile:
    mem = psutil.virtual_memory()
    cp = psutil.cpu_count(logical=False) or 1
    cl = psutil.cpu_count(logical=True) or 1
    rt = mem.total / (1024 ** 3)
    rf = mem.available / (1024 ** 3)
    cn = platform.processor() or ""
    if not cn and platform.system() == "Windows":
        try:
            r = subprocess.run(["wmic", "cpu", "get", "name"],
                               capture_output=True, text=True, timeout=5)
            ls = [l.strip() for l in r.stdout.split("\n") if l.strip()]
            if len(ls) > 1: cn = ls[1]
        except Exception: pass
    cn = cn or "Không xác định"
    gpu, cuda = "Không phát hiện", False
    try:
        import onnxruntime as ort
        if "CUDAExecutionProvider" in ort.get_available_providers():
            cuda = True; gpu = "NVIDIA GPU (CUDA)"
            try:
                r = subprocess.run(
                    ["nvidia-smi","--query-gpu=name","--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    gpu = r.stdout.strip().split("\n")[0]
            except Exception: pass
    except ImportError: pass
    wr = max(1, int(rf * 0.4 / 0.5))
    wc = max(1, int(cp * cpu_target / 100))
    return SysProfile(
        os_name=f"{platform.system()} {platform.release()}",
        cpu_name=cn, cores_p=cp, cores_l=cl,
        ram_gb=rt, ram_free=rf, gpu=gpu, has_cuda=cuda,
        rec_workers=max(1, min(wc, wr, cp)), cpu_target=cpu_target,
    )


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 4 — AI CROPPER ENGINE (Logic v2.5)                 ║
# ╚══════════════════════════════════════════════════════════════╝
#
#  Pipeline:
#  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐
#  │ Validate │─▶│  AI Mask  │─▶│  Refine  │─▶│  Smart   │
#  │ max(w,h) │  │  3-layer  │  │  + Edge  │  │  Crop    │
#  │ ≥ minpx  │  │  cleanup  │  │  Detect  │  │  + Place │
#  └──────────┘  └───────────┘  └──────────┘  └──────────┘
#       │ fail                                       │
#       ▼                                            ▼
#  ┌──────────┐                               ┌──────────┐
#  │ Move to  │                               │ Save PNG │
#  │ Rejected │                               │ Lossless │
#  └──────────┘                               └──────────┘
#
#  Edge-Aware Logic:
#  ┌─────────────────────┐
#  │     padding_top     │  ← nếu subject KHÔNG sát biên trên
#  │  ┌───────────────┐  │
#  │  │               │  │
#  │ p│   SUBJECT     │p │  ← padding_left / _right
#  │  │               │  │
#  │  └───────────────┘  │
#  │     padding_bot     │  ← nếu subject KHÔNG sát biên dưới
#  └─────────────────────┘
#
#  Nếu subject sát biên → padding = 0 ở cạnh đó
#  (ví dụ: bàn, landscape, sản phẩm cắt sát mép)

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

    # ─── AI Mask — 3 lớp làm sạch ───
    def _get_mask(self, img: PILImage.Image) -> np.ndarray:
        """
        Lớp 1: rembg raw mask (U²-Net / ISNet)
        Lớp 2: Gaussian blur + adaptive threshold → mịn biên
        Lớp 3: Morpho close/open + connected component → loại noise
        """
        s = self.settings

        # ── Lớp 1: AI raw mask ──
        raw = remove(img, session=self.session, only_mask=True)
        mask = np.array(raw)
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_RGB2GRAY)

        # ── Lớp 2: Smooth + Threshold ──
        # Gaussian blur giảm răng cưa biên mask
        mask = cv2.GaussianBlur(mask, (5, 5), 0)

        # Dùng 2 ngưỡng: chắc chắn subject + có thể subject
        _, sure_fg = cv2.threshold(mask, s.mask_threshold, 255, cv2.THRESH_BINARY)
        _, probable_fg = cv2.threshold(
            mask, max(30, s.mask_threshold - 50), 255, cv2.THRESH_BINARY
        )

        # ── Lớp 3: Morphological cleanup ──
        kern_sm = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        kern_lg = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))

        # Đóng lỗ bên trong subject (sure_fg)
        sure_fg = cv2.morphologyEx(sure_fg, cv2.MORPH_CLOSE, kern_lg, iterations=3)

        # Mở để loại noise nhỏ
        sure_fg = cv2.morphologyEx(sure_fg, cv2.MORPH_OPEN, kern_sm, iterations=1)

        # Dùng probable_fg để mở rộng biên subject
        # (tránh mất chi tiết mỏng như tóc, cành cây)
        combined = cv2.bitwise_or(sure_fg, probable_fg)
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kern_sm, iterations=1)

        # Flood fill từ sure_fg vào combined → giữ vùng liên thông
        # Chỉ giữ vùng trong combined mà overlap với sure_fg
        n_sure, labels_sure, stats_sure, _ = cv2.connectedComponentsWithStats(sure_fg, 8)
        n_comb, labels_comb, stats_comb, _ = cv2.connectedComponentsWithStats(combined, 8)

        # Tìm component lớn nhất trong sure_fg
        if n_sure <= 1:
            return sure_fg

        areas = stats_sure[1:, cv2.CC_STAT_AREA]
        main_label = 1 + int(np.argmax(areas))
        main_mask = (labels_sure == main_label).astype(np.uint8) * 255

        # Mở rộng: lấy vùng combined mà overlap với main subject
        if n_comb > 1:
            overlap_labels = set(np.unique(labels_comb[main_mask > 0]))
            overlap_labels.discard(0)
            expanded = np.zeros_like(combined)
            for lbl in overlap_labels:
                expanded[labels_comb == lbl] = 255
            # Merge
            final = cv2.bitwise_or(main_mask, expanded)
            # Clean lần cuối
            final = cv2.morphologyEx(final, cv2.MORPH_CLOSE, kern_sm, iterations=1)
            return final

        return main_mask

    @staticmethod
    def _bbox(mask):
        coords = np.argwhere(mask > 0)
        if len(coords) == 0:
            return None
        y1, x1 = coords.min(axis=0)
        y2, x2 = coords.max(axis=0)
        return int(x1), int(y1), int(x2), int(y2)

    def _detect_edges(self, x1, y1, x2, y2, img_w, img_h):
        """
        Phát hiện cạnh nào của subject sát biên ảnh.
        Trả dict: {top, bottom, left, right} = True nếu sát biên.
        """
        threshold = self.settings.edge_threshold_pct / 100.0
        th_x = int(img_w * threshold)
        th_y = int(img_h * threshold)
        return dict(
            top=y1 <= th_y,
            bottom=y2 >= img_h - 1 - th_y,
            left=x1 <= th_x,
            right=x2 >= img_w - 1 - th_x,
        )

    def _calc_output_size(self, orig_w, orig_h):
        """Tính canvas đầu ra — mặc định theo ảnh gốc."""
        s = self.settings

        # Nếu auto → giữ nguyên kích thước ảnh gốc
        if s.auto_output_size or (s.target_width <= 0 and s.target_height <= 0):
            base_w, base_h = orig_w, orig_h
        else:
            base_w = s.target_width if s.target_width > 0 else orig_w
            base_h = s.target_height if s.target_height > 0 else orig_h

        idx = s.frame_index
        if idx < 0 or idx >= len(FRAME_OPTIONS):
            idx = 0
        _, rw, rh = FRAME_OPTIONS[idx]

        if rw == 0 and rh == 0:
            # Auto: giữ tỷ lệ gốc
            return base_w, base_h
        elif rw == -1 and rh == -1:
            # Custom: dùng base_w × base_h
            return base_w, base_h
        else:
            # Preset ratio: fit vào base size
            scale = min(base_w / rw, base_h / rh)
            return max(256, int(rw * scale)), max(256, int(rh * scale))

    def _move_rejected(self, path: Path, reason: str) -> Path:
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
            thumbnail=None, edges_near=None,
        )

        try:
            # ── 1. LOAD ──
            img = PILImage.open(image_path).convert("RGB")
            w, h = img.size
            r["original_size"] = (w, h)

            # ── 2. REJECT: chỉ khi CẢ HAI cạnh < min ──
            if max(w, h) < s.min_size_px:
                img.close(); del img
                dest = self._move_rejected(
                    image_path, f"Cả 2 cạnh < {s.min_size_px}px ({w}×{h})"
                )
                r.update(status="rejected",
                         reason=f"Quá nhỏ ({w}×{h}) → đã chuyển",
                         moved_path=dest)
                return r

            # ── 3. AI MASK ──
            mask = self._get_mask(img)
            bbox = self._bbox(mask)

            if bbox is None:
                r.update(status="skipped", reason="Không phát hiện chủ thể")
                return r

            x1, y1, x2, y2 = bbox
            sw, sh = x2 - x1, y2 - y1
            r["subject_size"] = (sw, sh)

            # Subject quá nhỏ? (cả 2 cạnh subject < min)
            if max(sw, sh) < s.min_size_px:
                img.close(); del img, mask
                dest = self._move_rejected(
                    image_path, f"Chủ thể quá nhỏ ({sw}×{sh})"
                )
                r.update(status="rejected",
                         reason=f"Chủ thể nhỏ ({sw}×{sh}) → đã chuyển",
                         moved_path=dest)
                return r

            # ── 4. EDGE-AWARE PADDING ──
            edges = self._detect_edges(x1, y1, x2, y2, w, h)
            r["edges_near"] = edges

            if s.use_uniform_padding:
                p = s.padding_px
                pt = 0 if edges["top"] else p
                pb = 0 if edges["bottom"] else p
                pl = 0 if edges["left"] else p
                pr = 0 if edges["right"] else p
            else:
                pt = 0 if edges["top"] else s.padding_top_px
                pb = 0 if edges["bottom"] else s.padding_bottom_px
                pl = 0 if edges["left"] else s.padding_left_px
                pr = 0 if edges["right"] else s.padding_right_px

            # Tính vùng crop (subject + padding, clamp vào biên ảnh)
            cx1 = max(0, x1 - pl)
            cy1 = max(0, y1 - pt)
            cx2 = min(w, x2 + pr)
            cy2 = min(h, y2 + pb)

            # Nếu cạnh sát biên → crop tới tận biên ảnh gốc (giữ nguyên content)
            if edges["top"]:    cy1 = 0
            if edges["bottom"]: cy2 = h
            if edges["left"]:   cx1 = 0
            if edges["right"]:  cx2 = w

            crop = img.crop((cx1, cy1, cx2, cy2))
            cw, ch = crop.size

            # ── 5. OUTPUT SIZE ──
            tw, th = self._calc_output_size(w, h)

            # ── 6. SCALE + PLACE trên canvas ──
            fill = s.subject_fill / 100.0
            uw, uh = int(tw * fill), int(th * fill)
            scale = min(uw / cw, uh / ch, s.max_upscale)
            nw = max(1, int(cw * scale))
            nh = max(1, int(ch * scale))

            resized = crop.resize((nw, nh), PILImage.LANCZOS)

            if s.white_bg:
                canvas = PILImage.new("RGB", (tw, th), (255, 255, 255))
            else:
                canvas = PILImage.new("RGBA", (tw, th), (0, 0, 0, 0))

            # Smart placement: dựa vào cạnh sát biên
            # Default: center
            px = (tw - nw) // 2
            py = (th - nh) // 2

            # Nếu sát biên nào → dính vào biên đó
            if edges["top"] and not edges["bottom"]:
                py = 0
            elif edges["bottom"] and not edges["top"]:
                py = th - nh
            elif not edges["top"] and not edges["bottom"]:
                # Hơi lệch lên 2% cho tự nhiên (product photo)
                py = max(0, py - int(th * 0.02))

            if edges["left"] and not edges["right"]:
                px = 0
            elif edges["right"] and not edges["left"]:
                px = tw - nw

            canvas.paste(resized, (px, py))

            # ── 7. SAVE ──
            out_dir = image_path.parent / s.output_folder
            out_dir.mkdir(exist_ok=True)
            out = out_dir / f"{image_path.stem}.png"
            canvas.save(out, format="PNG", compress_level=s.png_compress)

            # ── 8. THUMBNAIL ──
            thumb = canvas.copy()
            thumb.thumbnail((THUMB_PX, THUMB_PX), PILImage.LANCZOS)

            del resized, crop, mask, canvas, img

            edge_info = ", ".join(
                k for k, v in edges.items() if v
            ) or "không"

            r.update(
                status="success",
                reason=(
                    f"{sw}×{sh} → {nw}×{nh} (×{scale:.1f}) "
                    f"Canvas {tw}×{th} │ Sát biên: {edge_info}"
                ),
                output_path=out, thumbnail=thumb,
            )
            return r

        except Exception as e:
            r.update(status="error", reason=str(e))
            return r


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 5 — BATCH WORKER                                   ║
# ╚══════════════════════════════════════════════════════════════╝

class BatchWorker(QThread):
    sig_progress = pyqtSignal(int, int, dict)
    sig_file_start = pyqtSignal(int, str)
    sig_finished = pyqtSignal(list)
    sig_log = pyqtSignal(str)
    sig_sysload = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mx = QMutex()
        self._cond = QWaitCondition()
        self._paused = self._cancelled = False
        self.file_list: list[Path] = []
        self.settings = CropSettings()
        self.cpu_limit = 20.0
        self._cropper: SmartCropper | None = None

    def set_folder(self, path: str):
        folder = Path(path)
        self.file_list = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
        )

    def pause(self):
        self._mx.lock(); self._paused = True; self._mx.unlock()

    def resume(self):
        self._mx.lock(); self._paused = False
        self._cond.wakeAll(); self._mx.unlock()

    def cancel(self):
        self._mx.lock(); self._cancelled = True; self._paused = False
        self._cond.wakeAll(); self._mx.unlock()

    def release_resources(self):
        if self._cropper:
            self._cropper.release(); self._cropper = None
        gc.collect()

    def _check_pause(self):
        self._mx.lock()
        while self._paused and not self._cancelled:
            self._cond.wait(self._mx)
        self._mx.unlock()

    def _throttle(self):
        cpu = psutil.cpu_percent(interval=0.15)
        ram = psutil.virtual_memory().percent
        self.sig_sysload.emit(cpu, ram)
        if cpu > self.cpu_limit:
            ov = (cpu - self.cpu_limit) / 100.0
            sl = min(2.5, 0.2 + ov * 4.0)
            self.sig_log.emit(
                f"  🌡️ CPU {cpu:.0f}% > {self.cpu_limit:.0f}% → chờ {sl:.1f}s"
            )
            time.sleep(sl)

    def run(self):
        self._cancelled = self._paused = False
        total = len(self.file_list)
        if total == 0:
            self.sig_log.emit("⚠️  Không có ảnh")
            self.sig_finished.emit([]); return

        self.sig_log.emit(
            f"🚀 Bắt đầu: {total} ảnh │ Model: {self.settings.model_name} │ "
            f"CPU ≤ {self.cpu_limit:.0f}%\n"
        )
        self._cropper = SmartCropper(self.settings)
        results = []
        cnt = dict(success=0, skipped=0, rejected=0, error=0)
        t0 = time.time()

        for i, fp in enumerate(self.file_list):
            if self._cancelled:
                self.sig_log.emit("🛑 Đã huỷ!"); break
            self._check_pause()
            if self._cancelled: break
            self._throttle()
            self.sig_file_start.emit(i, fp.name)

            res = self._cropper.process(fp)
            results.append(res)
            cnt[res["status"]] = cnt.get(res["status"], 0) + 1

            icon = dict(success="✅", skipped="⏭️",
                        rejected="📦", error="❌").get(res["status"], "❓")
            self.sig_log.emit(
                f"{icon} [{i+1}/{total}]  {fp.name}\n    └─ {res['reason']}"
            )
            self.sig_progress.emit(i + 1, total, res)

        el = time.time() - t0
        self.sig_log.emit(
            f"\n{'═'*54}\n🏁 HOÀN TẤT — {el:.1f}s (~{el/max(len(results),1):.2f}s/ảnh)\n"
            f"   ✅ Thành công: {cnt['success']}   ⏭️ Bỏ qua: {cnt['skipped']}\n"
            f"   📦 Loại bỏ: {cnt['rejected']}     ❌ Lỗi: {cnt['error']}\n{'═'*54}"
        )
        self._cropper.release(); self._cropper = None
        gc.collect()
        self.sig_finished.emit(results)


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 6 — WIDGETS                                        ║
# ╚══════════════════════════════════════════════════════════════╝

class SliderRow(QWidget):
    valueChanged = pyqtSignal(float)
    def __init__(self, label, lo, hi, default, step=1,
                 suffix="", decimals=0, tip="", label_w=130, parent=None):
        super().__init__(parent)
        self._m = 10 ** decimals; self._s = suffix; self._d = decimals
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(5)
        lbl = QLabel(label); lbl.setFixedWidth(label_w)
        if tip: lbl.setToolTip(tip)
        lay.addWidget(lbl)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(lo*self._m))
        self.slider.setMaximum(int(hi*self._m))
        self.slider.setValue(int(default*self._m))
        self.slider.setSingleStep(int(step*self._m))
        lay.addWidget(self.slider, 1)
        self.vlbl = QLabel()
        self.vlbl.setFixedWidth(48)
        self.vlbl.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.vlbl.setStyleSheet(f"color:{C['acc']};font-weight:600;font-size:12px;")
        lay.addWidget(self.vlbl)
        self._upd(self.slider.value())
        self.slider.valueChanged.connect(self._upd)

    def _upd(self, raw):
        v = raw / self._m
        t = f"{int(v)}{self._s}" if self._d == 0 else f"{v:.{self._d}f}{self._s}"
        self.vlbl.setText(t); self.valueChanged.emit(v)

    def value(self): return self.slider.value() / self._m
    def setValue(self, v): self.slider.setValue(int(v * self._m))


class SpinRow(QWidget):
    def __init__(self, label, lo, hi, default,
                 suffix="", tip="", label_w=130, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1); lay.setSpacing(5)
        lbl = QLabel(label); lbl.setFixedWidth(label_w)
        if tip: lbl.setToolTip(tip)
        lay.addWidget(lbl)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi); self.spin.setValue(default)
        if suffix: self.spin.setSuffix(f" {suffix}")
        lay.addWidget(self.spin, 1)

    def value(self): return self.spin.value()
    def setValue(self, v): self.spin.setValue(v)


class Sep(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background:{C['brd']};")


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 7 — DROP ZONE                                      ║
# ╚══════════════════════════════════════════════════════════════╝

class DropZone(QWidget):
    folder_dropped = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True); self.setFixedHeight(110)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hov = False; self._path = ""

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m, w, h = 4, self.width(), self.height()
        bg = QColor(C["bg_hov"] if self._hov else C["dz_bg"])
        pp = QPainterPath()
        pp.addRoundedRect(m, m, w-2*m, h-2*m, 11, 11)
        p.fillPath(pp, bg)
        pen = QPen(QColor(C["acc"]))
        pen.setWidth(3 if self._hov else 2)
        pen.setStyle(Qt.PenStyle.SolidLine if self._hov else Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(m, m, w-2*m, h-2*m, 11, 11)
        p.setPen(QColor(C["acc"] if self._hov else C["t2"]))
        p.setFont(QFont("Segoe UI Emoji", 24))
        p.drawText(0, 0, w, int(h*0.58),
                   Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignBottom, "📂")
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        if self._path:
            p.setPen(QColor(C["ok"]))
            txt = f"✔  {Path(self._path).name}"
        else:
            txt = "Kéo thư mục ảnh vào đây  —  hoặc nhấn để chọn"
        p.drawText(10, int(h*0.55), w-20, int(h*0.38),
                   Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignTop, txt)
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
# ║  SECTION 8 — THUMBNAIL GRID                                 ║
# ╚══════════════════════════════════════════════════════════════╝

class ThumbCard(QFrame):
    _ST = {
        "success":("✅ Xong",C["ok"]), "skipped":("⏭️ Bỏ qua",C["skip"]),
        "rejected":("📦 Loại",C["warn"]), "error":("❌ Lỗi",C["err"]),
        "processing":("⏳ ...",C["acc"]), "waiting":("⏳ Chờ",C["t_off"]),
    }
    def __init__(self, name="", parent=None):
        super().__init__(parent)
        self.setFixedSize(THUMB_PX+16, THUMB_PX+48)
        self._setb(C["brd"])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 2); lay.setSpacing(1)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img = QLabel()
        self.img.setFixedSize(THUMB_PX, THUMB_PX)
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setStyleSheet(f"background:{C['bg_in']};border-radius:5px;")
        lay.addWidget(self.img, 0, Qt.AlignmentFlag.AlignCenter)
        self.nlbl = QLabel(name[:20] if len(name)<=20 else name[:9]+"…"+name[-8:])
        self.nlbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nlbl.setMaximumWidth(THUMB_PX)
        self.nlbl.setStyleSheet(f"color:{C['t2']};font-size:9px;")
        lay.addWidget(self.nlbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.slbl = QLabel("")
        self.slbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.slbl, 0, Qt.AlignmentFlag.AlignCenter)

    def _setb(self, col):
        self.setStyleSheet(
            f"ThumbCard{{background:{C['th_bg']};border:2px solid {col};border-radius:9px;}}"
        )
    def set_px_path(self, path):
        px = QPixmap(str(path))
        if not px.isNull():
            self.img.setPixmap(px.scaled(
                THUMB_PX-4,THUMB_PX-4,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
    def set_px_pil(self, pil):
        im = pil.convert("RGB"); d = np.array(im)
        h, w, ch = d.shape
        qi = QImage(d.tobytes(), w, h, w*ch, QImage.Format.Format_RGB888)
        self.img.setPixmap(QPixmap.fromImage(qi).scaled(
            THUMB_PX-4,THUMB_PX-4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
    def set_status(self, status, detail=""):
        txt, col = self._ST.get(status, ("?", C["t2"]))
        self.slbl.setText(detail[:26] if detail else txt)
        self.slbl.setStyleSheet(f"color:{col};font-size:9px;font-weight:600;")
        bm = dict(success=C["ok"],error=C["err"],skipped=C["skip"],
                   rejected=C["warn"],processing=C["acc"])
        self._setb(bm.get(status, C["brd"]))


class ThumbGrid(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._box = QWidget()
        self._grid = QGridLayout(self._box)
        self._grid.setContentsMargins(4,4,4,4); self._grid.setSpacing(5)
        self.setWidget(self._box)
        self._cards: list[ThumbCard] = []; self._cols = 4

    def clear(self):
        for c in self._cards: self._grid.removeWidget(c); c.deleteLater()
        self._cards.clear()
    def populate(self, files):
        self.clear(); self._calc()
        for i, f in enumerate(files):
            c = ThumbCard(f.name); c.set_px_path(str(f))
            self._grid.addWidget(c, i//self._cols, i%self._cols, Qt.AlignmentFlag.AlignTop)
            self._cards.append(c)
    def card(self, i): return self._cards[i] if 0<=i<len(self._cards) else None
    def update_card(self, i, result):
        c = self.card(i)
        if not c: return
        c.set_status(result["status"], result.get("reason",""))
        if result["status"]=="success" and result.get("thumbnail"):
            c.set_px_pil(result["thumbnail"])
        self.ensureWidgetVisible(c, 50, 50)
    def _calc(self):
        w = self.viewport().width()-8; cw = THUMB_PX+22
        self._cols = max(2, min(w//cw, 10))
    def resizeEvent(self, e):
        super().resizeEvent(e); old = self._cols; self._calc()
        if old != self._cols and self._cards:
            for i, c in enumerate(self._cards):
                self._grid.removeWidget(c)
                self._grid.addWidget(c, i//self._cols, i%self._cols, Qt.AlignmentFlag.AlignTop)


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 9 — DASHBOARD                                      ║
# ╚══════════════════════════════════════════════════════════════╝

class Dashboard(QWidget):
    def __init__(self, sp: SysProfile, parent=None):
        super().__init__(parent)
        self.sp = sp
        self.setMinimumWidth(340); self.setMaximumWidth(395)

        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(4)

        ttl = QLabel(f"⚙️  Bảng điều khiển")
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ttl.setStyleSheet(f"font-size:15px;font-weight:700;color:{C['acc']};padding:3px 0;")
        root.addWidget(ttl)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_tab1()
        self._build_tab2()
        self._build_tab3()

    # ───────── Tab 1: Hệ thống ─────────
    def _build_tab1(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(6,6,6,6); lay.setSpacing(6)

        g1 = QGroupBox("💻 Phần cứng")
        g1l = QVBoxLayout(g1)
        info = QLabel(self.sp.text()); info.setWordWrap(True)
        info.setStyleSheet(
            f"color:{C['t2']};font-family:'Cascadia Code','Consolas',monospace;"
            f"font-size:10.5px;padding:3px;line-height:1.4;")
        g1l.addWidget(info)
        lay.addWidget(g1)

        g2 = QGroupBox("⚡ Hiệu năng")
        g2l = QVBoxLayout(g2); g2l.setSpacing(4)
        self.sl_cpu = SliderRow("Giới hạn CPU:", 5, 80, self.sp.cpu_target,
                                step=5, suffix="%", tip="CPU tối đa khi xử lý")
        g2l.addWidget(self.sl_cpu)
        self.sp_workers = SpinRow("Số luồng:", 1, self.sp.cores_p,
                                  self.sp.rec_workers, tip="Luồng xử lý")
        g2l.addWidget(self.sp_workers)
        self.lbl_rt = QLabel("CPU: --% │ RAM: --%")
        self.lbl_rt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_rt.setStyleSheet(
            f"color:{C['t2']};font-family:'Cascadia Code',monospace;font-size:11px;"
            f"padding:5px;background:{C['bg_in']};border:1px solid {C['brd']};border-radius:5px;")
        g2l.addWidget(self.lbl_rt)
        lay.addWidget(g2)
        lay.addStretch(1)
        self.tabs.addTab(w, "💻 Hệ thống")

    # ───────── Tab 2: Xử lý ─────────
    def _build_tab2(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6,6,6,6); lay.setSpacing(6)

        # ── Model ──
        g1 = QGroupBox("🤖 Mô hình AI")
        g1l = QVBoxLayout(g1); g1l.setSpacing(4)
        mrow = QWidget(); mr = QHBoxLayout(mrow)
        mr.setContentsMargins(0,0,0,0); mr.setSpacing(5)
        mr.addWidget(self._lbl("Mô hình:", 130))
        self.cb_model = QComboBox()
        self.cb_model.addItems(["u2net","u2net_human_seg","isnet-general-use"])
        self.cb_model.setToolTip(
            "u2net — Tốt nhất tổng hợp (khuyên dùng)\n"
            "u2net_human_seg — Tối ưu người\n"
            "isnet-general-use — Nhanh, nhẹ")
        mr.addWidget(self.cb_model, 1)
        g1l.addWidget(mrow)
        self.sp_mask = SpinRow("Ngưỡng mask:", 30, 250, 120,
                               tip="Thấp hơn = bắt nhiều chi tiết hơn (30-250)")
        g1l.addWidget(self.sp_mask)
        lay.addWidget(g1)

        # ── Padding ──
        g2 = QGroupBox("📐 Khoảng đệm (Padding)")
        g2l = QVBoxLayout(g2); g2l.setSpacing(4)

        note_pad = QLabel(
            "💡 Padding tính bằng pixel — giữ chủ thể sát nền nhất.\n"
            "Cạnh nào chủ thể đã sát biên ảnh sẽ tự bỏ padding.")
        note_pad.setWordWrap(True)
        note_pad.setStyleSheet(f"color:{C['t2']};font-size:10.5px;padding:2px;")
        g2l.addWidget(note_pad)
        g2l.addWidget(Sep())

        self.chk_uniform = QCheckBox("  Đệm đều 4 cạnh")
        self.chk_uniform.setChecked(True)
        self.chk_uniform.toggled.connect(self._toggle_pad)
        g2l.addWidget(self.chk_uniform)

        self.sp_pad_all = SpinRow("Tất cả cạnh:", 0, 100, 10, suffix="px")
        g2l.addWidget(self.sp_pad_all)

        self.sp_pad_t = SpinRow("Trên:", 0, 100, 10, suffix="px")
        self.sp_pad_b = SpinRow("Dưới:", 0, 100, 10, suffix="px")
        self.sp_pad_l = SpinRow("Trái:", 0, 100, 10, suffix="px")
        self.sp_pad_r = SpinRow("Phải:", 0, 100, 10, suffix="px")
        for s in [self.sp_pad_t, self.sp_pad_b, self.sp_pad_l, self.sp_pad_r]:
            g2l.addWidget(s); s.setVisible(False)

        g2l.addWidget(Sep())
        self.sl_edge = SliderRow(
            "Ngưỡng sát biên:", 0, 10, 3, step=1, suffix="%",
            tip="Cạnh subject cách biên ảnh ≤ X% → coi là sát biên")
        g2l.addWidget(self.sl_edge)
        lay.addWidget(g2)

        # ── Fill ──
        g3 = QGroupBox("🎯 Vị trí chủ thể")
        g3l = QVBoxLayout(g3); g3l.setSpacing(4)
        self.sl_fill = SliderRow("Chiếm canvas:", 50, 99, 92, suffix="%",
                                 tip="% diện tích chủ thể chiếm canvas đầu ra")
        g3l.addWidget(self.sl_fill)
        self.sl_maxup = SliderRow("Phóng to tối đa:", 1, 4, 2,
                                  step=0.5, suffix="x", decimals=1,
                                  tip="Giới hạn upscale (tránh mờ)")
        g3l.addWidget(self.sl_maxup)
        lay.addWidget(g3)
        lay.addStretch(1)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "🖼️ Xử lý")

    # ───────── Tab 3: Đầu ra ─────────
    def _build_tab3(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6,6,6,6); lay.setSpacing(6)

        # ── Frame ──
        g1 = QGroupBox("🖼️ Tỷ lệ khung (Frame)")
        g1l = QVBoxLayout(g1); g1l.setSpacing(5)

        frow = QWidget(); fr = QHBoxLayout(frow)
        fr.setContentsMargins(0,0,0,0); fr.setSpacing(5)
        fr.addWidget(self._lbl("Frame:", 130))
        self.cb_frame = QComboBox()
        for label, _, _ in FRAME_OPTIONS:
            self.cb_frame.addItem(label)
        self.cb_frame.currentIndexChanged.connect(self._on_frame)
        fr.addWidget(self.cb_frame, 1)
        g1l.addWidget(frow)
        g1l.addWidget(Sep())

        # Output size mode
        self.rad_auto = QRadioButton("  Tự động (giữ kích thước ảnh gốc)")
        self.rad_custom = QRadioButton("  Tuỳ chỉnh kích thước:")
        self.rad_auto.setChecked(True)
        self.rad_auto.toggled.connect(self._on_size_mode)

        self.size_group = QButtonGroup(self)
        self.size_group.addButton(self.rad_auto)
        self.size_group.addButton(self.rad_custom)

        g1l.addWidget(self.rad_auto)
        g1l.addWidget(self.rad_custom)

        # W × H row
        self.sz_widget = QWidget()
        sz = QHBoxLayout(self.sz_widget)
        sz.setContentsMargins(20, 2, 0, 2); sz.setSpacing(5)
        sz.addWidget(self._lbl("W:", 20))
        self.sp_w = QSpinBox()
        self.sp_w.setRange(256, 4096); self.sp_w.setValue(1024)
        self.sp_w.setSuffix(" px")
        sz.addWidget(self.sp_w, 1)
        xl = QLabel("×"); xl.setFixedWidth(14)
        xl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sz.addWidget(xl)
        sz.addWidget(self._lbl("H:", 20))
        self.sp_h = QSpinBox()
        self.sp_h.setRange(256, 4096); self.sp_h.setValue(1024)
        self.sp_h.setSuffix(" px")
        sz.addWidget(self.sp_h, 1)
        g1l.addWidget(self.sz_widget)
        self.sz_widget.setEnabled(False)  # default auto

        hint = QLabel(
            "ℹ️  Tự động: đầu ra = kích thước ảnh gốc.\n"
            "Khi chọn frame preset (1:1, 4:3...): tỷ lệ\n"
            "sẽ được tính dựa trên ảnh gốc, giữ đúng ratio.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C['t2']};font-size:10px;padding:2px;")
        g1l.addWidget(hint)
        lay.addWidget(g1)

        # ── Quality ──
        g2 = QGroupBox("📦 Chất lượng")
        g2l = QVBoxLayout(g2); g2l.setSpacing(5)
        self.sp_png = SpinRow("Nén PNG:", 0, 9, 9,
                              tip="0 = nhanh, 9 = nhỏ nhất (tất cả lossless)")
        g2l.addWidget(self.sp_png)
        self.chk_white = QCheckBox("  Nền trắng đầu ra")
        self.chk_white.setChecked(True)
        g2l.addWidget(self.chk_white)
        lay.addWidget(g2)

        # ── Filter ──
        g3 = QGroupBox("🗑️ Lọc & Phân loại")
        g3l = QVBoxLayout(g3); g3l.setSpacing(5)

        self.sp_min = SpinRow("Ngưỡng loại bỏ:", 0, 2048, 512, suffix="px",
                              tip="Loại ảnh khi CẢ HAI cạnh < giá trị này")
        g3l.addWidget(self.sp_min)

        note = QLabel(
            "📌 Chỉ loại khi CẢ HAI cạnh < ngưỡng.\n"
            "     (1 cạnh > ngưỡng → vẫn giữ)\n"
            "     File gốc được di chuyển, không xoá.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{C['warn']};font-size:10px;padding:2px;")
        g3l.addWidget(note)

        g3l.addWidget(Sep())

        # Folder names
        self.sp_out_name = self._text_row("Thư mục kết quả:", "Done")
        g3l.addWidget(self.sp_out_name)
        self.sp_rej_name = self._text_row("Thư mục loại bỏ:", "Loại bỏ")
        g3l.addWidget(self.sp_rej_name)

        lay.addWidget(g3)
        lay.addStretch(1)
        scroll.setWidget(inner)
        self.tabs.addTab(scroll, "📤 Đầu ra")

    # ─── Helpers ───
    @staticmethod
    def _lbl(text, w=130):
        l = QLabel(text); l.setFixedWidth(w); return l

    def _text_row(self, label, default):
        w = QWidget(); lay = QHBoxLayout(w)
        lay.setContentsMargins(0,1,0,1); lay.setSpacing(5)
        lay.addWidget(self._lbl(label, 130))
        from PyQt6.QtWidgets import QLineEdit
        le = QLineEdit(default)
        le.setStyleSheet(
            f"background:{C['bg_in']};color:{C['t1']};border:1px solid {C['brd']};"
            f"border-radius:5px;padding:5px 8px;font-size:12px;")
        lay.addWidget(le, 1)
        w._le = le
        return w

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
            self.sp_w.setValue(int(rw * sc))
            self.sp_h.setValue(int(rh * sc))

    def _on_size_mode(self, auto_checked):
        self.sz_widget.setEnabled(not auto_checked)

    def get_settings(self) -> CropSettings:
        uniform = self.chk_uniform.isChecked()
        auto = self.rad_auto.isChecked()
        return CropSettings(
            model_name=self.cb_model.currentText(),
            padding_px=self.sp_pad_all.value(),
            padding_top_px=self.sp_pad_t.value(),
            padding_bottom_px=self.sp_pad_b.value(),
            padding_left_px=self.sp_pad_l.value(),
            padding_right_px=self.sp_pad_r.value(),
            use_uniform_padding=uniform,
            edge_threshold_pct=self.sl_edge.value(),
            frame_index=self.cb_frame.currentIndex(),
            target_width=self.sp_w.value() if not auto else 0,
            target_height=self.sp_h.value() if not auto else 0,
            png_compress=self.sp_png.value(),
            min_size_px=self.sp_min.value(),
            subject_fill=self.sl_fill.value(),
            mask_threshold=self.sp_mask.value(),
            white_bg=self.chk_white.isChecked(),
            max_upscale=self.sl_maxup.value(),
            auto_output_size=auto,
            output_folder=self.sp_out_name._le.text().strip() or "Done",
            rejected_folder=self.sp_rej_name._le.text().strip() or "Loại bỏ",
        )

    def cpu_limit(self): return self.sl_cpu.value()

    def update_sysload(self, cpu, ram):
        col = C["ok"] if cpu<=40 else (C["warn"] if cpu<=70 else C["err"])
        self.lbl_rt.setText(f"CPU: {cpu:.0f}%  │  RAM: {ram:.0f}%")
        self.lbl_rt.setStyleSheet(
            f"color:{col};font-family:'Cascadia Code',monospace;font-size:11px;"
            f"padding:5px;background:{C['bg_in']};border:1px solid {C['brd']};border-radius:5px;")

    def reset_defaults(self):
        self.cb_model.setCurrentIndex(0)
        self.sp_mask.setValue(120)
        self.chk_uniform.setChecked(True)
        self.sp_pad_all.setValue(10)
        for s in [self.sp_pad_t,self.sp_pad_b,self.sp_pad_l,self.sp_pad_r]: s.setValue(10)
        self.sl_edge.setValue(3)
        self.sl_fill.setValue(92); self.sl_maxup.setValue(2)
        self.cb_frame.setCurrentIndex(0)
        self.rad_auto.setChecked(True)
        self.sp_w.setValue(1024); self.sp_h.setValue(1024)
        self.sp_png.setValue(9); self.sp_min.setValue(512)
        self.chk_white.setChecked(True)
        self.sl_cpu.setValue(20); self.sp_workers.setValue(self.sp.rec_workers)
        self.sp_out_name._le.setText("Done")
        self.sp_rej_name._le.setText("Loại bỏ")


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 10 — MAIN WINDOW                                   ║
# ╚══════════════════════════════════════════════════════════════╝
#
# ┌─────────────────┬────────────────────────────────────────────┐
# │                 │  ┌── 📂 DROP ZONE ──────────────────────┐ │
# │   DASHBOARD     │  └─────────────────────────────────────────┘ │
# │  ┌───────────┐  │  [▶ Bắt đầu] [⏸] [🛑] [🔄 Reset]  N ảnh │
# │  │💻 Hệ thống│  │  ████████████░░░  45%   12/27            │
# │  │🖼 Xử lý  │  │  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐   │
# │  │📤 Đầu ra  │  │  │🖼│ │🖼│ │🖼│ │🖼│ │🖼│ │🖼│ │🖼│   │
# │  └───────────┘  │  └──┘ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘   │
# │                 │  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐        │
# │                 │  │🖼│ │🖼│ │🖼│ │🖼│ │🖼│ │🖼│        │
# │                 │  └──┘ └──┘ └──┘ └──┘ └──┘ └──┘        │
# │                 ├────────────────────────────────────────────┤
# │                 │  📋 Log  (thu nhỏ — kéo lên để xem thêm)│
# └─────────────────┴────────────────────────────────────────────┘

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"🔲 {APP_TITLE} — Cắt chủ thể thông minh")
        self.setMinimumSize(1060, 660)
        self.resize(1340, 780)

        self.sp = detect_system(20.0)
        self.worker = BatchWorker()
        self.worker.sig_progress.connect(self._on_progress)
        self.worker.sig_file_start.connect(self._on_file_start)
        self.worker.sig_finished.connect(self._on_finished)
        self.worker.sig_log.connect(self._on_log)
        self.worker.sig_sysload.connect(self._on_sysload)
        self._busy = False
        self.setStyleSheet(build_qss())
        self._build()

    def _build(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(8,8,8,8); main.setSpacing(8)

        # ── LEFT ──
        self.dash = Dashboard(self.sp)
        main.addWidget(self.dash)

        # ── RIGHT ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)

        # Drop zone
        self.dz = DropZone()
        self.dz.folder_dropped.connect(self._on_folder)
        rl.addWidget(self.dz)

        # Action bar
        ab = QWidget()
        al = QHBoxLayout(ab)
        al.setContentsMargins(0,0,0,0); al.setSpacing(6)

        self.btn_start = QPushButton("▶  Bắt đầu")
        self.btn_start.setProperty("class","primary")
        self.btn_start.setMinimumHeight(34); self.btn_start.setMinimumWidth(120)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_start.setEnabled(False)

        self.btn_pause = QPushButton("⏸  Dừng")
        self.btn_pause.setMinimumHeight(34)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_pause.setEnabled(False)

        self.btn_cancel = QPushButton("🛑  Huỷ")
        self.btn_cancel.setProperty("class","danger")
        self.btn_cancel.setMinimumHeight(34)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)

        self.btn_reset = QPushButton("🔄  Làm mới")
        self.btn_reset.setProperty("class","warn")
        self.btn_reset.setMinimumHeight(34)
        self.btn_reset.clicked.connect(self._on_reset)

        al.addWidget(self.btn_start)
        al.addWidget(self.btn_pause)
        al.addWidget(self.btn_cancel)
        al.addWidget(self.btn_reset)
        al.addStretch(1)

        self.lbl_count = QLabel("📁 Chưa chọn thư mục")
        self.lbl_count.setStyleSheet(f"color:{C['t2']};font-size:12px;")
        al.addWidget(self.lbl_count)
        rl.addWidget(ab)

        # Progress
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m ảnh  —  %p%")
        rl.addWidget(self.progress)

        # Splitter: thumbnails (lớn) + log (nhỏ)
        split = QSplitter(Qt.Orientation.Vertical)
        split.setHandleWidth(4)

        self.thumbs = ThumbGrid()
        split.addWidget(self.thumbs)

        log_w = QWidget()
        ll = QVBoxLayout(log_w)
        ll.setContentsMargins(0,0,0,0); ll.setSpacing(2)
        lh = QLabel("📋 Nhật ký")
        lh.setStyleSheet(f"color:{C['acc']};font-weight:700;font-size:12px;")
        ll.addWidget(lh)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Nhật ký hiển thị khi bắt đầu xử lý...")
        ll.addWidget(self.log)
        split.addWidget(log_w)

        # Thumbnail chiếm 80%, log 20%
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        # Set initial sizes (thumbnails lớn, log nhỏ)
        split.setSizes([500, 100])

        rl.addWidget(split, 1)
        main.addWidget(right, 1)

    # ═══════════════ SLOTS ═══════════════

    def _on_folder(self, path):
        self.worker.set_folder(path)
        n = len(self.worker.file_list)
        self.lbl_count.setText(f"📁 {n} ảnh" if n else "⚠️ Không có ảnh")
        self.btn_start.setEnabled(n > 0)
        self.progress.setMaximum(max(n, 1)); self.progress.setValue(0)
        if n:
            self.thumbs.populate(self.worker.file_list)
            self._on_log(
                f"📂 Thư mục: {path}\n📁 {n} ảnh hỗ trợ "
                f"({', '.join(sorted(SUPPORTED_EXT))})")
        else:
            self.thumbs.clear()

    def _on_start(self):
        if self._busy: return
        self.worker.settings = self.dash.get_settings()
        self.worker.cpu_limit = self.dash.cpu_limit()
        self.progress.setValue(0); self.log.clear()
        self._set_busy(True); self.worker.start()

    def _on_pause(self):
        if not self._busy: return
        if "Dừng" in self.btn_pause.text():
            self.worker.pause()
            self.btn_pause.setText("▶  Tiếp tục")
            self.btn_pause.setProperty("class","primary")
            self._on_log("⏸️  Đã tạm dừng")
        else:
            self.worker.resume()
            self.btn_pause.setText("⏸  Dừng")
            self.btn_pause.setProperty("class","")
            self._on_log("▶️  Tiếp tục")
        self.btn_pause.style().unpolish(self.btn_pause)
        self.btn_pause.style().polish(self.btn_pause)

    def _on_cancel(self):
        if not self._busy: return
        r = QMessageBox.question(
            self, "Xác nhận huỷ",
            "Huỷ bỏ? Ảnh đã xong vẫn được giữ.",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            self.worker.cancel()

    def _on_reset(self):
        if self._busy:
            r = QMessageBox.question(
                self, "Đang xử lý",
                "Đang chạy! Huỷ và làm mới toàn bộ?",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes: return
            self.worker.cancel(); self.worker.wait(3000)
        self.worker.release_resources()
        self.thumbs.clear(); self.log.clear()
        self.progress.setValue(0); self.progress.setMaximum(1)
        self.dz.reset()
        self.lbl_count.setText("📁 Chưa chọn thư mục")
        self.btn_start.setEnabled(False)
        self.dash.reset_defaults()
        self._set_busy(False)
        gc.collect()
        self._on_log("🔄 Đã làm mới — Bộ nhớ đã giải phóng")
        self.dash.update_sysload(
            psutil.cpu_percent(interval=0.1),
            psutil.virtual_memory().percent)

    def _on_progress(self, cur, total, result):
        self.progress.setValue(cur)
        self.thumbs.update_card(cur - 1, result)

    def _on_file_start(self, idx, name):
        c = self.thumbs.card(idx)
        if c: c.set_status("processing")

    def _on_finished(self, results):
        self._set_busy(False)
        s = self.dash.get_settings()
        ok = sum(1 for r in results if r["status"]=="success")
        rej = sum(1 for r in results if r["status"]=="rejected")
        msg = f"✅ Đã xử lý xong!\n\nThành công: {ok} ảnh → '{s.output_folder}'\n"
        if rej: msg += f"Loại bỏ: {rej} ảnh → '{s.rejected_folder}'\n"
        msg += f"\nTổng: {len(results)} ảnh"
        QMessageBox.information(self, "Hoàn tất", msg)

    def _on_log(self, msg):
        self.log.append(msg)
        c = self.log.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(c)

    def _on_sysload(self, cpu, ram):
        self.dash.update_sysload(cpu, ram)

    def _set_busy(self, busy):
        self._busy = busy
        self.btn_start.setEnabled(not busy)
        self.btn_pause.setEnabled(busy)
        self.btn_cancel.setEnabled(busy)
        self.dz.setEnabled(not busy)
        self.btn_reset.setEnabled(True)
        if not busy: self.btn_pause.setText("⏸  Dừng")

    def closeEvent(self, e):
        if self._busy: self.worker.cancel(); self.worker.wait(3000)
        self.worker.release_resources(); gc.collect(); e.accept()


# ╔══════════════════════════════════════════════════════════════╗
# ║  SECTION 11 — RUN                                           ║
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