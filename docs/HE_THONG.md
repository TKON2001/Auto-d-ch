# Rà soát hệ thống — 2026-10-03

## Luồng xử lý

Video trên máy / Excel → nhập nguồn → FFprobe → fingerprint nguồn → cache OCR hoặc quét OCR → gom chữ theo thời gian và vùng → dịch có ngữ cảnh, lưu từng phần → bố trí phụ đề → ASS → FFmpeg → dự án chỉnh sửa.

Chỉnh phụ đề → kiểm tra thời gian, tọa độ và nội dung → bố trí lại → FFmpeg. Xuất lại không cần OCR hay gọi API dịch.

| Thành phần | Trách nhiệm và kết quả rà soát |
| --- | --- |
| [video_translator.py](../video_translator.py) | Điều phối CLI/GUI và pipeline. Sửa lỗi thụt lề chặn import/khởi động; dùng tham số OCR thống nhất cho scan, grouping và cache. |
| [ocr_core.py](../ocr_core.py), [adaptive_ocr.py](../adaptive_ocr.py) | Dò chữ toàn khung, theo dõi vùng, đọc lại khi ảnh thay đổi. Gom mẫu chỉ xét nhóm còn hiệu lực theo thời gian; bỏ phép cắt danh sách lịch sử không cần thiết. Kiểm tra FPS và ROI trước khi nạp model. |
| [ocr_loader.py](../ocr_loader.py) | Giữ model trong phiên, khóa khởi tạo để tránh nạp trùng. Giữ cơ chế này. |
| [ocr_cache.py](../ocr_cache.py) | Khóa cache xét SHA nguồn, kích thước, thời lượng, chu kỳ lấy mẫu, ROI và phiên bản chính sách. Checksum dữ liệu phát hiện hai file cache không khớp khi bị ngắt giữa chừng. |
| [translation_core.py](../translation_core.py) | Giữ dịch theo ID, ngữ cảnh, retry và khôi phục từng phần. Cache JSON sai kiểu được bỏ qua; dòng chỉ có khoảng trắng không còn được coi là dịch xong. |
| [storage.py](../storage.py) | Ghi JSON vào file tạm riêng, flush/fsync rồi thay thế. Manifest, dự án và cache dùng chung; file cũ được giữ nếu thay thế thất bại. |
| [subtitle_layout.py](../subtitle_layout.py) | Cache font có giới hạn; xét vùng chữ trong khoảng thời gian liên quan thay vì quét mọi cue cho mỗi dòng. Trả kết quả theo thứ tự đầu vào. |
| [subtitle_editor.py](../subtitle_editor.py), [editor_core.py](../editor_core.py) | Sửa tên file dự án khi nạp bản dịch; tránh phát sự kiện chọn dòng khi bảng đang được điền; lưu dự án bằng ghi thay thế. |
| [pause_control.py](../pause_control.py) | Tạm dừng lặp không suspend thêm lần nữa; chỉ resume tiến trình đã suspend. Hạn chế mắc kẹt tiến trình trên Windows. |
| [resource_limits.py](../resource_limits.py) | OCR/render dùng tối đa một nửa số CPU logic, giới hạn 8 luồng; tối thiểu 1. Đây là lựa chọn ưu tiên độ phản hồi desktop, cần đo thêm trên video thật để điều chỉnh. |
| [render_core.py](../render_core.py) | Giữ render vào file tạm rồi thay thế, thử NVENC và fallback x264. Kiểm thử tích hợp sử dụng x264 thật. |
| [batch_core.py](../batch_core.py), [batch_translation.py](../batch_translation.py), [batch_gui.py](../batch_gui.py) | Giữ thứ tự Excel, manifest tiếp tục, hash nguồn/đầu ra và cô lập lỗi từng video. Manifest chuyển sang ghi JSON dùng chung. |
| [components.py](../components.py), [launcher.py](../launcher.py) | Cơ chế xác thực FFmpeg/model được giữ. Bộ test giả lập FFmpeg đã được chỉnh phù hợp hợp đồng trả đường dẫn và khác biệt Windows/POSIX. |
| [video_player.py](../video_player.py) | Giữ QMediaPlayer phát nguồn và preview phụ đề; không thay decoder hay backend âm thanh. |

