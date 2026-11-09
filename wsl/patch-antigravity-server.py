#!/usr/bin/env python3
"""
Idempotent binary + live-memory patcher for Antigravity language_server.
- Raises command output limits (command.TruncateOutput 8 KiB) to 42 KiB (43,008 bytes).
- Raises MCP output limit (McpToolHandler.Handle 10 KiB) to 128 KiB and outer step cap to 129 KiB.
- Raises global rules / skills file & token limits (24 KB / 20k tokens) to 128 KiB / 128k tokens.
- Raises view_file limits (MaxLinesPerView 800 -> 2,000 lines, MaxBytesPerView 45 KiB -> 68 KiB)
  and DefaultSerializer.stepToMessage maxStepTokens (16,384 -> 44,544 tokens / 129 KiB).
- Unlocks Gemini 4 Argon Extra (Xhigh, ThinkingLevel=5, MODEL_PLACEHOLDER_M416) and
  Max (ThinkingLevel=6, MODEL_PLACEHOLDER_M415) in UI selector and CCPA requests.
"""
import glob
import os
import re
import shutil
import stat
import struct
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


import struct
import re

def find_all(data: bytes, pat: bytes) -> list[int]:
    res = []
    start = 0
    while True:
        idx = data.find(pat, start)
        if idx == -1:
            break
        res.append(idx)
        start = idx + 1
    return res

def resolve_symbols(data: bytes) -> dict[str, int]:
    # 1. GetChatMessage slash split check
    p1 = bytes([0x48, 0x8b, 0x11, 0x48, 0x8b, 0x41, 0x08, 0x48, 0x8b, 0x4a, 0x78, 0xff, 0xd1, 0x84, 0xc0, 0x74, 0x6e])
    m1 = find_all(data, p1)
    assert len(m1) == 1, f"m1={len(m1)}"
    chat_je_idx = m1[0] + 15

    # 2. fetchAvailableModels filter call
    p2 = bytes([0x48, 0x83, 0xfa, 0x1d, 0x74, 0x04, 0x31, 0xc9, 0xeb, 0x25])
    m2 = find_all(data, p2)
    assert len(m2) == 1, f"m2={len(m2)}"
    jmp_from = m2[0]
    p2_to = bytes([0x48, 0x8b, 0x9c, 0x24, 0xc8, 0x00, 0x00, 0x00, 0x48, 0x8b, 0x8c, 0x24, 0xd0, 0x00, 0x00, 0x00])
    jmp_to = data.find(p2_to, jmp_from, jmp_from + 0x100)
    assert jmp_to != -1
    call_pos = data.find(bytes([0x66, 0x90, 0xe8]), jmp_to, jmp_to + 0x40)
    assert call_pos != -1
    call_ins = call_pos + 2
    rel = struct.unpack("<i", data[call_ins + 1 : call_ins + 5])[0]
    filter_fn = call_ins + 5 + rel

    # 3. Inside filter_fn, extract runtime helpers
    fn_bytes = data[filter_fn : filter_fn + 0x850]
    lea_pos = filter_fn + 0xec
    assert data[lea_pos : lea_pos + 3] == bytes([0x48, 0x8d, 0x05])
    maptype_models = lea_pos + 7 + struct.unpack("<i", data[lea_pos + 3 : lea_pos + 7])[0]

    m_map = re.search(re.escape(bytes([0x90, 0xe8])) + b"(....)" + re.escape(bytes([0x84, 0xdb, 0x0f, 0x85])), fn_bytes, re.DOTALL)
    assert m_map is not None
    call_map_pos = filter_fn + m_map.start() + 1
    mapaccess2_faststr = call_map_pos + 5 + struct.unpack("<i", m_map.group(1))[0]

    m_asgn = re.search(re.escape(bytes([0x48, 0x8b, 0x4c, 0x24, 0x70, 0x48, 0x8b, 0x7c, 0x24, 0x38, 0xe8])) + b"(....)", fn_bytes, re.DOTALL)
    assert m_asgn is not None
    call_asgn_pos = filter_fn + m_asgn.start() + 10
    mapassign_faststr = call_asgn_pos + 5 + struct.unpack("<i", m_asgn.group(1))[0]

    m_new = re.search(re.escape(bytes([0x0f, 0x1f, 0x00, 0xe8])) + b"(....)" + re.escape(bytes([0x48, 0x89, 0x84, 0x24, 0x68, 0x02, 0x00, 0x00])), fn_bytes, re.DOTALL)
    assert m_new is not None
    call_new_pos = filter_fn + m_new.start() + 3
    newobject = call_new_pos + 5 + struct.unpack("<i", m_new.group(1))[0]

    m_grow = re.search(re.escape(bytes([0x4c, 0x89, 0xcb, 0x48, 0x89, 0xd1, 0xbf, 0x01, 0x00, 0x00, 0x00, 0x48, 0x8d, 0x35])) + b"(....)" + re.escape(bytes([0xe8])) + b"(....)", data[jmp_from : jmp_from + 0x2000], re.DOTALL)
    assert m_grow is not None
    lea_str_pos = jmp_from + m_grow.start() + 11
    type_string = lea_str_pos + 7 + struct.unpack("<i", m_grow.group(1))[0]
    call_grow_pos = lea_str_pos + 7
    growslice = call_grow_pos + 5 + struct.unpack("<i", m_grow.group(2))[0]

    # 4. type_ModelDetails
    m_md = re.search(
        re.escape(bytes([0x48, 0x8d, 0x05]))
        + b"(....)"
        + re.escape(bytes([0xe8]))
        + b"(....)"
        + re.escape(bytes([0xc7, 0x40, 0x70, 0x46, 0x01, 0x00, 0x00])),
        data,
        re.DOTALL,
    )
    assert m_md is not None
    lea_md_pos = m_md.start()
    type_ModelDetails = lea_md_pos + 7 + struct.unpack("<i", m_md.group(1))[0]

    # 5. staticCatalog.GetModelInfoFromKey
    pat_gmi = (
        re.escape(bytes([0x84, 0xdb, 0x74, 0x2c, 0x48, 0x8b, 0x18, 0x48, 0x8d, 0x05]))
        + b".{29}"
        + re.escape(bytes([0x48, 0x89, 0xd8, 0x31, 0xdb, 0x31, 0xc9, 0xc9, 0xc3]))
    )
    m_gmi = list(re.finditer(pat_gmi, data, re.DOTALL))
    assert len(m_gmi) == 1
    get_model_info_idx = m_gmi[0].start() + 7

    return {
        "chat_je_idx": chat_je_idx,
        "jmp_from": jmp_from,
        "jmp_to": jmp_to,
        "filter_fn": filter_fn,
        "maptype_models": maptype_models,
        "mapaccess2_faststr": mapaccess2_faststr,
        "mapassign_faststr": mapassign_faststr,
        "newobject": newobject,
        "type_string": type_string,
        "growslice": growslice,
        "type_ModelDetails": type_ModelDetails,
        "get_model_info_idx": get_model_info_idx,
    }


