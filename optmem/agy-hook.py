#!/usr/bin/env python3
"""Antigravity SessionStart, PreInvocation & PreToolUse hooks for mneves75/OptMem (v1.3.3).

- SessionStart: runs `~/.optmem/memo wake --brief <repo-basename>` (or
  `~/.optmem/memo wake` outside a repo) and injects `memo`'s exact output as
  `systemMessage`.
- PreInvocation: stays silent (`{}`) on 99% of steps, acting only on two events:
  1. Post-compaction recovery (`SYSTEM CHECKPOINT` in `transcriptPath` with no
     subsequent wake): re-injects `memo wake --brief <repo>` as `systemMessage`.
  2. Pending tree compression (`has_pending_nap()` at `invocationNum == 1`):
     injects `~/.optmem/memo nap`'s exact output as `ephemeralMessage`.
- PreToolUse (`run_command`):
  1. Blocks subagents from running `memo` (`decision: "deny"`).
  2. Transparently prepends `[<project>] ` via `overwrite` when a `memo note`
      inside a repository omits the project name (and is not `[global]`),
     ensuring `memo wake --brief <project>` always retrieves it.
"""

import functools
import json
import os
import re
import subprocess
import sys
import unicodedata

MEMO = os.path.expanduser("~/.optmem/memo")
HOME = os.path.normpath(os.path.expanduser("~"))
PROJECTS_DIR = os.path.join(HOME, "projects")
LOG_REC = 320
TREE_REC = 288
ENTRY_CHARS = 280

IGNORED_BASENAMES = frozenset(
    {
        "",
        "gohans-linux",
        "projects",
        "config",
        ".gemini",
        ".optmem",
        "tmp",
    }
)

SAFE_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")
NOTE_TOKEN_RE = re.compile(r"[^\W]{2,}")
PROJ_TOKEN_RE = re.compile(r"[^\W_]{2,}")
PROJ_ALL_SEGMENTS_RE = re.compile(r"[^\W_]+")
GLOBAL_TAG_RE = re.compile(r"^\[global\](?:[\s:]|$)", re.IGNORECASE)