## Dọn thư mục

Đã đưa kiểm thử vào [tests](../tests/), tài liệu cũ vào thư mục này, CSV mẫu vào [examples](../examples/). Giữ module chạy ở vị trí cũ để không phá import, PyInstaller và tài nguyên đi kèm. Thêm README, lệnh chạy test và lệnh chạy từ thư mục ngoài.

Bản nguồn trước khi sửa nằm trong [backups](../../backups/). Không xóa model, FFmpeg, môi trường thư viện hay dữ liệu người dùng. `.runtime` hiện trỏ tới Python 3.12 không còn tồn tại; lệnh chạy đã biết bỏ qua và dùng `.venv` đang hoạt động. Không di chuyển môi trường ảo vì chúng chứa đường dẫn tuyệt đối.

## Kiểm chứng

Lần chạy trước chỉnh sửa phát hiện lỗi cú pháp chặn nhiều module, cùng các test ROI, CPU và mock FFmpeg đã lệch hành vi hiện tại. Sửa test ROI bằng cách truyền ROI cụ thể, giữ test riêng xác nhận mặc định quét toàn khung. Test đọc Unicode chỉ định UTF-8 thay vì phụ thuộc code page của Windows.

Bổ sung hồi quy cho cache đổi FPS/ROI, cặp cache ghi dở, JSON sai kiểu, ghi file bị khóa, tạm dừng lặp, khoảng cách lớn giữa hai câu giống nhau, tham số OCR không hợp lệ và render có âm thanh.

Kết quả cuối: **90/90 kiểm thử đạt**, khoảng 5,6 giây trên môi trường hiện tại. Các cảnh báo `moov atom not found` xuất phát từ file giả trong test GUI; test render riêng tạo MP4 hợp lệ và kiểm chứng bằng FFprobe.

| Phép đo tổng hợp, kết quả trước/sau giống nhau | Trước | Sau |
| --- | --- | --- |
| Gom 6.000 mẫu OCR | 1,0850 giây | 0,0248 giây |
| Bố trí 1.000 cue không chồng thời gian | 1,4382 giây | 0,0361 giây |

Đây là một lượt đo trên máy hiện tại, không phải cam kết tăng tốc OCR, GPU hay toàn bộ video theo cùng tỷ lệ.

Phép đo [benchmark_pipeline.py](../tests/benchmark_pipeline.py) đọc mã nguồn từ bản ZIP sao lưu do đợt làm việc này tạo, so sánh kết quả trước/sau rồi đo thời gian. Chỉ chạy với ZIP nguồn tin cậy vì phép đo thực thi mã Python trong ZIP.

## Giới hạn còn lại

- Kiểm thử OCR dùng ảnh/video tổng hợp và reader giả; chưa đo độ chính xác OCR thật hay CUDA trên video người dùng.
- Chưa gọi API dịch thật, đo chất lượng dịch hay tốc độ tải mạng. Hiệu năng gom/bố trí không đại diện tổng thời gian xử lý video.
- GUI chính vẫn tập trung trong module điều phối; một số thao tác nạp Excel, probe và lưu dự án vẫn chạy đồng bộ. Dữ liệu rất lớn có thể gây khựng ở các thao tác này.
- Luồng URL ở CLI tải nguồn vào thư mục tạm; dự án chỉnh sửa lưu đường dẫn nguồn đó nên không dùng lại được sau khi thư mục tạm bị xóa. Để chỉnh sửa lâu dài, dùng video cục bộ hoặc luồng nhập Excel lưu nguồn trong thư mục dự án.
- Cache OCR chính sách cũ bị vô hiệu hóa và sẽ quét lại một lần. File cache cũ không bị xóa hàng loạt.
- Chưa đóng gói lại EXE; thay đổi áp dụng cho bản mã nguồn chạy bằng các lệnh BAT.