def build_filter_patch(syms: dict[str, int]) -> tuple[int, bytes]:
    body_start = syms["filter_fn"] + 0xec
    buf = bytearray()
    fixups: list[tuple[int, str, str]] = []
    labels: dict[str, int] = {}

    def pc() -> int:
        return body_start + len(buf)

    def emit(b: list[int] | bytes) -> None:
        buf.extend(b)

    def emit_lea_abs(prefix: list[int], target: int) -> None:
        rel = target - (pc() + len(prefix) + 4)
        emit(prefix)
        emit(struct.pack("<i", rel))

    def emit_lea_lbl(prefix: list[int], lbl: str) -> None:
        emit(prefix)
        fixups.append((len(buf), "rel32", lbl))
        emit(b"\x00\x00\x00\x00")

    def emit_call(target: int) -> None:
        rel = target - (pc() + 5)
        emit([0xe8])
        emit(struct.pack("<i", rel))

    def emit_jcc(opcode: list[int], lbl: str) -> None:
        emit(opcode)
        fixups.append((len(buf), "rel32", lbl))
        emit(b"\x00\x00\x00\x00")

    # 1. Lookup "gemini-4-argon-high" (prefix 19 of str_id_xhigh) in 0x80(%rsp)
    emit_lea_abs([0x48, 0x8d, 0x05], syms["maptype_models"])
    emit([0x48, 0x8b, 0x9c, 0x24, 0x80, 0x00, 0x00, 0x00])
    emit_lea_lbl([0x48, 0x8d, 0x0d], "str_id_xhigh")
    emit([0xbf, 19, 0x00, 0x00, 0x00])
    emit_call(syms["mapaccess2_faststr"])
    emit([0x84, 0xdb])
    emit_jcc([0x0f, 0x84], "done")
    emit([0x48, 0x8b, 0x00, 0x48, 0x85, 0xc0])
    emit_jcc([0x0f, 0x84], "done")
    emit([0x48, 0x89, 0x84, 0x24, 0xf0, 0x00, 0x00, 0x00])

    # 2. Check if "gemini-4-argon-high/xhigh" (len 25) is already in 0x80(%rsp)
    emit_lea_abs([0x48, 0x8d, 0x05], syms["maptype_models"])
    emit([0x48, 0x8b, 0x9c, 0x24, 0x80, 0x00, 0x00, 0x00])
    emit_lea_lbl([0x48, 0x8d, 0x0d], "str_id_xhigh")
    emit([0xbf, 25, 0x00, 0x00, 0x00])
    emit_call(syms["mapaccess2_faststr"])
    emit([0x84, 0xdb])
    emit_jcc([0x0f, 0x85], "done")

    # 3. Create & insert Xhigh (ThinkingLevel=5, Model=orig-1) and Max (ThinkingLevel=6, Model=orig-2)
    for id_lbl, id_len, disp_lbl, disp_len, model_delta, think_lvl in [
        ("str_id_xhigh", 25, "str_disp_xhigh", 22, -1, 5),
        ("str_id_max", 23, "str_disp_max", 20, -2, 6),
    ]:
        emit_lea_abs([0x48, 0x8d, 0x05], syms["type_ModelDetails"])
        emit_call(syms["newobject"])
        emit([0x48, 0x89, 0x44, 0x24, 0x78])
        emit([0x48, 0x89, 0xc7])
        emit([0x48, 0x8b, 0xb4, 0x24, 0xf0, 0x00, 0x00, 0x00])
        emit([0xb9, 0x2d, 0x00, 0x00, 0x00, 0xf3, 0x48, 0xa5])
        emit_lea_lbl([0x48, 0x8d, 0x0d], disp_lbl)
        emit([0x48, 0x89, 0x48, 0x08])
        emit([0x48, 0xc7, 0x40, 0x10] + list(struct.pack("<I", disp_len)))
        emit([0x83, 0x40, 0x70, model_delta & 0xff])
        emit([0xc7, 0x80, 0xc4, 0x00, 0x00, 0x00] + list(struct.pack("<I", think_lvl)))
        emit_lea_abs([0x48, 0x8d, 0x05], syms["maptype_models"])
        emit([0x48, 0x8b, 0x9c, 0x24, 0x80, 0x00, 0x00, 0x00])
        emit_lea_lbl([0x48, 0x8d, 0x0d], id_lbl)
        emit([0xbf] + list(struct.pack("<I", id_len)))
        emit_call(syms["mapassign_faststr"])
        emit([0x48, 0x8b, 0x4c, 0x24, 0x78, 0x48, 0x89, 0x08])

    # 4. Append both IDs to resp.AgentModelSorts[0].Groups[0].ModelIds
    emit([0x48, 0x8b, 0x84, 0x24, 0x98, 0x02, 0x00, 0x00])
    emit([0x48, 0x83, 0x78, 0x28, 0x00])
    emit_jcc([0x0f, 0x8e], "done")
    emit([0x48, 0x8b, 0x40, 0x20, 0x48, 0x8b, 0x00, 0x48, 0x85, 0xc0])
    emit_jcc([0x0f, 0x84], "done")
    emit([0x48, 0x83, 0x78, 0x20, 0x00])
    emit_jcc([0x0f, 0x8e], "done")
    emit([0x48, 0x8b, 0x40, 0x18, 0x48, 0x8b, 0x00, 0x48, 0x85, 0xc0])
    emit_jcc([0x0f, 0x84], "done")
    emit([0x48, 0x89, 0x84, 0x24, 0xf0, 0x00, 0x00, 0x00])
    emit([0x48, 0x8b, 0x48, 0x20, 0x48, 0x89, 0x4c, 0x24, 0x50])
    emit([0x48, 0x8b, 0x50, 0x28, 0x48, 0x8b, 0x40, 0x18])
    emit([0x48, 0x8d, 0x59, 0x02, 0x48, 0x89, 0xd1, 0xbf, 0x02, 0x00, 0x00, 0x00])
    emit_lea_abs([0x48, 0x8d, 0x35], syms["type_string"])
    emit_call(syms["growslice"])
    emit([0x48, 0x8b, 0x54, 0x24, 0x50, 0x48, 0xc1, 0xe2, 0x04, 0x48, 0x8d, 0x3c, 0x10])
    emit_lea_lbl([0x48, 0x8d, 0x35], "str_id_xhigh")
    emit([0x48, 0x89, 0x37, 0x48, 0xc7, 0x47, 0x08, 25, 0x00, 0x00, 0x00])
    emit_lea_lbl([0x48, 0x8d, 0x35], "str_id_max")
    emit([0x48, 0x89, 0x77, 0x10, 0x48, 0xc7, 0x47, 0x18, 23, 0x00, 0x00, 0x00])
    emit([0x48, 0x8b, 0xb4, 0x24, 0xf0, 0x00, 0x00, 0x00])
    emit([0x48, 0x89, 0x46, 0x18, 0x48, 0x89, 0x5e, 0x20, 0x48, 0x89, 0x4e, 0x28])

    labels["done"] = len(buf)
    emit([0xc9, 0xc3])

    for lbl, text in [
        ("str_id_xhigh", b"gemini-4-argon-high/xhigh"),
        ("str_id_max", b"gemini-4-argon-high/max"),
        ("str_disp_xhigh", b"Gemini 4 Argon (Xhigh)"),
        ("str_disp_max", b"Gemini 4 Argon (Max)"),
    ]:
        labels[lbl] = len(buf)
        emit(text)

    for pos, kind, lbl in fixups:
        target_off = labels[lbl]
        rel = target_off - (pos + 4)
        buf[pos : pos + 4] = struct.pack("<i", rel)

    return body_start, bytes(buf)