MEMO_SUBCMDS = r"(?:init|wake|note|nap|recall|zoom|forget|config|import|check|find|brief)"
WS = r"(?:[ \t]|\\\r?\n)+"
OPT_WS = r"(?:[ \t]|\\\r?\n)*"
OPTMEM_DIR_PAT = r"\.o(?:\\\r?\n|\\)?['\"]?p(?:\\\r?\n|\\)?['\"]?t(?:\\\r?\n|\\)?['\"]?m(?:\\\r?\n|\\)?['\"]?e(?:\\\r?\n|\\)?['\"]?m['\"]?"
CMD_PREFIX_PAT = (
    rf"(?P<sep>^|[;&|\n(`{{!)]){OPT_WS}"
    r"(?:"
    rf"(?:if|then|elif|else|while|until|do|time|command|builtin|exec|eval|nohup|source|\.|coproc|export|declare|local|readonly|typeset){WS}"
    rf"|(?:nice|xargs){WS}(?:-[A-Za-z0-9-]+{WS}(?:[^-\s][^\s;&|()`]*{WS})?)*"
    rf"|timeout{WS}(?:-(?:k|s){WS}[^\s;&|()`]+{WS}|--[A-Za-z0-9-]+(?:=[^\s;&|()`]+)?{WS}|-[A-Za-z0-9-]+{WS})*[^-\s][^\s;&|()`]*{WS}"
    rf"|[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s'\";&|()`])*{WS}"
    r")*"
)
INTERP_PREFIX_PAT = (
    rf"(?:(?:(?:/usr)?/bin/)?(?:env|python3?(?:\.\d+)?|(?:ba|z|da|k)?sh|uv{WS}run){WS}"
    rf"(?:(?:-(?:u|C|S|W|X)|--(?:python|with|directory|project)){WS}[^\s;&|()`]+{WS}|(?:--?[A-Za-z0-9-]+(?:=[^\s;&|()`]+)?|[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s'\";&|()`])*){WS})*)*"
)
MEMO_EXEC_PREFIX = (
    rf"{CMD_PREFIX_PAT}"
    rf"{INTERP_PREFIX_PAT}"
    rf"(?:['\"]?(?:(?:~|\$HOME|\$\{{HOME\}}|\$[A-Za-z_][A-Za-z0-9_]*|\$\{{[A-Za-z_][A-Za-z0-9_]*\}}|\.\.?|/[^\s'\";&|()`]+)/(?:\./)*)?(?:{OPTMEM_DIR_PAT}/(?:\./)*)?['\"]?m(?:\\\r?\n|\\)?['\"]?e(?:\\\r?\n|\\)?['\"]?m(?:\\\r?\n|\\)?['\"]?o['\"]?)"
)
MEMO_CMD_RE = re.compile(rf"{MEMO_EXEC_PREFIX}(?:{WS}{MEMO_SUBCMDS}\b|{WS}--?[A-Za-z0-9-]|{OPT_WS}(?:[;&|\r\n)`}}]|$))")
SHELL_DASH_C_RE = re.compile(
    rf"{CMD_PREFIX_PAT}"
    rf"{INTERP_PREFIX_PAT}"
    rf"(?:(?:/usr)?/bin/)?(?P<interp>(?:ba|z|da|k)?sh|python3?(?:\.\d+)?|bun|node|perl|ruby|eval){OPT_WS}"
    rf"(?:(?:-(?:W|X){WS}[^\s;&|()`]+|--?[A-Za-z0-9-]+(?:=[^\s;&|()`]+)?){WS})*"
    r"(?:\"(?P<dq>(?:\\.|[^\"\\])*)\"|'(?P<sq>(?:[^']|'\\''|'\"'\"')*)'|\$'(?P<ac>(?:\\.|[^'\\])*)')"
    r"(?P<trailing>[^\r\n;&|)`}}]*)"
)
INTERP_STDIN_RE = re.compile(
    rf"{CMD_PREFIX_PAT}"
    rf"{INTERP_PREFIX_PAT}"
    rf"(?:(?:/usr)?/bin/)?(?:(?:ba|z|da|k)?sh|python3?(?:\.\d+)?|bun|node|perl|ruby)(?:{WS}[-\w.=]+)*{WS}(?:<<-?{OPT_WS}['\"\\]?[A-Za-z0-9_.-]+['\"]?|<<<|<\()"
)
OPTMEM_MEMORY_PATH_RE = re.compile(
    rf"(?:~|\$HOME|\$\{{HOME\}}|/[^\s'\";&|()`]+)/{OPTMEM_DIR_PAT}/memory(?:/|\b)|(?:^|[\s'\"=/]){OPTMEM_DIR_PAT}/memory(?:/|\b)|(?:^|[\s'\"=/])memory/(?:LOG\.txt|TREE\b|config\b|\.lock\b)|\bMEMORY_DIR\b"
)
OPTMEM_MUTATE_RE = re.compile(
    rf"{CMD_PREFIX_PAT}"
    rf"(?:(?:rm|mv|cp|dd|truncate|chmod|chown|tee|ln|install|rsync|unlink|shred|cd|find|xargs|sed|perl|touch|mkdir|rmdir)\b(?:\\\r?\n|[^\r\n;&|)`}}])*{OPTMEM_DIR_PAT}(?:/|\b|--?|\*|\?)"
    rf"|[A-Za-z_][A-Za-z0-9_]*=(?:\\\r?\n|[^\r\n;&|)`}}])*{OPTMEM_DIR_PAT}(?:/|\b)"
    rf"|(?:\\\r?\n|[^\r\n;&|)`}}])*>[>&]?{OPT_WS}['\"]?(?:(?:~|\$HOME|\$\{{HOME\}}|/[^\s'\";&|()`]+)/)?{OPTMEM_DIR_PAT}(?:/|\b))"
)
SUBAGENT_WILDCARD_RE = re.compile(
    rf"(?:\.o[^\s;&|()`]*[*?\[]|[*?\[][^\s;&|()`]*optmem|(?:\.opt|/home/)[^\s;&|()`]*/m[^\s;&|()`]*[*?\[]|[^\s;&|()`]*[*?\[][^\s;&|()`]*{WS}{MEMO_SUBCMDS}\b)"
)
SUBAGENT_SAFE_READONLY_RE = re.compile(
    r"^\s*(?:grep|egrep|fgrep|rg|diff|wc|file|stat)\s+"
    r"(?:-[A-Za-z0-9]+\s+)*"
    r"(?:\"[^\";&|`$><\r\n]*\"|'[^'\r\n]*'|[A-Za-z0-9_./~-]+)"
    r"(?:\s+(?:~|\$HOME|/home/[A-Za-z0-9_.-]+)/\.optmem/(?:memo|agy-hook\.py|test_agy_hook\.py))+\s*$"
)
SHELL_PREFIX_KW_RE = re.compile(
    r"(?:if|then|elif|else|while|until|do|time|command|builtin|exec|eval|nohup|nice|source|\.|xargs|coproc|export|declare|local|readonly|typeset)(?=\s)"
)
CASE_KW_RE = re.compile(r"case(?=\s)")
ESAC_KW_RE = re.compile(r"esac(?=\s|[;&|)\r\n`}]|$)")

CD_TOKEN_RE = re.compile(
    r"cd(?:\s+-[LP]+)*(?:\s+--)?(?:\s+(?:\"((?:\\.|[^\"\\\r\n])*)\"|'([^'\r\n]*)'|([^\s;&|()\r\n`#]+)))?(?=\s*(?:#[^\r\n]*)?(?:[;&|)\r\n`}]|$))"
)

HEREDOC_OP_RE = re.compile(r"<<(-?)\s*(?:(['\"])([A-Za-z0-9_.-]+)\2|(\\?)([A-Za-z0-9_.-]+))(?=\s|[;&|<>()\r\n]|$)")

NOTE_STATEMENT_RE = re.compile(
    rf"(?P<cmd_head>{MEMO_EXEC_PREFIX}{WS}note{WS})"
    r"(?:"
    rf"(?P<hd_lead>-{OPT_WS}<<(?P<hd_dash>-?){OPT_WS})(?:(?P<hd_q>['\"])(?P<hd_delim_q>[A-Za-z0-9_.-]+)(?P=hd_q)|(?P<hd_bs>\\?)(?P<hd_delim_u>[A-Za-z0-9_.-]+))"
    r"(?P<hd_rest>[^\r\n]*\r?\n)(?P<hd_body>[^\r\n]+)"
    r"(?P<hd_tail>\r?\n(?P<hd_indent>\t*)(?:(?P=hd_delim_q)|(?P=hd_delim_u))(?=\r?\n|$))"
    r"|"
    rf"(?P<arg_lead>(?:-{WS})?<<<{OPT_WS}|(?:--{WS})?)"
    r"(?:\"(?P<arg_dq>(?:\\.|[^\"\\\r\n])+)\"|'(?P<arg_sq>(?:[^'\r\n]|'\\''|'\"'\"')+)'|\$'(?P<arg_ac>(?:\\.|[^'\\\r\n])+)')"
    r"(?=\s|[;&|)\r\n`}]|$)"
    r")"
)


