# Frame Video Translator

Dịch phụ đề tiếng Trung có sẵn trong hình sang tiếng Việt, giữ âm thanh gốc và cho phép chỉnh phụ đề sau khi dịch.

## Khởi chạy

Chạy [RUN_APP.bat](RUN_APP.bat). Có thể dùng [nút chạy ở thư mục ngoài](../RUN_APP.bat).
Ứng dụng thử môi trường `.runtime` trước, sau đó thử `.venv` ở thư mục ngoài; môi trường có Python hỏng sẽ được bỏ qua.
Máy chưa cài thư viện dùng [START_WINDOWS.bat](START_WINDOWS.bat).

API key nhập trong ứng dụng. Các kiểm thử tự động không gọi API dịch thật.

## Thư mục

| Vị trí | Nội dung |
| --- | --- |
| Các module Python ở thư mục này | Mã chạy ứng dụng; giữ đường dẫn tương thích với bản đóng gói |
| [tests](tests/) | Kiểm thử hồi quy và phép đo hiệu năng |
| [docs](docs/) | Hướng dẫn, lịch sử phiên bản, báo cáo rà soát |
| [examples](examples/) | CSV mẫu nhập video |
| [models](models/) | Trọng số OCR có sẵn |
| [ffmpeg](ffmpeg/) | FFmpeg, ffprobe và giấy phép đi kèm |
| [backups](../backups/) | Bản sao nguồn trước khi dọn dẹp |

## Kiểm tra

Chạy [RUN_TESTS.bat](RUN_TESTS.bat), hoặc tại thư mục ứng dụng:

```powershell
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kiểm thử giao diện dùng chế độ offscreen. Kiểm thử render tạo video ngắn trong thư mục tạm và kiểm tra âm thanh bằng FFprobe; nếu thiếu FFmpeg thì test này được bỏ qua.

Xem [báo cáo hệ thống](docs/HE_THONG.md) để biết thay đổi, cách kiểm chứng và giới hạn.
