---
name: antigravity-auto-execute
description: >-
  Inspect, enable, disable, or troubleshoot full auto-execution (EAGER auto-run mode without confirmation dialogs or Blocked waiting states) for terminal commands, scripts, and background workflows in Google Antigravity IDE and Antigravity 2.0. Use when the user asks to disable execution prompts, stop the agent from asking to submit commands, configure CASCADE_COMMANDS_AUTO_EXECUTION_EAGER, or make all agent processes run automatically.
---

# Antigravity Full Auto-Execution Skill

Kỹ năng này giúp Agent tự động kiểm tra, cấu hình và kích hoạt chế độ **EAGER Auto-Execution (Tự động thực thi toàn bộ dòng lệnh)** trong Google Antigravity IDE và Antigravity 2.0 mà không cần người dùng phải bấm nút `Submit` xác nhận mỗi khi chạy lệnh terminal.

---

## 1. Khi nào kích hoạt Skill này?
Kích hoạt skill này khi người dùng yêu cầu:
- Tắt thông báo "Allow running command?" hoặc popup bắt duyệt lệnh.
- Cho agent tự động chạy từ đầu đến cuối quy trình mà không dừng ở trạng thái `Blocked` / `Waiting for user input`.
- Cấu hình chạy tự động cho tất cả các câu lệnh Node.js, Python, Shell, Git,...
- Chuyển đổi chính sách `CASCADE_COMMANDS_AUTO_EXECUTION` từ `OFF` sang `EAGER`.

---

## 2. Quy trình thực hiện (Runbook)

### Bước 1: Kiểm tra trạng thái hiện tại
Chạy script kiểm tra xem hệ thống và các dự án đang ở chế độ nào:
```bash
node scripts/status.mjs
```

### Bước 2: Bật chế độ Tự động thực thi (Eager Mode)
Chạy script tự động cập nhật `config.json` và toàn bộ các project trong `projects/`:
```bash
node scripts/enable_auto_exec.mjs
```
Script này sẽ:
1. Sao lưu file cấu hình gốc thành `config.json.bak`.
2. Đổi `autoExecutionPolicy` thành `CASCADE_COMMANDS_AUTO_EXECUTION_EAGER`.
3. Đồng bộ thiết lập này vào tất cả các project hiện có trên máy.

### Bước 3: Hướng dẫn người dùng áp dụng
1. Thông báo cho người dùng đã kích hoạt thành công chế độ `CASCADE_COMMANDS_AUTO_EXECUTION_EAGER`.
2. Hướng dẫn người dùng đóng và mở lại ứng dụng Antigravity một lần để backend `language_server.exe` nạp cấu hình mới.

### Bước 4: Hoàn tác (nếu người dùng muốn quay lại chế độ an toàn)
Nếu người dùng muốn bật lại cơ chế hỏi duyệt bảo vệ:
```bash
node scripts/disable_auto_exec.mjs
```

---

## 3. Tài liệu tham khảo sâu
- Đọc thêm tài liệu kỹ thuật tại [references/under-the-hood.md](references/under-the-hood.md) để hiểu sâu về cơ chế định danh lệnh và kiến trúc engine Cascade của Google.