def read_payload():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def is_subagent(payload):
    # Hosts that know the session tree (OpenCode plugin) say so explicitly.
    if payload.get("isSubagent") is True:
        return True
    art = payload.get("artifactDirectoryPath") or ""
    transcript = payload.get("transcriptPath") or ""
    if not art and transcript and "/.system_generated/" in transcript:
        art = transcript.split("/.system_generated/", 1)[0]
    if art:
        base_msg_dir = os.path.join(art, ".system_generated", "messages")
        for msg_dir in (base_msg_dir, os.path.join(base_msg_dir, "undelivered")):
            try:
                names = os.listdir(msg_dir)
            except Exception:
                continue
            for name in names:
                if not name.endswith(".json") or name == "read.json":
                    continue
                try:
                    p = os.path.join(msg_dir, name)
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        msg = json.load(f)
                    if not isinstance(msg, dict):
                        continue
                    title = (msg.get("renderDetails") or {}).get("messageTitle") or ""
                    tool_name = (
                        (((msg.get("sourceMetadata") or {}).get("tool") or {}).get("toolCall") or {}).get("name")
                        or msg.get("source")
                        or ""
                    )
                    if title == "Message from Parent Agent" or tool_name == "invoke_subagent":
                        return True
                except Exception:
                    continue
    if transcript:
        candidates = [transcript]
        if transcript.endswith("transcript.jsonl"):
            candidates.append(transcript[:-16] + "transcript_full.jsonl")
        for t_path in candidates:
            try:
                with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline()
                step0 = json.loads(first_line) if first_line.strip() else {}
                if isinstance(step0, dict):
                    content = step0.get("content") or ""
                    if (
                        step0.get("source") == "SYSTEM"
                        and "injected by a SessionStart hook" not in content
                        and (
                            "content=You are a subagent" in content
                            or ("[Message]" in content and "You are a subagent" in content)
                        )
                    ):
                        return True
                    if "content" not in (step0.get("truncated_fields") or []):
                        break
            except Exception:
                continue
    return False


def _fold(text):
    text = text.lower()
    if text.isascii():
        return text
    return NON_ASCII_RE.sub(
        lambda m: "" if unicodedata.category(m.group()) == "Mn" else m.group(),
        unicodedata.normalize("NFKD", text),
    )


def _expand_shell_path(raw_path):
    p = re.sub(r"^\$(?:HOME|\{HOME\})(?=/|$)", HOME, raw_path.strip())
    return os.path.expanduser(p)


