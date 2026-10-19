# Google Antigravity Auto-Execution Architecture & Internal Mechanics

Tài liệu kỹ thuật giải thích cách cơ chế thực thi lệnh (Command Execution) hoạt động trong lõi Google Antigravity và Antigravity 2.0.

---

## 1. Vấn đề cốt lõi: Tại sao UI không cho bật tự động?

Trong các phiên bản Antigravity và Antigravity 2.0 (Desktop Electron build), phần giao diện người dùng (UI Settings):
- **Security Preset**: Cho chọn `Full Machine`, `Sandbox`, v.v.
- **Terminal Commands**: Chỉ cho phép thêm lệnh tĩnh (`e.g., npm test`) theo cơ chế **so khớp chính xác 100% (Exact Match)**.

### Tại sao lại bị dừng hỏi `Submit` liên tục?
Khi Agent thực hiện các tác vụ động (ví dụ: truy vấn Meta Graph API, kiểm tra dữ liệu, chạy script tự sinh), Agent thường chạy các câu lệnh có tham số thay đổi hoặc code inline:
```bash
node -e " import('./.agents/...').then(...) "
```
Do mỗi lần chạy code lại đổi một vài ký tự, cơ chế Exact Match trong Allowlist nhận diện đây là một câu lệnh mới hoàn toàn chưa từng được cấp phép, do đó luôn kích hoạt modal:
`Allow running command? -> Blocked / Waiting for user input`

---

## 2. Nhân điều hành Cascade & Cờ ẩn `CASCADE_COMMANDS_AUTO_EXECUTION`

Bên trong backend lõi của Google Antigravity (`resources/bin/language_server.exe`), toàn bộ luồng suy nghĩ và hành động của Agent được điều phối bởi engine có mã nội bộ là **Cascade**.

Quy tắc thực thi lệnh trong terminal được quản lý bởi enum:
```text
CASCADE_COMMANDS_AUTO_EXECUTION_UNSPECIFIED
CASCADE_COMMANDS_AUTO_EXECUTION_OFF                // Mặc định: Yêu cầu xác nhận (Request review)
CASCADE_COMMANDS_AUTO_EXECUTION_AUTO               // Agent tự phán đoán rủi ro
CASCADE_COMMANDS_AUTO_EXECUTION_EAGER              // Tự động chạy ngay lập tức (Always Proceed / YOLO)
CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX // Tự động chạy trong Sandbox
```

### Điểm mấu chốt:
Khi đặt `autoExecutionPolicy` thành **`CASCADE_COMMANDS_AUTO_EXECUTION_EAGER`**:
- Nhân `language_server.exe` sẽ bỏ qua bước chặn chờ phê duyệt từ người dùng.
- Mọi câu lệnh terminal (`run_command`) do agent phát ra sẽ được chuyển trực tiếp vào shell để thực thi ngay lập tức.
- Trạng thái hội thoại không bao giờ bị chuyển thành `Blocked`.

---

## 3. Vị trí lưu trữ cấu hình trên máy tính

### A. Cấu hình toàn cục (Global)
- **Đường dẫn**: `~/.gemini/config/config.json` (Windows: `C:\Users\<Username>\.gemini\config\config.json`)
- **Khóa cấu hình**:
  ```json
  {
    "userSettings": {
      "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"
    }
  }
  ```

### B. Cấu hình dự án (Project Override)
- **Đường dẫn**: `~/.gemini/config/projects/<project-id>.json`
- **Khóa cấu hình**:
  ```json
  {
    "settings": {
      "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"
    },
    "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"
  }
  ```
