# Bản đồ dịch ngược và vá nóng Antigravity Language Server

Tài liệu định hướng cấu trúc binary cho AI tương lai khi nâng cấp hoặc vá lỗi. Bản 2.31.0 chỉ vá giới hạn đầu ra và ngữ cảnh, không can thiệp danh mục model.

## Đường dẫn thực thi và cơ chế kích hoạt

| Môi trường | Đường dẫn file thực thi | Cơ chế tự động chạy và làm tươi |
| :--- | :--- | :--- |
| WSL và Linux | ~/.antigravity-server/bin/*/language_server | Systemd user theo dõi thư mục bin và daemon để vá đĩa cứng cùng bộ nhớ RAM. |
| Windows thuần | %LOCALAPPDATA%/Programs/Antigravity/resources/bin/language_server.exe | Shortcut Startup chạy script Python với cờ --watch để vá file trước khi khởi động giao diện và vá lại sau mỗi lần app tự cập nhật. |
| Giao diện UI | resources/app/out/vs/workbench/workbench.desktop.main.js | Không vá, giữ nguyên bản gốc của Google. |

## Bảng điểm vá giới hạn đầu ra và ngữ cảnh

| Hàm mục tiêu | Giá trị gốc | Giá trị sau khi vá | Cách dò tìm lại khi đổi phiên bản |
| :--- | :--- | :--- | :--- |
| command.TruncateOutput | 8 KiB tức 0x2000 | 42 KiB tức 0xa800 | Tìm lệnh nạp 0x2000 vào esi rồi cmovne ngay trước lệnh gọi hàm cắt chuỗi, bản 2.31 dùng nhánh mặc định thay cho nhánh vô điều kiện. |
| utils.terminalDetailsFromScopeItem và serializers | 8 KiB tức 0x2000 | 42 KiB tức 0xa800 | Tìm hằng số nạp thanh ghi 0x2000 đi kèm hằng số kiểu cắt chuỗi bằng 2 ngay trước lệnh gọi hàm cắt chuỗi. |
| handlers.McpToolHandler.Handle | 10 KiB tức 0x2800 | 128 KiB tức 0x20000 | Tìm nhánh đọc giới hạn byte đầu ra của công cụ MCP tại độ lệch 0x10 và ghi đè thanh ghi r8d thành 0x20000. |
| tooldecorators.truncateOutput | 10 KB tức 0x2800 | 129 KiB tức 0x20400 | Dùng biểu thức chính quy khớp lệnh lưu rax và rdi xuống ngăn xếp ngay trước phép so sánh độ dài rcx và rbx. |
| customizations.readGlobalRules, parseRuleFile, convertSkillPath | 24 KB tức 0x5dc0 | 128 KiB tức 0x20000 | Tìm hằng số nạp 0x5dc0 vào thanh ghi ecx tại các hàm nạp luật toàn cục và kỹ năng. |
| customizations.computeTruncatedCustomizations và GetTokenBase | 20000 token tức 0x4e20 | 131072 token tức 0x20000 | Tìm hằng số nạp 0x4e20 làm ngân sách token tối đa cho tập luật và kỹ năng, bản 2.31 lưu kết quả ở rsp+0x4c. |
| config.GetDefaultConversationalCascadeConfig và các hàm đọc file | 800 dòng và 45 KiB | 2000 dòng và 68 KiB | Tìm hằng số 0x320 tức 800 dòng và 0xb400 tức 46080 byte trong cấu hình mặc định cùng bộ chuyển đổi công cụ đọc file. |
| integration.CreateSerializer | 16384 token | 44544 token | Tìm hằng số 0x4000 trong cấu hình bước tin nhắn của serializer. |

## Vì sao đã bỏ hẳn phần mở khóa Gemini 4 Argon

| Sự kiện | Chi tiết |
| :--- | :--- |
| Bản 2.30 trở về trước | Patch cắt hậu tố tên model dựa vào chuỗi tại ModelInfo+0x38 và độ dài tại 0x40, chạy được. |
| Bản 2.31.0 | staticCatalog.GetModelInfoFromKey đổi sang tra cứu map[int32], đọc [rbx+0x38] thành con trỏ rác nên language server chết với 0xC0000005, app reload liên tục mỗi 25 đến 40 giây. |
| Quyết định | Toàn bộ mã Argon đã xóa khỏi script, không để lại cờ bật tắt để tránh bật nhầm. Muốn thêm lại phải dịch ngược lại cả chuỗi bốn điểm neo trước. |

## Quy trình khi Antigravity lên phiên bản mới

| Bước | Việc cần làm |
| :--- | :--- |
| 1 | Chạy check_exact.py trên binary mới để biết mẫu byte nào còn khớp, mẫu bắt buộc không khớp là phải dịch lại. |
| 2 | Chạy script trên một bản copy trong %TEMP% rồi so số vùng lệch với bản gốc, kỳ vọng đúng 16 vùng và 64 byte. |
| 3 | Chỉ chép đè lên binary thật sau khi số vùng lệch khớp, rồi theo dõi language_server.log ít nhất 2 phút để chắc không có crash. |