def apply_argon_thinking_patches(
    data: bytearray,
    current_data: bytearray,
    applied_offsets: list[tuple[int, bytes, bytes]],
) -> bool:
    try:
        syms = resolve_symbols(data)
    except Exception as e:
        print(f"  [WARN] Argon thinking symbol resolution skipped: {e}")
        return False

    modified = False
    body_start, filter_code = build_filter_patch(syms)
    jmp_from = syms["jmp_from"]
    jmp_to = syms["jmp_to"]
    rel8 = jmp_to - (jmp_from + 2)
    assert 0 < rel8 < 0x80

    gmi_idx = syms["get_model_info_idx"]
    patches = [
        (
            "staticCatalog.GetModelInfoFromKey (strip /xhigh and /max for ThinkingLevel>=5)",
            gmi_idx,
            bytes(data[gmi_idx : gmi_idx + 32]),
            bytes([0x83, 0xbb, 0x88, 0x00, 0x00, 0x00, 0x05, 0x7c, 0x08, 0x48, 0xc7, 0x43, 0x40, 0x13, 0x00, 0x00, 0x00] + [0x90] * 15),
        ),
        (
            "CodeAssistClient.GetChatMessage (strip /xhigh and /max modelId suffix)",
            syms["chat_je_idx"],
            bytes([0x74, 0x6e]),
            bytes([0x90, 0x90]),
        ),
        (
            "CodeAssistClient.fetchAvailableModels (always invoke model injector)",
            jmp_from,
            bytes(data[jmp_from : jmp_from + 10]),
            bytes([0xeb, rel8] + [0x90] * 8),
        ),
        (
            "CodeAssistClient.filterUnavailableVertex3PModels (inject Argon Extra=5 & Max=6)",
            body_start,
            bytes(data[body_start : body_start + len(filter_code)]),
            filter_code,
        ),
    ]

    for name, idx, orig, patched in patches:
        assert len(orig) == len(patched)
        data[idx : idx + len(patched)] = patched
        applied_offsets.append((idx, orig, patched))
        if current_data[idx : idx + len(patched)] == patched:
            print(f"  [already-patched] {name} @ 0x{idx:x}")
        else:
            modified = True
            print(f"  [patched] {name} @ 0x{idx:x}")

    return modified