def _resolve_git_repo_root(target):
    probe = target
    while probe and probe not in ("/", HOME, PROJECTS_DIR, "/tmp") and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not probe or probe in ("/", HOME, PROJECTS_DIR, "/tmp") or not os.path.isdir(probe):
        return ""
    try:
        real_probe = os.path.realpath(probe)
        if real_probe in ("/", HOME, PROJECTS_DIR, "/tmp"):
            return ""
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
        }
        clean_env["GIT_TERMINAL_PROMPT"] = "0"
        common_dir = subprocess.check_output(
            ["git", "-c", "core.fsmonitor=false", "-C", real_probe, "rev-parse", "--git-common-dir"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            env=clean_env,
        ).strip()
        if not common_dir:
            return ""
        abs_common = os.path.normpath(os.path.join(real_probe, common_dir))
        mod_marker = os.sep + ".git" + os.sep + "modules"
        if mod_marker + os.sep in abs_common or abs_common.endswith(mod_marker):
            repo_root = abs_common.split(mod_marker, 1)[0]
        elif os.path.basename(abs_common) == ".git":
            repo_root = os.path.dirname(abs_common)
        else:
            repo_root = abs_common
        repo_root = os.path.normpath(repo_root)
        if repo_root in ("/", HOME, PROJECTS_DIR, "/tmp"):
            return ""
        return repo_root
    except Exception:
        return ""


@functools.lru_cache(maxsize=64)
def _resolve_candidate_project(raw_path):
    if not raw_path or raw_path == "-":
        return ""
    try:
        target = os.path.normpath(os.path.abspath(_expand_shell_path(raw_path)))
        real_target = os.path.normpath(os.path.realpath(target))
    except Exception:
        return ""
    if target in ("/", HOME, PROJECTS_DIR, "/tmp") or real_target in ("/", HOME, PROJECTS_DIR, "/tmp"):
        return ""
    for excluded in (os.path.join(HOME, ".gemini"), os.path.join(HOME, ".optmem")):
        real_exc = os.path.normpath(os.path.realpath(excluded))
        if (
            target == excluded
            or target.startswith(excluded + os.sep)
            or real_target == real_exc
            or real_target.startswith(real_exc + os.sep)
        ):
            return ""

    # 1. Git repository, worktree, or submodule: resolve main superproject via --git-common-dir
    git_root = _resolve_git_repo_root(target)
    if git_root:
        base = os.path.basename(git_root.rstrip("/"))
        if base.endswith(".git") and len(base) > 4:
            base = base[:-4]
        if base not in IGNORED_BASENAMES and SAFE_PROJECT_RE.match(base):
            return base

    # 2. Under ~/projects/<project-name>(/...): always take the top-level project folder
    if target.startswith(PROJECTS_DIR + os.sep):
        rel = os.path.relpath(target, PROJECTS_DIR)
        first_part = rel.split(os.sep)[0]
        if (
            first_part
            and first_part not in (".", "..")
            and first_part not in IGNORED_BASENAMES
            and SAFE_PROJECT_RE.match(first_part)
        ):
            return first_part
    return ""


def _base_working_dir(payload):
    args = ((payload.get("toolCall") or {}).get("args") or {})
    candidates = [
        c
        for c in (args.get("Cwd"), args.get("cwd"), payload.get("cwd"), *(payload.get("workspacePaths") or []))
        if c
    ]
    for c in candidates:
        if _resolve_candidate_project(c):
            return _expand_shell_path(c)
    return _expand_shell_path(candidates[0]) if candidates else HOME


def detect_project(payload):
    seen = set()
    args = ((payload.get("toolCall") or {}).get("args") or {})
    for candidate in (args.get("Cwd"), args.get("cwd"), payload.get("cwd"), *(payload.get("workspacePaths") or [])):
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        proj = _resolve_candidate_project(candidate)
        if proj:
            return proj
    return ""


def _shell_state_at(cmd, limit, base_dir, in_heredoc=False, prev_dir=None, changed_cd=False):
    in_sq = False
    in_dq = False
    in_ac = False
    arith_depth = 0
    case_depth = 0
    stack = [(base_dir, prev_dir or base_dir, changed_cd, False, None)]
    pending_heredocs = []
    at_cmd_start = True
    at_token_start = True
    i = 0
    n = min(limit, len(cmd))
    while i < n:
        ch = cmd[i]
        if in_heredoc and len(stack) == 1:
            if ch == "\\":
                i += 2
                continue
            if cmd[i : i + 3] == "$((":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, False, "$))"))
                arith_depth += 1
                at_cmd_start = False
                at_token_start = True
                i += 3
                continue
            if cmd[i : i + 2] == "$(":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, False, "$)"))
                at_cmd_start = True
                at_token_start = True
                i += 2
                continue
            if ch == "`":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, False, "`"))
                at_cmd_start = True
                at_token_start = True
                i += 1
                continue
            i += 1
            continue
        if in_sq:
            if ch == "'":
                in_sq = False
            i += 1
            continue
        if in_ac:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_ac = False
            i += 1
            continue
        if in_dq:
            if ch == "\\":
                i += 2
                continue
            if cmd[i : i + 3] == "$((":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, True, "$))"))
                in_dq = False
                arith_depth += 1
                at_cmd_start = False
                at_token_start = True
                i += 3
                continue
            if cmd[i : i + 2] == "$(":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, True, "$)"))
                in_dq = False
                at_cmd_start = True
                at_token_start = True
                i += 2
                continue
            if cmd[i : i + 2] == "${":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, True, "}"))
                in_dq = False
                at_cmd_start = False
                at_token_start = False
                i += 2
                continue
            if ch == "`":
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, True, "`"))
                in_dq = False
                at_cmd_start = True
                at_token_start = True
                i += 1
                continue
            if ch == '"':
                in_dq = False
            i += 1
            continue

        if ch == "\\":
            if cmd[i + 1 : i + 2] == "\n":
                i += 2
                continue
            if cmd[i + 1 : i + 3] == "\r\n":
                i += 3
                continue
            i += 2
            at_cmd_start = False
            at_token_start = False
            continue
        if at_token_start and ch == "#" and stack[-1][4] != "}":
            nl = cmd.find("\n", i)
            if nl == -1 or n <= nl:
                return False, stack[-1][0], stack[-1][2]
            i = nl
            continue
        if cmd[i : i + 2] == "$'":
            in_ac = True
            at_cmd_start = False
            at_token_start = False
            i += 2
            continue
        if cmd[i : i + 3] == "$((":
            cur_d, prev_d, chg_d, _, _ = stack[-1]
            stack.append((cur_d, prev_d, chg_d, False, "$))"))
            arith_depth += 1
            at_cmd_start = False
            at_token_start = True
            i += 3
            continue
        if cmd[i : i + 2] == "$(":
            cur_d, prev_d, chg_d, _, _ = stack[-1]
            stack.append((cur_d, prev_d, chg_d, False, "$)"))
            at_cmd_start = True
            at_token_start = True
            i += 2
            continue
        if cmd[i : i + 2] == "${":
            cur_d, prev_d, chg_d, _, _ = stack[-1]
            stack.append((cur_d, prev_d, chg_d, False, "}"))
            at_cmd_start = False
            at_token_start = False
            i += 2
            continue
        if cmd[i : i + 2] == "((":
            cur_d, prev_d, chg_d, _, _ = stack[-1]
            stack.append((cur_d, prev_d, chg_d, False, "))"))
            arith_depth += 1
            at_cmd_start = False
            at_token_start = True
            i += 2
            continue
        if arith_depth > 0 and len(stack) > 1 and stack[-1][4] in ("))", "$))") and cmd[i : i + 2] == "))":
            _, _, _, parent_dq, closer = stack.pop()
            in_dq = parent_dq
            arith_depth -= 1
            at_cmd_start = False
            at_token_start = closer == "))" and not in_dq
            i += 2
            continue
        if ch == "'":
            in_sq = True
            at_cmd_start = False
            at_token_start = False
            i += 1
            continue
        if ch == '"':
            in_dq = True
            at_cmd_start = False
            at_token_start = False
            i += 1
            continue
        if ch in (" ", "\t", "\r"):
            at_token_start = True
            i += 1
            continue
        if arith_depth == 0 and ch == "<":
            if cmd[i : i + 3] == "<<<":
                i += 3
                at_cmd_start = False
                at_token_start = True
                continue
            if cmd[i : i + 2] == "<<":
                m_hd = HEREDOC_OP_RE.match(cmd, i)
                if m_hd:
                    delim = m_hd.group(3) or m_hd.group(5)
                    is_quoted_hd = bool(m_hd.group(2) or m_hd.group(4))
                    pending_heredocs.append((delim, bool(m_hd.group(1)), is_quoted_hd))
                    i = m_hd.end()
                    at_cmd_start = False
                    at_token_start = True
                    continue
        if ch == "(":
            cur_d, prev_d, chg_d, _, _ = stack[-1]
            stack.append((cur_d, prev_d, chg_d, False, ")"))
            at_cmd_start = True
            at_token_start = True
            i += 1
            continue
        if ch == ")":
            if case_depth > 0 and (len(stack) == 1 or stack[-1][4] != ")"):
                at_cmd_start = True
                at_token_start = True
                i += 1
                continue
            closer = None
            if len(stack) > 1 and stack[-1][4] in (")", "$)"):
                _, _, _, parent_dq, closer = stack.pop()
                in_dq = parent_dq
            at_cmd_start = False
            at_token_start = closer == ")" and not in_dq
            i += 1
            continue
        if ch == "}" and len(stack) > 1 and stack[-1][4] == "}":
            _, _, _, parent_dq, _ = stack.pop()
            in_dq = parent_dq
            at_cmd_start = False
            at_token_start = False
            i += 1
            continue
        if ch == "`":
            if len(stack) > 1 and stack[-1][4] == "`":
                _, _, _, parent_dq, _ = stack.pop()
                in_dq = parent_dq
                at_cmd_start = False
                at_token_start = False
            else:
                cur_d, prev_d, chg_d, _, _ = stack[-1]
                stack.append((cur_d, prev_d, chg_d, False, "`"))
                at_cmd_start = True
                at_token_start = True
            i += 1
            continue
        if ch == "\n":
            i += 1
            while pending_heredocs:
                delim, strip_tabs, is_quoted_hd = pending_heredocs.pop(0)
                lead_pat = r"\t*" if strip_tabs else r""
                pat = re.compile(rf"^{lead_pat}{re.escape(delim)}(?=\r?\n|$)", re.MULTILINE)
                m_end = pat.search(cmd, i)
                end_body = m_end.start() if m_end else len(cmd)
                if not m_end:
                    body_after = len(cmd) + 1
                else:
                    line_end = cmd.find("\n", m_end.end())
                    body_after = len(cmd) if line_end == -1 else line_end + 1
                if n < body_after:
                    cur_d, prev_d, chg_d, _, _ = stack[-1]
                    if not is_quoted_hd and n <= end_body:
                        return _shell_state_at(
                            cmd[i:n], n - i, cur_d, in_heredoc=True, prev_dir=prev_d, changed_cd=chg_d
                        )
                    return False, cur_d, chg_d
                i = body_after
            at_cmd_start = True
            at_token_start = True
            continue
        if ch in ";&|" and stack[-1][4] != "}":
            at_cmd_start = True
            at_token_start = True
            i += 1
            continue
        if ch == "{" and at_cmd_start and i + 1 < len(cmd) and cmd[i + 1] in (" ", "\t", "\n", "\r"):
            at_cmd_start = True
            at_token_start = True
            i += 1
            continue
        if at_cmd_start:
            m_case = CASE_KW_RE.match(cmd, i)
            if m_case and m_case.end() <= n:
                case_depth += 1
                i = m_case.end()
                at_cmd_start = False
                at_token_start = True
                continue
            m_esac = ESAC_KW_RE.match(cmd, i)
            if m_esac and m_esac.end() <= n:
                case_depth = max(0, case_depth - 1)
                i = m_esac.end()
                at_cmd_start = False
                at_token_start = True
                continue
            m_kw = SHELL_PREFIX_KW_RE.match(cmd, i)
            if m_kw and m_kw.end() <= n:
                i = m_kw.end()
                at_cmd_start = True
                at_token_start = True
                continue
            m_cd = CD_TOKEN_RE.match(cmd, i)
            if m_cd and m_cd.end() <= n:
                dq_cd, sq_cd, uq_cd = m_cd.group(1), m_cd.group(2), m_cd.group(3)
                raw_cd = (dq_cd or sq_cd or uq_cd or "").strip()
                is_sq_cd = sq_cd is not None
                is_dq_cd = dq_cd is not None
                rem_after_home = re.sub(r"^\$(?:HOME|\{HOME\})(?=/|$)", "", raw_cd)
                has_unexpanded = (not is_sq_cd) and any(c in rem_after_home for c in ("$", "`", "\\"))
                if not has_unexpanded:
                    cur_dir, prev_dir, _, parent_dq, closer = stack[-1]
                    if (dq_cd is None and sq_cd is None and not uq_cd) or (
                        raw_cd == "~" and not is_sq_cd and not is_dq_cd
                    ):
                        stack[-1] = (HOME, cur_dir, True, parent_dq, closer)
                    elif raw_cd == "" and (is_sq_cd or is_dq_cd):
                        pass
                    elif raw_cd == "-":
                        stack[-1] = (prev_dir, cur_dir, True, parent_dq, closer)
                    elif is_sq_cd and (raw_cd.startswith("~") or raw_cd.startswith("$")):
                        pass
                    elif is_dq_cd and raw_cd.startswith("~"):
                        pass
                    else:
                        if is_sq_cd:
                            expanded = raw_cd
                        elif is_dq_cd:
                            expanded = re.sub(r"^\$(?:HOME|\{HOME\})(?=/|$)", HOME, raw_cd)
                        else:
                            expanded = _expand_shell_path(raw_cd)
                        new_dir = (
                            expanded
                            if os.path.isabs(expanded)
                            else os.path.normpath(os.path.join(cur_dir, expanded))
                        )
                        stack[-1] = (new_dir, cur_dir, True, parent_dq, closer)
                i = m_cd.end()
                at_cmd_start = False
                at_token_start = True
                continue
            at_cmd_start = False
        at_token_start = False
        i += 1
    cur_dir, _, changed_cd, _, _ = stack[-1]
    if in_heredoc and len(stack) == 1:
        return False, cur_dir, changed_cd
    return (not in_sq and not in_dq and not in_ac), cur_dir, changed_cd


