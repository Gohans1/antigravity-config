#!/usr/bin/env python3
"""
Idempotent binary + live-memory patcher for Antigravity language_server.
- Raises command output limits (command.TruncateOutput 8 KiB) to 42 KiB (43,008 bytes).
- Raises MCP output limit (McpToolHandler.Handle 10 KiB) to 128 KiB and outer step cap to 129 KiB.
- Raises global rules / skills file & token limits (24 KB / 20k tokens) to 128 KiB / 128k tokens.
- Raises view_file limits (MaxLinesPerView 800 -> 2,000 lines, MaxBytesPerView 45 KiB -> 68 KiB)
  and DefaultSerializer.stepToMessage maxStepTokens (16,384 -> 44,544 tokens / 129 KiB).
"""
import glob
import os
import re
import shutil
import stat
import subprocess
import sys

# Exact byte patches: (name, original_bytes, patched_bytes, required)
EXACT_PATCHES = [
    (
        "command.TruncateOutput (8 KiB -> 42 KiB unconditional)",
        bytes.fromhex("488b4308488b5b104885c9ba00200000480f44ca"),
        bytes.fromhex("488b4308488b5b1031c990ba00a80000480f44ca"),
        True,
    ),
    (
        "ideCommand.execute (8 KiB -> 42 KiB raw debug buffer)",
        bytes.fromhex(
            "4881fa002000007e4748c786b8010000002000004829d74881c7002000004889bec00100004a8dbe00e0ffff"
        ),
        bytes.fromhex(
            "4881fa00a800007e4748c786b801000000a800004829d74881c700a800004889bec00100004a8dbe0058ffff"
        ),
        False,
    ),
    (
        "utils.terminalDetailsFromScopeItem (8 KiB -> 42 KiB)",
        bytes.fromhex("488b02488b5a08b900200000488d7c2470be02000000"),
        bytes.fromhex("488b02488b5a08b900a80000488d7c2470be02000000"),
        False,
    ),
    (
        "serializers.terminalDetailsFromScopeItem (8 KiB -> 42 KiB)",
        bytes.fromhex("488b024889f3b900200000e8"),
        bytes.fromhex("488b024889f3b900a80000e8"),
        False,
    ),
    (
        "tooldecorators.newOutputTruncationDecorator (10 KB -> 129 KiB outer cap)",
        bytes.fromhex("4885d274058b5208eb0231d24885d274"),
        bytes.fromhex("4885d27407ba0004020066904885d274"),
        False,
    ),
    (
        "customizations.readGlobalRules (24 KB -> 128 KiB per-file limit)",
        bytes.fromhex("010000b9c05d0000488dbc24"),
        bytes.fromhex("010000b900000200488dbc24"),
        False,
    ),
    (
        "customizations.parseRuleFile (24 KB -> 128 KiB per-file limit)",
        bytes.fromhex("488b4230488b5a38b9c05d0000488dbc2450010000be02000000"),
        bytes.fromhex("488b4230488b5a38b900000200488dbc2450010000be02000000"),
        False,
    ),
    (
        "customizations.convertSkillPath (24 KB -> 128 KiB per-skill limit)",
        bytes.fromhex("80000000b9c05d0000488dbc24"),
        bytes.fromhex("80000000b900000200488dbc24"),
        False,
    ),
    (
        "customizations.computeTruncatedCustomizations (20k -> 128k rules token budget)",
        bytes.fromhex("41b900000000eb094885d241b9204e000074084c8b5208"),
        bytes.fromhex("41b900000000eb094885d241b90000020074084c8b5208"),
        False,
    ),
    (
        "customizations.computeTruncatedCustomizations (20k -> 128k skills/workflows token budget)",
        bytes.fromhex("8b12eb0931d2eb05ba204e000044898c24"),
        bytes.fromhex("8b12eb0931d2eb05ba0000020044898c24"),
        False,
    ),
    (
        "language_server.GetTokenBase (20k -> 128k rules token budget)",
        bytes.fromhex("ba00000000eb084885c0ba204e00007406488b7008"),
        bytes.fromhex("ba00000000eb084885c0ba000002007406488b7008"),
        False,
    ),
    (
        "language_server.GetTokenBase (20k -> 128k skills/workflows token budget)",
        bytes.fromhex("8b1eeb0931dbeb05bb204e0000899424"),
        bytes.fromhex("8b1eeb0931dbeb05bb00000200899424"),
        False,
    ),
    (
        "config.GetDefaultConversationalCascadeConfig (800 -> 2000 MaxLinesPerView)",
        bytes.fromhex("c70020030000488d05"),
        bytes.fromhex("c700d0070000488d05"),
        False,
    ),
    (
        "config.GetDefaultConversationalCascadeConfig (45 KiB -> 68 KiB MaxBytesPerView)",
        bytes.fromhex("4889842470020000c70000b40000488d05"),
        bytes.fromhex("4889842470020000c70000100100488d05"),
        False,
    ),
    (
        "tools.ViewFileToolConverter.ToolCallToCortexStep (800 -> 2000 MaxLinesPerView unconditional)",
        bytes.fromhex("4885ff74048b0feb0231c9488b4210488b5a18"),
        bytes.fromhex("b9d00700006690eb0231c9488b4210488b5a18"),
        False,
    ),
    (
        "handlers.ViewFileHandler.Handle (45 KiB -> 68 KiB MaxBytesPerView unconditional)",
        bytes.fromhex(
            "488b76484885f674048b36eb0231f64885f674114889cf4c29c74839fe"
        ),
        bytes.fromhex(
            "488b7648be001001006690eb0231f64885f674114889cf4c29c74839fe"
        ),
        False,
    ),
    (
        "handlers.McpToolHandler.Handle (10 KiB -> 128 KiB MaxOutputBytes unconditional)",
        bytes.fromhex("4d85c07406458b4010eb034531c044894424"),
        bytes.fromhex("41b8000002000f1f00eb034531c044894424"),
        False,
    ),
    (
        "integration.CreateSerializer (16k -> 44.5k MaxStepTokens / 129 KiB net)",
        bytes.fromhex("4c8b47504d85c07405458b00eb034531c04d63c0"),
        bytes.fromhex("4c8b475041b800ae00006690eb034531c04d63c0"),
        False,
    ),
    (
        "serializers.DefaultSerializer.stepToMessage (16k -> 44.5k maxStepTokens / 129 KiB net, 2.18..2.21)",
        bytes.fromhex(
            "83fa0e750a488bbc24c8010000eb1183fa17750431ffeb08488bbc24c00100004885ff7f0a"
        ),
        bytes.fromhex(
            "83fa0e750a488bbc24c8010000eb1183fa17750431ffeb08bf00ae00000f1f004885ff7f0a"
        ),
        False,
    ),
    (
        "serializers.DefaultSerializer.stepToMessage (16k -> 44.5k maxStepTokens / 129 KiB net, 2.23+)",
        bytes.fromhex(
            "83fa0e750a488bbc24d8010000eb1183fa17750431ffeb08488bbc24d00100004885ff7f0a"
        ),
        bytes.fromhex(
            "83fa0e750a488bbc24d8010000eb1183fa17750431ffeb08bf00ae00000f1f004885ff7f0a"
        ),
        False,
    ),
]

