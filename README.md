<div align="center">

# 🔲 Smart Subject Cropper

**Công cụ tự động crop ảnh thông minh dựa trên AI — giữ nguyên chủ thể, loại bỏ nền thừa**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt6/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com)

[Tính năng](#-tính-năng) • [Cài đặt](#-cài-đặt) • [Sử dụng](#-sử-dụng) • [Cấu hình](#%EF%B8%8F-cấu-hình) • [FAQ](#-faq)

</div>

---

## 📋 Giới thiệu

**Smart Subject Cropper** là công cụ xử lý ảnh hàng loạt sử dụng AI để:
- Tự động nhận diện chủ thể chính trong ảnh
- Crop thông minh giữ nguyên tỷ lệ ảnh gốc
- Loại bỏ ảnh/chủ thể quá nhỏ (< 600px)
- Xử lý hàng nghìn ảnh với hiệu năng tối ưu

**Hoàn hảo cho:** Photographer, Designer, E-commerce, Dataset preparation cho AI/ML.

---

## ✨ Tính năng

### 🤖 AI-Powered
- **Nhận diện chủ thể** bằng model U2-Net, ISNet
- **Tách nền chính xác** với rembg
- **Phát hiện cạnh sát biên** — tự động giữ bố cục gốc

### 🖼️ Smart Crop
- **Auto-Frame** — tự động giữ tỷ lệ ảnh gốc (3:2, 4:3, 16:9...)
- **Subject Fill** — điều chỉnh % chủ thể chiếm khung
- **Chỉ crop pixel gốc** — không scale, không tạo nền giả
- **Padding thông minh** — đệm đều hoặc riêng 4 cạnh

### ⚡ Hiệu năng
- **Adaptive Speed** — tự điều chỉnh tốc độ theo CPU/RAM
- **Batch processing** — xử lý hàng loạt với progress bar
- **Quét subfolder** — mỗi thư mục con có kết quả riêng
- **Tiết kiệm tài nguyên** — giới hạn CPU, tự GC

### 🎨 Giao diện
- **Dark theme** hiện đại
- **Drag & Drop** thư mục
- **Thumbnail grid** xem trước kết quả
- **Real-time log** chi tiết

---

## 📦 Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|------------|---------|
| **OS** | Windows 10/11 (64-bit) |
| **Python** | 3.12.x |
| **RAM** | ≥ 8GB (khuyến nghị 16GB) |
| **GPU** | Không bắt buộc (có NVIDIA CUDA sẽ nhanh hơn) |
| **Disk** | ~2GB cho môi trường + thư viện |

---

## 🚀 Cài đặt

### Cách 1: Tự động (Khuyến nghị)

1. **Tải về** hoặc clone repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/smart-subject-cropper.git
   cd smart-subject-cropper
   ```

2. **Double-click** `start.bat`

   Script sẽ tự động:
   - ✅ Kiểm tra Python 3.12
   - ✅ Tạo môi trường ảo (nếu chưa có)
   - ✅ Cài đặt thư viện (nếu thiếu)
   - ✅ Chạy ứng dụng

### Cách 2: Thủ công

```bash
git clone https://github.com/YOUR_USERNAME/smart-subject-cropper.git
cd smart-subject-cropper
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## 📖 Sử dụng

### Bắt đầu nhanh

1. **Mở ứng dụng** — double-click `start.bat`
2. **Kéo thả thư mục ảnh** vào vùng Drop Zone (hoặc click để chọn)
3. **Nhấn "▶ Bắt đầu"**
4. **Kết quả** nằm trong thư mục `Done/` cùng cấp

### Cấu trúc output

```
📁 Ảnh_của_bạn/
├── image1.jpg              ← Ảnh gốc
├── image2.png              ← Ảnh gốc
├── 📁 Done/                ← ✅ Kết quả crop
│   ├── image1.png
│   └── image2.png
└── 📁 Loại bỏ/             ← 📦 Ảnh bị loại (quá nhỏ)
    └── image3.png
```

### Quét subfolder

Bật **"Quét cả thư mục con"** trong tab Đầu ra:

```
📁 Root/
├── 📁 Category_A/
│   ├── a1.jpg
│   └── 📁 Done/         ← Kết quả riêng
└── 📁 Category_B/
    ├── b1.jpg
    └── 📁 Done/         ← Kết quả riêng
```

---

## ⚙️ Cấu hình

### Tab Crop

| Tuỳ chọn | Mô tả | Mặc định |
|----------|-------|----------|
| **Mô hình AI** | u2net, u2net_human_seg, isnet-general-use | u2net |
| **Ngưỡng mask** | Thấp = nhiều chi tiết, Cao = ít chi tiết | 120 |
| **Padding** | Khoảng đệm xung quanh chủ thể (px) | 10 |
| **Subject chiếm** | % chủ thể chiếm vùng crop | 92% |
| **Giới hạn CPU** | Ngưỡng % CPU tối đa | 20% |
| **Adaptive Speed** | Tự điều chỉnh tốc độ theo tải | ✅ Bật |

### Tab Đầu ra

| Tuỳ chọn | Mô tả | Mặc định |
|----------|-------|----------|
| **Quét subfolder** | Xử lý đệ quy thư mục con | ❌ Tắt |
| **Nén PNG** | Mức nén 0-9 (9 = nhỏ nhất) | 9 |
| **Loại nếu subject <** | Ngưỡng kích thước tối thiểu | 600px |
| **Thư mục kết quả** | Tên folder output | Done |
| **Thư mục loại bỏ** | Tên folder ảnh bị loại | Loại bỏ |

### File cấu hình

Cài đặt tự động lưu vào `cropper_settings.json` cùng thư mục.

---

## 📁 Cấu trúc dự án

```
smart-subject-cropper/
├── 📄 start.bat              # Launcher tự động
├── 📄 main.py                # Source code chính
├── 📄 requirements.txt       # Danh sách thư viện
├── 📄 README.md              # Tài liệu này
├── 📄 LICENSE                # MIT License
├── 📁 .venv/                 # Môi trường ảo (tự tạo)
└── 📄 cropper_settings.json  # Cấu hình (tự tạo)
```

---

## 🔧 Xử lý sự cố

### Lỗi "Không tìm thấy Python 3.12"

1. Tải Python 3.12 từ [python.org](https://www.python.org/downloads/)
2. Khi cài, **tick ✅ "Add Python to PATH"**
3. Restart máy và thử lại

### Lỗi "Cài thư viện thất bại"

```bash
rmdir /s /q .venv
start.bat
```

### App bị treo, không tắt được

1. Đóng cửa sổ cmd
2. Xoá file `.venv\.running` nếu còn
3. Mở lại `start.bat`

### Cài thủ công nếu start.bat lỗi

```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## ❓ FAQ

<details>
<summary><b>Q: Hỗ trợ định dạng ảnh nào?</b></summary>

PNG, JPG, JPEG, WebP, BMP, TIFF
</details>

<details>
<summary><b>Q: Có thể xử lý bao nhiêu ảnh cùng lúc?</b></summary>

Không giới hạn. Đã test với 10,000+ ảnh. Adaptive Speed tự điều chỉnh để không quá tải hệ thống.
</details>

<details>
<summary><b>Q: Ảnh output có bị giảm chất lượng không?</b></summary>

Không. Tool chỉ crop pixel gốc, không resize hay nén lossy. Output luôn là PNG.
</details>

<details>
<summary><b>Q: GPU có cần thiết không?</b></summary>

Không bắt buộc. Có NVIDIA GPU + CUDA sẽ nhanh hơn ~2-3x, nhưng CPU vẫn chạy tốt.
</details>

<details>
<summary><b>Q: Tại sao ảnh bị chuyển vào "Loại bỏ"?</b></summary>

3 lý do:
1. Ảnh gốc có cạnh lớn nhất < 600px
2. Chủ thể phát hiện được có cạnh lớn nhất < 600px
3. Vùng crop cuối cùng có cạnh lớn nhất < 600px

Điều chỉnh ngưỡng trong tab Đầu ra nếu cần.
</details>

<details>
<summary><b>Q: Làm sao để crop vuông 1:1?</b></summary>

Hiện tại tool auto-frame theo tỷ lệ ảnh gốc. Nếu ảnh gốc là 1:1 thì output cũng 1:1.
</details>

---

## 📊 Benchmark

| Số ảnh | Kích thước TB | Thời gian | Máy test |
|--------|---------------|-----------|----------|
| 100 | 2000×1500 | ~3 phút | i7-10700, 16GB, no GPU |
| 1,000 | 1500×1000 | ~25 phút | i7-10700, 16GB, no GPU |
| 100 | 2000×1500 | ~1 phút | i7-10700, 16GB, RTX 3060 |

---

## 🤝 Đóng góp

Mọi đóng góp đều được chào đón!

1. Fork repository
2. Tạo branch (`git checkout -b feature/TinhNangMoi`)
3. Commit (`git commit -m 'Thêm tính năng XYZ'`)
4. Push (`git push origin feature/TinhNangMoi`)
5. Tạo Pull Request

---

## 📜 License

[MIT License](LICENSE) — Tự do sử dụng, chỉnh sửa, phân phối.

---

## 🙏 Credits

- [rembg](https://github.com/danielgatis/rembg) — Background removal
- [U2-Net](https://github.com/xuebinqin/U-2-Net) — Salient object detection
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — GUI framework
- [OpenCV](https://opencv.org/) — Image processing

---

<div align="center">

**Nếu thấy hữu ích, hãy ⭐ star repo này!**

Made with ❤️

</div>
