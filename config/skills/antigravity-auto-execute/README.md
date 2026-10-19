# 🚀 Google Antigravity Auto-Execution Skill (Full Auto Mode)

> **Bí kíp mở khóa chế độ Tự Động 100% (YOLO / Eager Mode) cho Google Antigravity IDE & Antigravity 2.0**  
> *Không còn bị phiền bởi popup "Allow running command?" hay trạng thái Blocked bắt bấm Submit liên tục!*

---

## 🎯 Vấn đề cộng đồng hay gặp phải
Khi dùng Antigravity xây dựng các quy trình tự động (như bot Facebook Ads, crawl dữ liệu, lập trình tự động đa bước), bạn sẽ thường xuyên bị nghẽn:
- Mỗi khi Agent chạy lệnh terminal (Node, Python, Shell, Git...), Antigravity lại hiện popup **"Allow running command?"** và trạng thái hội thoại bị đứng yên ở `Blocked / Waiting for user input`.
- Dù đã vào `Settings -> Terminal Commands` thêm lệnh, nhưng hễ Agent sinh ra một đoạn code inline mới (`node -e "..."`) thì hệ thống lại coi là lệnh mới và tiếp tục chặn bắt bấm `Submit`.
- Trên giao diện bên ngoài, Google cố tình **giấu công tắc cho phép chạy tự động** vì lý do an toàn mặc định.

---

## 💡 Giải pháp kỹ thuật từ lõi hệ thống
Bên trong nhân điều hành `language_server.exe` của Antigravity, Google quản lý quyền chạy lệnh bằng biến:
```text
CASCADE_COMMANDS_AUTO_EXECUTION
```
- Giá trị mặc định: `CASCADE_COMMANDS_AUTO_EXECUTION_OFF` (Bắt buộc hỏi người dùng).
- **Giá trị mở khóa:** `CASCADE_COMMANDS_AUTO_EXECUTION_EAGER` (**Thực thi ngay lập tức mọi câu lệnh, không chờ duyệt**).

Skill này giúp kích hoạt cờ bí mật `EAGER` vào thẳng file cấu hình của Antigravity chỉ với 1 cú click!

---

## 📦 Cấu trúc Skill
```text
antigravity-auto-execute/
├── SKILL.md                          # Hướng dẫn chính thức cho Agent
├── README.md                         # Hướng dẫn sử dụng & chia sẻ cộng đồng
├── scripts/
│   ├── enable_auto_exec.mjs          # Script kích hoạt Full Auto (Eager Mode)
│   ├── disable_auto_exec.mjs         # Script hoàn tác về chế độ hỏi an toàn
│   └── status.mjs                    # Script kiểm tra trạng thái hiện tại
└── references/
    └── under-the-hood.md             # Tài liệu phân tích sâu kiến trúc Cascade
```

---

## ⚡ Hướng dẫn cài đặt & sử dụng

### Cách 1: Cho Agent tự chạy (Khuyên dùng)
Bạn chỉ cần chép thư mục `antigravity-auto-execute` này vào thư mục cấu hình:
- **Đường dẫn**: `C:\Users\<Tên_User>\.gemini\config\skills\antigravity-auto-execute\`

Sau đó trong ô chat Antigravity, bạn chỉ cần gõ:
> *"Bật chế độ tự động thực thi (auto-execution) cho tôi."*

Agent sẽ tự động nhận diện skill này và thực hiện mọi thao tác cấu hình cho bạn!

---

### Cách 2: Chạy trực tiếp bằng lệnh 1-chạm (Dành cho Dev)
Mở PowerShell hoặc Command Prompt và chạy:
```bash
node "C:\Users\<Tên_User>\.gemini\config\skills\antigravity-auto-execute\scripts\enable_auto_exec.mjs"
```

Sau khi chạy xong:
1. Đóng và mở lại ứng dụng Antigravity.
2. Từ nay Agent sẽ tự động làm việc từ đầu đến cuối mà không bao giờ hỏi duyệt Submit nữa!

---

### Cách 3: Sửa thủ công bằng tay (Nếu không muốn chạy script)
1. Mở file: `C:\Users\<Tên_User>\.gemini\config\config.json`
2. Tìm dòng `"autoExecutionPolicy"` và sửa thành:
   ```json
   "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"
   ```
3. Lưu file và khởi động lại Antigravity.

---

## 🔄 Hoàn tác (Khi muốn quay lại chế độ hỏi bảo vệ)
Nếu muốn bật lại cơ chế hỏi duyệt như cũ, chỉ cần chạy:
```bash
node scripts/disable_auto_exec.mjs
```

---
*Tạo bởi cộng đồng người dùng Antigravity Việt Nam 🇻🇳*