def refresh_live_models(pid: int) -> None:
    try:
        import ssl
        import urllib.request

        cmd = (
            open(f"/proc/{pid}/cmdline", "rb")
            .read()
            .decode("utf-8", "ignore")
            .split("\x00")
        )
        if "--csrf_token" not in cmd:
            return
        csrf = cmd[cmd.index("--csrf_token") + 1]
        ss = subprocess.check_output(["ss", "-tlnp"], text=True)
        ports = [
            int(m.group(1))
            for m in re.finditer(rf"127\.0\.0\.1:(\d+)\s+.*pid={pid},", ss)
        ]
        ctx = ssl._create_unverified_context()
        for port in ports:
            for scheme in ("https", "http"):
                try:
                    url = f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetAvailableModels"
                    hdrs = {
                        "Content-Type": "application/json",
                        "x-codeium-csrf-token": csrf,
                    }
                    c = ctx if scheme == "https" else None
                    cached = urllib.request.urlopen(
                        urllib.request.Request(url, data=b"{}", headers=hdrs, method="POST"),
                        context=c,
                        timeout=4,
                    ).read()
                    if b"gemini-4-argon-high/xhigh" in cached:
                        return
                    body = urllib.request.urlopen(
                        urllib.request.Request(url, data=b'{"forceRefresh":true}', headers=hdrs, method="POST"),
                        context=c,
                        timeout=8,
                    ).read()
                    if b"gemini-4-argon-high/xhigh" in body:
                        url2 = f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetCascadeModelConfigData"
                        urllib.request.urlopen(
                            urllib.request.Request(url2, data=b"{}", headers=hdrs, method="POST"),
                            context=c,
                            timeout=8,
                        ).read()
                        print(
                            f"  [live-models-refreshed] PID {pid} ({scheme}://127.0.0.1:{port}) -> Argon Extra & Max active"
                        )
                        return
                except Exception:
                    continue
    except Exception:
        pass


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

    # Layer 3: Gemini 4 Argon Extra (Xhigh, ThinkingLevel=5) & Max (ThinkingLevel=6)
    if apply_argon_thinking_patches(data, current_data, applied_offsets):
        modified = True

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
    refresh_live_models(pid)


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