def _detect_project_at_offset(cmd, offset, payload, default_project):
    base_dir = _base_working_dir(payload)
    is_unquoted, cur_dir, changed_cd = _shell_state_at(cmd, offset, base_dir)
    if not is_unquoted:
        return None
    if changed_cd:
        return _resolve_candidate_project(cur_dir) or default_project
    return default_project


def _already_mentions_project_or_global(note_text, project):
    stripped = note_text.strip()
    if GLOBAL_TAG_RE.match(stripped):
        return True
    if stripped.lower().startswith(f"[{project.lower()}]"):
        return True
    folded_note = _fold(stripped)
    folded_proj = _fold(project)
    all_segments = PROJ_ALL_SEGMENTS_RE.findall(folded_proj)
    if not all_segments:
        return True
    if any(len(seg) < 2 for seg in all_segments):
        return bool(re.search(rf"(?<![0-9a-z_]){re.escape(folded_proj)}(?![0-9a-z_])", folded_note))
    note_tokens = set(NOTE_TOKEN_RE.findall(folded_note))
    if folded_proj in note_tokens:
        return True
    proj_tokens = PROJ_TOKEN_RE.findall(folded_proj)
    return bool(proj_tokens) and all(t in note_tokens for t in proj_tokens)


def _unescaped_utf8_len(text, kind):
    if kind == "dq":
        text = re.sub(r'\\([\"\\$`])', r"\1", text)
    elif kind == "sq":
        text = text.replace("'\\''", "'").replace("'\"'\"'", "'")
    elif kind == "ac":
        text = re.sub(r"\\(['\"\\])", r"\1", text)
    return len(text.encode("utf-8"))


