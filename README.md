# Antigravity Config & Skills Repository

Configuration, skills, and WSL binary patcher for Google Antigravity & Agent.

## Quick Install on a New Machine

Open PowerShell on the new machine and run:

```powershell
# 1. Clone repository
git clone https://github.com/Gohans1/antigravity-config.git "$env:USERPROFILE\antigravity-config"

# 2. Copy config to ~/.gemini/config
Copy-Item -Path "$env:USERPROFILE\antigravity-config\config\*" -Destination "$env:USERPROFILE\.gemini\config" -Recurse -Force
```

Or just prompt the AI on the new machine:
> "Clone repo `Gohans1/antigravity-config` và copy nội dung thư mục config vào `~/.gemini/config` để cài đặt cấu hình Antigravity cho tôi."

If the machine has its own `config/mcp_config.local.json`, ask the AI to **overlay it on top** of `~/.gemini/config/mcp_config.json` (same `mcpServers` keys, local wins). It carries machine-specific absolute paths and API keys, so it is git-ignored on purpose.

## What's Included:
- `config/GEMINI.md`: Global instructions and behavioral rules.
- `config/skills/`: Custom skills (`antigravity-auto-execute`, `ponytail`, `test-driven-development`, etc.).
- `config/mcp_config.json`: Portable MCP servers (`codegraph`, `chrome-devtools`, `tldraw`). Machine-independent only.
- `config/mcp_config.local.json`: Machine-specific MCP servers with absolute paths and keys. Git-ignored, per machine.
- `config/config.json`: User UI settings and permission grants.
- `exa-cli/`: Bundled `exa` search & local Markdown/HTML fetch CLI (`exa search`, `exa fetch`, `exa status`).
- `wsl/`: WSL/Linux `language_server` truncation patcher (`128 KiB` / `129 KiB`) and systemd auto-patcher units.

## 🔎 Install `exa` CLI (`exa-cli/`)

```bash
cd ~/antigravity-config/exa-cli
bun install
bun link
```

Store API keys in `~/.config/exa/config.json` (or `EXA_API_KEYS` / `EXA_API_KEY` env vars):

```json
{ "keys": [{ "label": "personal", "value": "00000000-0000-0000-0000-000000000000" }] }
```

## 🚀 Auto-Execution (Full Auto / Eager Mode)

Kích hoạt chế độ tự động thực thi lệnh (không cần bấm Submit duyệt từng lệnh):
- Double click **`1_KICH_HOAT_TU_DONG.bat`** (hoặc chạy trong `config/skills/antigravity-auto-execute/`).
- Double click **`2_KIEM_TRA_TRANG_THAI.bat`** để kiểm tra trạng thái các project.
- Double click **`3_TAT_TU_DONG_HOAN_TAC.bat`** nếu muốn quay về chế độ hỏi duyệt an toàn.

## 🐧 WSL `language_server` Truncation Patcher (Rules, Skills, `view_file`, `run_command` & MCP)

Mở khóa giới hạn cắt cụt `GEMINI.md` / Rules / Skills (`24 KB` / `20k` tokens -> `128 KiB` / `128k` tokens), `view_file` (`800` dòng / `45 KiB` -> `2,000` dòng / `68 KiB`), `run_command` (`8 KiB` / `10 KB` -> `128 KiB`), `McpToolHandler` (`10 KiB` -> `128 KiB`), và outer step serializer (`45 KiB` -> `129 KiB`) trên WSL/Linux (vừa vá file binary trên đĩa vừa live-patch thẳng vào RAM):

- `wsl/patch-antigravity-server.py`: Script tự động vá mọi bản `language_server` trong `~/.antigravity-server/bin/*/language_server` và live-patch tiến trình đang chạy qua `/proc/<pid>/mem`.
- `wsl/antigravity-patcher.service` & `wsl/antigravity-patcher.path`: Systemd user units tự động kích hoạt bản vá mỗi khi Antigravity tự update phiên bản `language_server` mới.

### Cài đặt trên WSL / Linux:

```bash
mkdir -p ~/.local/bin ~/.config/systemd/user
cp ~/antigravity-config/wsl/patch-antigravity-server.py ~/.local/bin/patch-antigravity-server.py
chmod +x ~/.local/bin/patch-antigravity-server.py
cp ~/antigravity-config/wsl/antigravity-patcher.service ~/antigravity-config/wsl/antigravity-patcher.path ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now antigravity-patcher.path antigravity-patcher.service
```