def run_pass(
    cache: dict[str, tuple[int, int, list[tuple[int, bytes, bytes]]]],
) -> None:
    server_bins = sorted(
        glob.glob(os.path.expanduser("~/.antigravity-server/bin/*/language_server"))
    )
    if not server_bins:
        print("No language_server binaries found.")
        return

    running_maps: list[tuple[int, str]] = []
    for pid_dir in glob.glob("/proc/[0-9]*"):
        try:
            pid = int(pid_dir.split("/")[2])
            with open(f"{pid_dir}/maps", "r") as f:
                m = f.read()
            if "language_server" in m:
                running_maps.append((pid, m))
        except Exception:
            pass

    scan_all = "--all" in sys.argv
    latest_bin = server_bins[-1]
    offsets_by_realpath: dict[str, list[tuple[int, bytes, bytes]]] = {}

    for bin_path in server_bins:
        abs_path = os.path.abspath(bin_path)
        is_running = any(abs_path in m for _, m in running_maps)
        has_orig = os.path.exists(bin_path + ".orig")
        if not scan_all and bin_path != latest_bin and not is_running and has_orig:
            continue
        if not is_file_stable(bin_path):
            print(f"Skipping {bin_path} (still being written)...")
            continue
        st = os.stat(bin_path)
        cached = cache.get(abs_path)
        if cached and cached[0] == st.st_size and cached[1] == st.st_mtime_ns:
            offsets = cached[2]
        else:
            print(f"Checking {bin_path}:")
            offsets = patch_binary_file(bin_path)
            st2 = os.stat(bin_path)
            cache[abs_path] = (st2.st_size, st2.st_mtime_ns, offsets)
        offsets_by_realpath[abs_path] = offsets

    # Also live-patch any currently running language_server process in RAM
    for pid, first_map in running_maps:
        for bin_path, offsets in offsets_by_realpath.items():
            if bin_path in first_map and offsets:
                live_patch_pid(pid, offsets)


def main() -> None:
    import time

    cache: dict[str, tuple[int, int, list[tuple[int, bytes, bytes]]]] = {}
    passes = 6 if "--systemd" in sys.argv else 1
    for i in range(passes):
        run_pass(cache)
        if i + 1 < passes:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