def run_memo(args, timeout=5):
    try:
        proc = subprocess.run(
            [MEMO] + list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except Exception:
        return 1, ""


def memory_dir():
    return os.path.expanduser(os.environ.get("MEMORY_DIR") or "~/.optmem/memory")


def has_pending_nap():
    d = memory_dir()
    try:
        t = os.path.getsize(os.path.join(d, "LOG.txt")) // LOG_REC
    except OSError:
        return False
    size = 2
    while size <= t:
        try:
            have = os.path.getsize(os.path.join(d, "TREE", str(size))) // TREE_REC
        except OSError:
            have = 0
        if t // size > have:
            return True
        size *= 2
    return False


def _iter_lines_reverse(path, chunk_size=65536):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        rem = b""
        while pos > 0:
            read_len = min(chunk_size, pos)
            pos -= read_len
            f.seek(pos)
            chunk = f.read(read_len)
            nl_idx = chunk.find(b"\n")
            if nl_idx == -1:
                rem = chunk + rem
                continue
            buf = chunk + rem
            rem = buf[:nl_idx]
            if b'"CHECKPOINT"' not in buf and b"You are awake." not in buf:
                continue
            for line in reversed(buf[nl_idx + 1 :].split(b"\n")):
                if line.strip():
                    yield line
        if rem.strip():
            yield rem


def _is_wake_step(step):
    src = step.get("source")
    typ = step.get("type")
    content = step.get("content") or ""
    if src == "SYSTEM_SDK" and typ == "SYSTEM_MESSAGE":
        return "You are awake." in content
    if src == "MODEL" and typ == "GENERIC":
        norm = content.replace("\r\n", "\n")
        return "Command exited with code 0." in norm and (
            norm.rstrip().endswith("You are awake.") or "\nYou are awake.\n" in norm
        )
    return False


def needs_post_compact_wake(payload):
    transcript = payload.get("transcriptPath") or ""
    if not transcript or not os.path.exists(transcript):
        return False
    candidates = [transcript]
    if transcript.endswith("transcript.jsonl"):
        full_t = transcript[:-16] + "transcript_full.jsonl"
        if os.path.exists(full_t):
            candidates.insert(0, full_t)
    for t_path in candidates:
        try:
            for raw_line in _iter_lines_reverse(t_path):
                if b'"CHECKPOINT"' not in raw_line and b"You are awake." not in raw_line:
                    continue
                step = json.loads(raw_line.decode("utf-8", errors="ignore"))
                if step.get("type") == "CHECKPOINT":
                    return True
                if _is_wake_step(step):
                    return False
        except Exception:
            continue
    return False


def _wake_system_message(payload):
    project = detect_project(payload)
    cmd = ["wake", "--brief", project] if project else ["wake"]
    _, wake_out = run_memo(cmd)
    if not wake_out:
        return {}
    return {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": wake_out,
                }
            }
        ]
    }


def handle_session_start(payload):
    if is_subagent(payload):
        return {}
    return _wake_system_message(payload)


def handle_pre_invocation(payload):
    if is_subagent(payload):
        return {}
    if needs_post_compact_wake(payload):
        return _wake_system_message(payload)
    if payload.get("invocationNum", 1) == 1 and has_pending_nap():
        _, nap_out = run_memo(["nap"])
        if nap_out and nap_out != "Nothing left to compress.":
            return {
                "injectSteps": [
                    {
                        "ephemeralMessage": nap_out,
                    }
                ]
            }
    return {}