# Regex patch for tooldecorators.truncateOutput across all compiler stack layouts:
# Replaces redundant initial `mov %rax, disp(%rsp)` (8 bytes) before `cmp %rcx, %rbx; jle ...`
# with `mov $0x20400, %ecx; nopl (%rax)` (`b9 00 04 02 00 0f 1f 00`, 8 bytes = 129 KiB outer cap).
TRUNCATE_OUTPUT_ORIG_RE = re.compile(
    re.escape(bytes.fromhex("48898424"))
    + b"(....)"
    + re.escape(bytes.fromhex("4889bc24"))
    + b"(....)"
    + re.escape(bytes.fromhex("4839cb0f8e"))
    + b"(....)"
    + re.escape(bytes.fromhex("48898c24"))
    + b"(....)"
    + re.escape(bytes.fromhex("48898424"))
    + b"\\1",
    re.DOTALL,
)

TRUNCATE_OUTPUT_PATCHED_RE = re.compile(
    re.escape(bytes.fromhex("b9000402000f1f00"))
    + re.escape(bytes.fromhex("4889bc24"))
    + b"(....)"
    + re.escape(bytes.fromhex("4839cb0f8e"))
    + b"(....)"
    + re.escape(bytes.fromhex("48898c24"))
    + b"(....)"
    + re.escape(bytes.fromhex("48898424"))
    + b"(....)",
    re.DOTALL,
)


