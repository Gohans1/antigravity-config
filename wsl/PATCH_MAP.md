# Bản đồ dịch ngược và vá nóng Antigravity Language Server

Tài liệu định hướng cấu trúc binary cho AI tương lai khi nâng cấp hoặc vá lỗi trên cả WSL Linux và Windows. Trình biên dịch Go dùng chung chuẩn thanh ghi ABIInternal trên cả ELF Linux và PE Windows nên toàn bộ chuỗi byte nhận diện cũng như độ lệch tương đối trong vùng mã thực thi đều giống hệt nhau giữa hai hệ điều hành.

## Đường dẫn thực thi và cơ chế kích hoạt

| Môi trường | Đường dẫn file thực thi | Cơ chế tự động chạy và làm tươi |
| :--- | :--- | :--- |
| WSL và Linux | ~/.antigravity-server/bin/*/language_server | Systemd user theo dõi thư mục bin và daemon để vá đĩa cứng cùng bộ nhớ RAM rồi gọi RPC GetAvailableModels với cờ forceRefresh. |
| Windows thuần | %LOCALAPPDATA%/Programs/Antigravity/resources/bin/language_server.exe | Dùng trực tiếp cùng bảng mẫu byte của script Python để vá file thực thi trước khi khởi động giao diện hoặc qua Task Scheduler. |
| Giao diện UI | resources/app/out/vs/workbench/workbench.desktop.main.js | Giao diện đã dựng sẵn năm mức nỗ lực gồm low, medium, high, xhigh hiển thị là Extra và max hiển thị là Max dựa theo hậu tố tên model. |

## Bản đồ bốn điểm neo mở khóa Gemini 4 Argon Extra và Max

| Điểm neo trong binary | Chuỗi byte hoặc hằng số nhận diện | Nhiệm vụ khi vá |
| :--- | :--- | :--- |
| CodeAssistClient.fetchAvailableModels | So sánh độ dài 0x1d tức 29 ký tự rồi nhảy qua lời gọi hàm lọc | Ghi đè thành lệnh nhảy không điều kiện để luôn gọi hàm bơm model mỗi lần làm tươi danh sách. |
| CodeAssistClient.filterUnavailableVertex3PModels | Thân hàm tại độ lệch 0xec sau đầu hàm nhận diện từ bước trên | Tìm bản ghi gemini-4-argon-high rồi nhân bản thành hai bản ghi hậu tố /xhigh và /max với mã enum lùi một và hai đơn vị kèm mức suy luận 5 và 6. |
| staticCatalog.GetModelInfoFromKey | Kiểm tra tra cứu bảng tĩnh trước khi trả về con trỏ ModelInfo trong thanh ghi rbx | Nếu trường mức suy luận tại độ lệch 0x88 lớn hơn hoặc bằng 5 thì gán lại độ dài chuỗi tên model tại độ lệch 0x40 về 0x13 tức 19 ký tự để cắt bỏ hậu tố trước khi gửi lên Google. |
| CodeAssistClient.GetChatMessage | Lệnh nhảy có điều kiện 74 6e ngay sau lời gọi kiểm tra chuỗi có dấu gạch chéo | Thay hai byte nhảy bằng lệnh rỗng 90 90 để luôn tách bỏ phần hậu tố sau dấu gạch chéo khỏi mã modelId. |

## Bảng độ lệch cấu trúc dữ liệu Go trong bộ nhớ

| Cấu trúc | Độ lệch byte | Kiểu dữ liệu | Ý nghĩa và luồng truyền dữ liệu |
| :--- | :--- | :--- | :--- |
| ModelInfo | 0x08 | int32 | Mã enum định danh model nội bộ như M419 là 1419 cho bản Low, M418 là 1418 cho bản Medium, M417 là 1417 cho bản High, M416 là 1416 cho bản Extra và M415 là 1415 cho bản Max. |
| ModelInfo | 0x38 và 0x40 | string ptr và len | Chuỗi tên model gửi lên máy chủ Google CCPA, cần ép độ dài tại 0x40 về 19 ký tự để giữ nguyên chuỗi gốc gemini-4-argon-high. |
| ModelInfo | 0x7c và 0x80 | int32 và int32 | Ngân sách token suy luận tối thiểu và tối đa khi không dùng mức suy luận theo cấp độ. |
| ModelInfo | 0x88 | int32 | Cấp độ suy luận ThinkingLevel, truyền thẳng vào trường tương ứng của cấu hình sinh văn bản trong hàm buildRequest. |
| ClientModelConfig | 0x08 và 0x10 | string ptr và len | Nhãn hiển thị trên giao diện người dùng như Gemini 4 Argon (Xhigh) và Gemini 4 Argon (Max). |
| ClientModelConfig | 0x70 | int32 | Mã enum model trả về cho giao diện khi gọi RPC GetCascadeModelConfigData. |
| ClientModelConfig | 0xc4 | int32 | Trường lưu tạm cấp độ suy luận trong bản ghi chi tiết model trước khi ánh xạ sang cấu trúc ModelInfo. |
| GenerationConfig_ThinkingConfig | 0x08, 0x10, 0x18 | ptr bool, ptr int32, ptr int32 | Lần lượt là cờ xuất suy nghĩ IncludeThoughts, ngân sách ThinkingBudget và cấp độ ThinkingLevel được hàm buildRequest đóng gói gửi lên máy chủ. |

## Bản đồ các điểm vá nới giới hạn đầu ra và ngữ cảnh

| Hàm mục tiêu | Giá trị gốc | Giá trị sau khi vá | Cách dò tìm lại khi đổi phiên bản trình biên dịch |
| :--- | :--- | :--- | :--- |
| utils.terminalDetailsFromScopeItem và serializers | 8 KiB tức 0x2000 | 42 KiB tức 0xa800 | Tìm hằng số nạp thanh ghi 0x2000 đi kèm hằng số kiểu cắt chuỗi bằng 2 ngay trước lệnh gọi hàm cắt chuỗi. |
| handlers.McpToolHandler.Handle | 10 KiB tức 0x2800 | 128 KiB tức 0x20000 | Tìm nhánh đọc giới hạn byte đầu ra của công cụ MCP tại độ lệch 0x10 và ghi đè thanh ghi r8d thành 0x20000. |
| tooldecorators.truncateOutput | 10 KB | 129 KiB tức 0x20400 | Dùng biểu thức chính quy khớp chuỗi lệnh lưu thanh ghi rax và rdi xuống ngăn xếp ngay trước phép so sánh độ dài rcx và rbx. |
| customizations.readGlobalRules, parseRuleFile, convertSkillPath | 24 KB tức 0x5dc0 | 128 KiB tức 0x20000 | Tìm hằng số nạp 0x5dc0 vào thanh ghi ecx tại các hàm nạp luật toàn cục và kỹ năng. |
| customizations.computeTruncatedCustomizations và GetTokenBase | 20000 token tức 0x4e20 | 131072 token tức 0x20000 | Tìm hằng số nạp 0x4e20 làm ngân sách token tối đa cho tập luật và kỹ năng. |
| config.GetDefaultConversationalCascadeConfig và ViewFile | 800 dòng và 45 KiB | 2000 dòng và 68 KiB | Tìm hằng số 0x320 tức 800 dòng và 0xb400 tức 46080 byte trong cấu hình mặc định cùng bộ chuyển đổi công cụ đọc file. |