def _extract_dash_c_inner(m):
    if m.group("dq") is not None:
        return re.sub(r'\\([\"\\$`])', r"\1", m.group("dq"))
    if m.group("ac") is not None:
        return re.sub(r"\\(['\"\\])", r"\1", m.group("ac"))
    return (m.group("sq") or "").replace("'\\''", "'").replace("'\"'\"'", "'")


def _payload_cwd_touches_optmem(payload):
    args = ((payload.get("toolCall") or {}).get("args") or {})
    optmem_root = os.path.realpath(os.path.expanduser("~/.optmem"))
    mem_root = os.path.realpath(memory_dir())
    for c in (args.get("Cwd"), args.get("cwd"), payload.get("cwd"), *(payload.get("workspacePaths") or [])):
        if not c:
            continue
        try:
            expanded = os.path.realpath(os.path.abspath(_expand_shell_path(str(c))))
            for root in (optmem_root, mem_root):
                if expanded == root or expanded.startswith(root + os.sep):
                    return True
        except Exception:
            continue
    return False


def _has_real_memo_invocation(cmd, base_dir, depth=0):
    if depth > 2:
        return False
    for m in MEMO_CMD_RE.finditer(cmd):
        is_unquoted, _, _ = _shell_state_at(cmd, m.end("sep"), base_dir)
        if is_unquoted:
            return True
    for m in SHELL_DASH_C_RE.finditer(cmd):
        is_unquoted, cur_dir, _ = _shell_state_at(cmd, m.end("sep"), base_dir)
        if not is_unquoted:
            continue
        inner = _extract_dash_c_inner(m)
        trailing = m.group("trailing") or ""
        interp = m.group("interp") or ""
        if interp.startswith(("python", "bun", "node", "perl", "ruby")):
            if ".optmem" in inner or re.search(rf"\bmemo\b.*?\b{MEMO_SUBCMDS}\b", inner):
                return True
        elif _has_real_memo_invocation(inner, cur_dir, depth + 1):
            return True
        if trailing and (
            ".optmem" in re.sub(r"""\\(?=[^\s])|['"]""", "", trailing)
            or _has_real_memo_invocation(trailing, cur_dir, depth + 1)
        ):
            return True
    for m in INTERP_STDIN_RE.finditer(cmd):
        is_unquoted, _, _ = _shell_state_at(cmd, m.end("sep"), base_dir)
        if not is_unquoted:
            continue
        tail = cmd[m.end() :]
        norm_tail = re.sub(r"""\\(?=[^\s])|['"]""", "", tail)
        if ".optmem" in norm_tail or re.search(rf"\bmemo\b.*?\b{MEMO_SUBCMDS}\b", norm_tail):
            return True
    return False


def _touches_optmem_memory_store(cmd, base_dir, depth=0):
    if depth > 2:
        return False
    norm_cmd = re.sub(r"""\\(?=[^\s])|['"]""", "", cmd)
    if (
        OPTMEM_MEMORY_PATH_RE.search(cmd)
        or OPTMEM_MEMORY_PATH_RE.search(norm_cmd)
        or SUBAGENT_WILDCARD_RE.search(norm_cmd)
    ):
        return True
    for m in OPTMEM_MUTATE_RE.finditer(cmd):
        is_unquoted, _, _ = _shell_state_at(cmd, m.end("sep"), base_dir)
        if is_unquoted:
            return True
    for m in SHELL_DASH_C_RE.finditer(cmd):
        is_unquoted, cur_dir, _ = _shell_state_at(cmd, m.end("sep"), base_dir)
        if not is_unquoted:
            continue
        inner = _extract_dash_c_inner(m)
        trailing = m.group("trailing") or ""
        if _touches_optmem_memory_store(inner, cur_dir, depth + 1) or (
            trailing and _touches_optmem_memory_store(trailing, cur_dir, depth + 1)
        ):
            return True
    for m in INTERP_STDIN_RE.finditer(cmd):
        is_unquoted, cur_dir, _ = _shell_state_at(cmd, m.end("sep"), base_dir)
        if not is_unquoted:
            continue
        tail = cmd[m.end() :]
        if _touches_optmem_memory_store(tail, cur_dir, depth + 1):
            return True
    return False