def patch_binary_file(bin_path: str) -> list[tuple[int, bytes, bytes]]:
    orig_backup = bin_path + ".orig"
    with open(bin_path, "rb") as f:
        current_data = bytearray(f.read())

    if os.path.exists(orig_backup) and os.path.getsize(orig_backup) == len(current_data):
        with open(orig_backup, "rb") as f:
            data = bytearray(f.read())
    else:
        data = bytearray(current_data)

    applied_offsets: list[tuple[int, bytes, bytes]] = []
    modified = False

    for name, orig, patched, required in EXACT_PATCHES:
        assert len(orig) == len(patched), f"Length mismatch in {name}"
        c_orig = data.count(orig)
        c_patched = data.count(patched)

        if c_patched == 1 and c_orig == 0:
            idx = data.find(patched)
            applied_offsets.append((idx, orig, patched))
            print(f"  [already-patched] {name} @ 0x{idx:x}")
            continue

        if c_orig == 1:
            idx = data.find(orig)
            data[idx : idx + len(orig)] = patched
            applied_offsets.append((idx, orig, patched))
            if current_data[idx : idx + len(patched)] == patched:
                print(f"  [already-patched] {name} @ 0x{idx:x}")
            else:
                modified = True
                print(f"  [patched] {name} @ 0x{idx:x}")
        elif required:
            print(
                f"  [WARN] Required signature '{name}' count={c_orig} in {bin_path}",
                file=sys.stderr,
            )

    # Layer 2: tooldecorators.truncateOutput (regex across stack frame sizes)
    m_orig = list(TRUNCATE_OUTPUT_ORIG_RE.finditer(data))
    m_patched = list(TRUNCATE_OUTPUT_PATCHED_RE.finditer(data))
    td_name = "tooldecorators.truncateOutput (10 KB -> 129 KiB outer cap)"
    if len(m_patched) == 1 and len(m_orig) == 0:
        idx = m_patched[0].start()
        rax_disp = m_patched[0].group(4)
        orig_head = bytes.fromhex("48898424") + rax_disp
        patched_head = bytes.fromhex("b9000402000f1f00")
        applied_offsets.append((idx, orig_head, patched_head))
        print(f"  [already-patched] {td_name} @ 0x{idx:x}")
    elif len(m_orig) == 1:
        idx = m_orig[0].start()
        rax_disp = m_orig[0].group(1)
        orig_head = bytes.fromhex("48898424") + rax_disp
        patched_head = bytes.fromhex("b9000402000f1f00")
        data[idx : idx + 8] = patched_head
        applied_offsets.append((idx, orig_head, patched_head))
        if current_data[idx : idx + 8] == patched_head:
            print(f"  [already-patched] {td_name} @ 0x{idx:x}")
        else:
            modified = True
            print(f"  [patched] {td_name} @ 0x{idx:x}")
    else:
        print(
            f"  [WARN] Required signature '{td_name}' orig={len(m_orig)} patched={len(m_patched)} in {bin_path}",
            file=sys.stderr,
        )

    if modified:
        if not os.path.exists(orig_backup):
            with open(orig_backup, "wb") as f:
                f.write(current_data)
            shutil.copymode(bin_path, orig_backup)
            print(f"  [backup] Saved original binary to {orig_backup}")

        tmp_path = bin_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(data)
        st = os.stat(bin_path)
        os.chmod(tmp_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp_path, bin_path)
        print(f"  [saved] Atomically updated {bin_path}")

    return applied_offsets


def live_patch_pid(pid: int, offsets: list[tuple[int, bytes, bytes]]) -> None:
    maps_path = f"/proc/{pid}/maps"
    base = None
    with open(maps_path, "r") as f:
        for line in f:
            parts = line.split()
            if (
                len(parts) >= 6
                and "r-xp" in parts[1]
                and int(parts[2], 16) == 0
                and "language_server" in parts[5]
            ):
                base = int(parts[0].split("-")[0], 16)
                break
    if base is None:
        return

    helper = (
        "import sys\n"
        f"with open('/proc/{pid}/mem', 'r+b', buffering=0) as m:\n"
    )
    for idx, orig, patched in offsets:
        va = base + idx
        helper += (
            f"    m.seek({va})\n"
            f"    cur = m.read({len(orig)})\n"
            f"    if cur == bytes.fromhex('{patched.hex()}'):\n"
            f"        print('  [live-ram-already-patched] PID {pid} @ 0x{va:x} (file +0x{idx:x})')\n"
            f"    else:\n"
            f"        m.seek({va})\n"
            f"        m.write(bytes.fromhex('{patched.hex()}'))\n"
            f"        print('  [live-ram-patched] PID {pid} @ 0x{va:x} (file +0x{idx:x})')\n"
        )

    try:
        subprocess.run(
            [sys.executable, "-c", helper],
            check=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        subprocess.run(["sudo", "-n", sys.executable, "-c", helper], check=True)


def is_file_stable(path: str) -> bool:
    try:
        s1 = os.stat(path)
        if s1.st_size < 50_000_000:
            return False
        import time

        time.sleep(0.15)
        s2 = os.stat(path)
        return s1.st_size == s2.st_size and s1.st_mtime_ns == s2.st_mtime_ns
    except OSError:
        return False


def run_pass() -> None:
    server_bins = sorted(
        glob.glob(os.path.expanduser("~/.antigravity-server/bin/*/language_server"))
    )
    if not server_bins:
        print("No language_server binaries found.")
        return

    offsets_by_realpath: dict[str, list[tuple[int, bytes, bytes]]] = {}
    for bin_path in server_bins:
        if not is_file_stable(bin_path):
            print(f"Skipping {bin_path} (still being written)...")
            continue
        print(f"Checking {bin_path}:")
        offsets = patch_binary_file(bin_path)
        offsets_by_realpath[os.path.abspath(bin_path)] = offsets

    # Also live-patch any currently running language_server process in RAM
    for pid_dir in glob.glob("/proc/[0-9]*"):
        try:
            pid = int(pid_dir.split("/")[2])
            with open(f"{pid_dir}/maps", "r") as f:
                first_map = f.read()
            for bin_path, offsets in offsets_by_realpath.items():
                if bin_path in first_map and offsets:
                    live_patch_pid(pid, offsets)
        except Exception:
            pass


def main() -> None:
    import time

    passes = 6 if "--systemd" in sys.argv else 1
    for i in range(passes):
        run_pass()
        if i + 1 < passes:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