def handle_pre_tool_use(payload):
    tool_call = payload.get("toolCall") or {}
    tool_name = tool_call.get("name") or ""
    args = tool_call.get("args") or {}
    if tool_name in ("write_file", "edit_file", "read_file"):
        raw_p = args.get("Path") or args.get("TargetFile") or args.get("AbsolutePath") or ""
        if raw_p:
            try:
                real_p = os.path.realpath(os.path.abspath(_expand_shell_path(str(raw_p))))
                mem_root = os.path.realpath(memory_dir())
                optmem_root = os.path.realpath(os.path.expanduser("~/.optmem"))
                in_mem = real_p == mem_root or real_p.startswith(mem_root + os.sep)
                in_optmem = real_p == optmem_root or real_p.startswith(optmem_root + os.sep)
                if tool_name in ("write_file", "edit_file") and (in_mem or ( in_optmem and is_subagent(payload))):
                    return {
                        "decision": "deny",
                        "reason": "Never edit or delete anything under ~/.optmem/memory: the tool manages it.",
                    }
                if tool_name == "read_file" and in_mem and is_subagent(payload):
                    return {
                        "decision": "deny",
                        "reason": "Subagents must never read or write ~/.optmem/memory.",
                    }
            except Exception:
                pass
        return {"decision": "allow"}
    if tool_name != "run_command":
        return {"decision": "allow"}
    cmd = args.get("CommandLine") or ""
    norm_cmd = re.sub(r"""\\\r?\n|\\(?=[^\s])|['"]""", "", cmd)
    cwd_touches = _payload_cwd_touches_optmem(payload)
    if (
        not cwd_touches
        and "memo" not in norm_cmd
        and ".opt" not in norm_cmd
        and "MEMORY_DIR" not in norm_cmd
        and "LOG.txt" not in norm_cmd
        and "TREE" not in norm_cmd
        and not any(c in norm_cmd for c in ("*", "?", "[", "$"))
    ):
        return {"decision": "allow"}
    base_dir = _base_working_dir(payload)
    if is_subagent(payload):
        if SUBAGENT_SAFE_READONLY_RE.match(cmd) and not cwd_touches:
            return {"decision": "allow"}
        has_subcmd_with_var = bool(
            re.search(rf"(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{{[A-Za-z_][A-Za-z0-9_]*\}})\s*{MEMO_SUBCMDS}\b", norm_cmd)
        )
        if (
            cwd_touches
            or ".opt" in norm_cmd
            or "memo" in norm_cmd
            or "MEMORY_DIR" in norm_cmd
            or "LOG.txt" in norm_cmd
            or "TREE" in norm_cmd
            or has_subcmd_with_var
            or SUBAGENT_WILDCARD_RE.search(norm_cmd)
            or _has_real_memo_invocation(cmd, base_dir)
            or _touches_optmem_memory_store(cmd, base_dir)
        ):
            return {
                "decision": "deny",
                "reason": "Subagents must never run memo (OptMem rule). Only the main agent may read or write OptMem.",
            }
        return {"decision": "allow"}

    has_memo_cmd = _has_real_memo_invocation(cmd, base_dir)
    if not has_memo_cmd:
        return {"decision": "allow"}

    if "note" not in norm_cmd:
        return {"decision": "allow"}
    default_project = detect_project(payload)

    changed = False
    overflow_err = None

    def _tag_body(raw_body, project, kind):
        nonlocal changed, overflow_err
        if not project:
            return raw_body
        stripped = raw_body.strip()
        if not stripped or _already_mentions_project_or_global(stripped, project):
            return raw_body
        prefix_bytes = len(f"[{project}] ".encode("utf-8"))
        raw_len = _unescaped_utf8_len(stripped, kind)
        tagged_len = prefix_bytes + raw_len
        if tagged_len > ENTRY_CHARS:
            max_raw = ENTRY_CHARS - prefix_bytes
            overflow_err = (
                f"OptMem note is {raw_len} bytes; prepending [{project}] makes it "
                f"{tagged_len} bytes (limit {ENTRY_CHARS} bytes, max {max_raw} bytes "
                f"before auto-tag). Shorten the note to <= {max_raw} bytes or "
                f"include '{project}' / '[global]' explicitly."
            )
            return raw_body
        changed = True
        body_out = raw_body.lstrip() if kind in ("dq", "ac", "hd") else stripped
        return f"[{project}] {body_out}"

    def _format_note_match(m, proj, base_offset):
        head = m.group("cmd_head")
        if m.group("hd_lead") is not None:
            if not m.group("hd_dash") and m.group("hd_indent"):
                return m.group(0)
            hd_rest = m.group("hd_rest")
            if "note" in hd_rest:
                hd_rest = _rewrite_notes(hd_rest, base_offset + m.start("hd_rest"))
            new_body = _tag_body(m.group("hd_body"), proj, "hd")
            if m.group("hd_delim_q") is not None:
                q = m.group("hd_q") or ""
                delim_str = f"{q}{m.group('hd_delim_q')}{q}"
            else:
                bs = m.group("hd_bs") or ""
                delim_str = f"{bs}{m.group('hd_delim_u')}"
            return f"{head}{m.group('hd_lead')}{delim_str}{hd_rest}{new_body}{m.group('hd_tail')}"
        arg_lead = m.group("arg_lead") or ""
        if m.group("arg_dq") is not None:
            new_body = _tag_body(m.group("arg_dq"), proj, "dq")
            return f'{head}{arg_lead}"{new_body}"'
        if m.group("arg_sq") is not None:
            new_body = _tag_body(m.group("arg_sq"), proj, "sq")
            return f"{head}{arg_lead}'{new_body}'"
        new_body = _tag_body(m.group("arg_ac"), proj, "ac")
        return f"{head}{arg_lead}$'{new_body}'"

    def _rewrite_notes(text, base_offset=0):
        out = []
        pos = 0
        while pos < len(text):
            m = NOTE_STATEMENT_RE.search(text, pos)
            if not m:
                out.append(text[pos:])
                break
            proj = _detect_project_at_offset(cmd, base_offset + m.end("sep"), payload, default_project)
            if proj is None:
                step_to = max(pos + 1, m.end("sep") + 1)
                out.append(text[pos:step_to])
                pos = step_to
                continue
            out.append(text[pos : m.start()])
            out.append(_format_note_match(m, proj, base_offset))
            pos = m.end()
        return "".join(out)

    new_cmd = _rewrite_notes(cmd, 0)

    if overflow_err:
        return {"decision": "deny", "reason": overflow_err}
    if changed and new_cmd != cmd:
        return {
            "decision": "allow",
            "overwrite": {
                "CommandLine": new_cmd,
            },
        }
    return {"decision": "allow"}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "session-start"
    payload = read_payload()
    if mode == "session-start":
        res = handle_session_start(payload)
    elif mode == "pre-invocation":
        res = handle_pre_invocation(payload)
    elif mode == "pre-tool-use":
        res = handle_pre_tool_use(payload)
    else:
        res = {}
    sys.stdout.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
