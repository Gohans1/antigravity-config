#!/usr/bin/env python3
"""TDD test suite for ~/.optmem/agy-hook.py and GEMINI.md OptMem setup block."""

import json
import os
import subprocess
import tempfile
import unittest

HOOK = os.path.expanduser("~/.optmem/agy-hook.py")
MEMO = os.path.expanduser("~/.optmem/memo")
GEMINI_MD = os.path.expanduser("~/.gemini/config/GEMINI.md")


def run_hook(mode, payload, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [HOOK, mode],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert proc.returncode == 0, f"Hook failed: {proc.stderr}"
    return json.loads(proc.stdout)


class AgyHookTest(unittest.TestCase):
    def test_gemini_md_starts_with_exact_verbatim_mneves_setup_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = os.path.join(tmp, "memory")
            proc = subprocess.run(
                [MEMO, "init"],
                env={**os.environ, "MEMORY_DIR": mem_dir},
                capture_output=True,
                text=True,
                check=True,
            )
        marker = "## Memory\n"
        self.assertIn(marker, proc.stdout)
        expected_block = proc.stdout[proc.stdout.index(marker) :].strip().replace(mem_dir, "~/.optmem/memory")
        with open(GEMINI_MD, "r", encoding="utf-8") as f:
            gemini_content = f.read()
        self.assertTrue(
            gemini_content.startswith(expected_block),
            "GEMINI.md must start with the exact verbatim ## Memory block from memo init",
        )

    def test_session_start_injects_pure_wake_brief_output_with_no_extra_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = os.path.join(tmp, "memory")
            env = {"MEMORY_DIR": mem_dir}
            subprocess.run([MEMO, "init"], env={**os.environ, **env}, check=True, capture_output=True)
            subprocess.run(
                [MEMO, "note", "slice-player stores audio waveforms in IndexedDB"],
                env={**os.environ, **env},
                check=True,
                capture_output=True,
            )

            payload = {"workspacePaths": ["/home/gohans-linux/projects/slice-player"]}
            res = run_hook("session-start", payload, env)
            expected_wake = subprocess.run(
                [MEMO, "wake", "--brief", "slice-player"],
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            self.assertEqual(
                res,
                {
                    "injectSteps": [
                        {
                            "systemMessage": {
                                "systemMessage": expected_wake,
                            }
                        }
                    ]
                },
            )

    def test_session_start_skips_subagents_and_never_poisons_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = os.path.join(tmp, "memory")
            env = {"MEMORY_DIR": mem_dir}
            subprocess.run([MEMO, "init"], env={**os.environ, **env}, check=True, capture_output=True)
            subprocess.run([MEMO, "note", "System fact"], env={**os.environ, **env}, check=True, capture_output=True)

            art_dir = os.path.join(tmp, "brain", "subagent-conv")
            msg_dir = os.path.join(art_dir, ".system_generated", "messages")
            os.makedirs(msg_dir, exist_ok=True)
            with open(os.path.join(msg_dir, "msg1.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "renderDetails": {"messageTitle": "Message from Parent Agent"},
                        "content": "P" * 6000,
                        "sourceMetadata": {"tool": {"toolCall": {"name": "invoke_subagent"}}},
                    },
                    f,
                )

            sub_payload = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "artifactDirectoryPath": art_dir,
            }
            self.assertEqual(run_hook("session-start", sub_payload, env), {})

            parent_art = os.path.join(tmp, "brain", "parent-conv")
            parent_msg_dir = os.path.join(parent_art, ".system_generated", "messages")
            os.makedirs(parent_msg_dir, exist_ok=True)
            with open(os.path.join(parent_msg_dir, "reply.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "renderDetails": {"messageTitle": "Message from Subagent"},
                        "content": 'Mentions "invoke_subagent" and "You are a subagent. Don\'t run memo."',
                        "sourceMetadata": {"tool": {"toolCall": {"name": "send_message"}}},
                    },
                    f,
                )
            parent_payload = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "artifactDirectoryPath": parent_art,
            }
            self.assertIn("injectSteps", run_hook("session-start", parent_payload, env))
            self.assertEqual(run_hook("pre-invocation", parent_payload, env), {})
            self.assertEqual(run_hook("pre-tool-use", parent_payload, env), {"decision": "allow"})

    def test_pre_invocation_recovers_wake_after_compaction_checkpoint_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = os.path.join(tmp, "memory")
            env = {"MEMORY_DIR": mem_dir}
            subprocess.run([MEMO, "init"], env={**os.environ, **env}, check=True, capture_output=True)
            subprocess.run(
                [MEMO, "note", "slice-player uses WaveSurfer v7"],
                env={**os.environ, **env},
                check=True,
                capture_output=True,
            )

            transcript = os.path.join(tmp, "transcript.jsonl")
            steps = [
                {
                    "step_index": 0,
                    "source": "SYSTEM_SDK",
                    "type": "SYSTEM_MESSAGE",
                    "content": "#0 2026-10-22 slice-player uses WaveSurfer v7\nYou are awake.",
                },
                {
                    "step_index": 1,
                    "source": "USER_EXPLICIT",
                    "type": "USER_INPUT",
                    "content": "Hello",
                },
                {
                    "step_index": 2,
                    "source": "SYSTEM",
                    "type": "CHECKPOINT",
                    "content": "# Resuming from a compaction\n\nYou are continuing work...",
                },
                {
                    "step_index": 3,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "content": "Mentioning You are awake. in normal prose must not spoof wake detection.",
                },
            ]
            with open(transcript, "w", encoding="utf-8") as f:
                for s in steps:
                    f.write(json.dumps(s) + "\n")

            payload = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "transcriptPath": transcript,
                "invocationNum": 2,
            }
            res = run_hook("pre-invocation", payload, env)
            expected_wake = subprocess.run(
                [MEMO, "wake", "--brief", "slice-player"],
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(
                res,
                {
                    "injectSteps": [
                        {
                            "systemMessage": {
                                "systemMessage": expected_wake,
                            }
                        }
                    ]
                },
            )

            # Once Antigravity records the injected systemMessage after CHECKPOINT, next call is a no-op
            with open(transcript, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "step_index": 4,
                            "source": "SYSTEM_SDK",
                            "type": "SYSTEM_MESSAGE",
                            "content": f"<SYSTEM_MESSAGE>\n{expected_wake}\n</SYSTEM_MESSAGE>",
                        }
                    )
                    + "\n"
                )
            self.assertEqual(run_hook("pre-invocation", payload, env), {})

    def test_pre_invocation_injects_official_memo_nap_only_when_pending_on_invocation_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem_dir = os.path.join(tmp, "memory")
            env = {"MEMORY_DIR": mem_dir}
            subprocess.run([MEMO, "init"], env={**os.environ, **env}, check=True, capture_output=True)
            subprocess.run([MEMO, "note", "First fact"], env={**os.environ, **env}, check=True, capture_output=True)

            # Only 1 memory -> no pending nap -> silent
            payload_inv1 = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "invocationNum": 1,
            }
            self.assertEqual(run_hook("pre-invocation", payload_inv1, env), {})

            # 2nd memory creates a pending 0-1 nap
            subprocess.run([MEMO, "note", "Second fact"], env={**os.environ, **env}, check=True, capture_output=True)
            expected_nap = subprocess.run(
                [MEMO, "nap"],
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            # Mid-turn (invocationNum > 1), pre-invocation stays silent so it doesn't duplicate memo note stdout
            payload_inv2 = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "invocationNum": 2,
            }
            self.assertEqual(run_hook("pre-invocation", payload_inv2, env), {})

            # At start of a turn (invocationNum == 1), pre-invocation injects exact memo nap output as ephemeralMessage
            self.assertEqual(
                run_hook("pre-invocation", payload_inv1, env),
                {
                    "injectSteps": [
                        {
                            "ephemeralMessage": expected_nap,
                        }
                    ]
                },
            )

            # After compressing 0-1, pre-invocation is silent again
            subprocess.run(
                [MEMO, "nap", "0-1", "First and second facts combined."],
                env={**os.environ, **env},
                check=True,
                capture_output=True,
            )
            self.assertEqual(run_hook("pre-invocation", payload_inv1, env), {})

    def test_pre_tool_use_denies_subagent_memo_commands_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            art_dir = os.path.join(tmp, "brain", "subagent-conv")
            msg_dir = os.path.join(art_dir, ".system_generated", "messages")
            os.makedirs(msg_dir, exist_ok=True)
            with open(os.path.join(msg_dir, "msg1.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "renderDetails": {"messageTitle": "Message from Parent Agent"},
                        "content": "Task instructions",
                        "sourceMetadata": {"tool": {"toolCall": {"name": "invoke_subagent"}}},
                    },
                    f,
                )

            sub_memo = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "artifactDirectoryPath": art_dir,
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": "~/.optmem/memo note 'Subagent note'"},
                },
            }
            res = run_hook("pre-tool-use", sub_memo)
            self.assertEqual(res.get("decision"), "deny")

            sub_other = {
                "workspacePaths": ["/home/gohans-linux/projects/slice-player"],
                "artifactDirectoryPath": art_dir,
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": "bun test"},
                },
            }
            self.assertEqual(run_hook("pre-tool-use", sub_other), {"decision": "allow"})

    def test_pre_tool_use_auto_tags_heredoc_quoted_and_chained_notes(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # 1. Heredoc note without project name
        heredoc_cmd = "~/.optmem/memo note - <<'MEMO'\nUse IndexedDB for waveform cache\nMEMO"
        res1 = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": heredoc_cmd}}},
        )
        self.assertEqual(res1["decision"], "allow")
        self.assertIn(
            "[slice-player] Use IndexedDB for waveform cache",
            res1["overwrite"]["CommandLine"],
        )

        # 2. Double-quoted note containing inner single quote
        dq_cmd = '~/.optmem/memo note "Gohans\'s waveform zoom uses wheel delta"'
        res2 = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": dq_cmd}}},
        )
        self.assertEqual(
            res2["overwrite"]["CommandLine"],
            '~/.optmem/memo note "[slice-player] Gohans\'s waveform zoom uses wheel delta"',
        )

        # 3. Single-quoted note containing inner double quotes
        sq_cmd = "~/.optmem/memo note 'Use \"strict\" in tsconfig'"
        res3 = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": sq_cmd}}},
        )
        self.assertEqual(
            res3["overwrite"]["CommandLine"],
            "~/.optmem/memo note '[slice-player] Use \"strict\" in tsconfig'",
        )

        # 4. Chained memo note commands: first has [global], second is untagged
        chained_cmd = (
            '~/.optmem/memo note "[global] Prefer bun over node" && '
            '~/.optmem/memo note "Decode audio via Web Audio API"'
        )
        res4 = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": chained_cmd}}},
        )
        self.assertEqual(
            res4["overwrite"]["CommandLine"],
            '~/.optmem/memo note "[global] Prefer bun over node" && '
            '~/.optmem/memo note "[slice-player] Decode audio via Web Audio API"',
        )

    def test_pre_tool_use_word_boundary_and_280_byte_guard(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # Already mentions slice-player as exact tokens -> no overwrite
        already_cmd = '~/.optmem/memo note "In slice-player we use Zustand for playback state"'
        res_ok = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": already_cmd}}},
        )
        self.assertEqual(res_ok, {"decision": "allow"})

        # Underscore token slice_player does NOT match memo's BM25 words() for slice-player -> must tag
        underscore_cmd = '~/.optmem/memo note "Variable slice_player_store holds state"'
        res_under = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": underscore_cmd}}},
        )
        self.assertIn("[slice-player] Variable slice_player_store", res_under["overwrite"]["CommandLine"])

        # 275-byte note without tag: adding "[slice-player] " (15 bytes) would exceed 280 bytes -> deny with clear reason
        long_note = "A" * 275
        long_cmd = f'~/.optmem/memo note "{long_note}"'
        res_long = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": long_cmd}}},
        )
        self.assertEqual(res_long["decision"], "deny")
        self.assertIn("280", res_long["reason"])

    def test_prose_mentioning_global_is_tagged_while_leading_global_tag_is_preserved(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        prose_global_cmd = '~/.optmem/memo note "Replaced global CSS variables with local Tailwind tokens"'
        res_prose = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": prose_global_cmd}}},
        )
        self.assertEqual(
            res_prose["overwrite"]["CommandLine"],
            '~/.optmem/memo note "[slice-player] Replaced global CSS variables with local Tailwind tokens"',
        )

        leading_global_cmd = '~/.optmem/memo note "[GLOBAL] Always prefer Bun over Node"'
        self.assertNotIn(
            "overwrite",
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": leading_global_cmd}}},
            ),
        )

        leading_global_colon = '~/.optmem/memo note "[global]: Always prefer Bun over Node"'
        self.assertNotIn(
            "overwrite",
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": leading_global_colon}}},
            ),
        )

    def test_non_project_bracket_tags_still_receive_project_prefix(self):
        ws = ["/home/gohans-linux/projects/slice-player"]
        perf_tag_cmd = '~/.optmem/memo note "[PERF] Offload waveform peaks calculation to Web Worker"'
        res_perf = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": perf_tag_cmd}}},
        )
        self.assertEqual(
            res_perf["overwrite"]["CommandLine"],
            '~/.optmem/memo note "[slice-player] [PERF] Offload waveform peaks calculation to Web Worker"',
        )

    def test_heredoc_bodies_and_non_memo_commands_are_never_corrupted_by_quoted_note_matching(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # 1. Heredoc body mentioning `memo note "secret"` must NOT have its inner quotes rewritten
        global_heredoc = '~/.optmem/memo note - <<\'MEMO\'\n[global] Never pass secrets to memo note "secret"\nMEMO'
        res_global_hd = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": global_heredoc}}},
        )
        self.assertNotIn("overwrite", res_global_hd)

        project_heredoc = '~/.optmem/memo note - <<\'MEMO\'\nHook rewrites memo note "text" automatically\nMEMO'
        res_proj_hd = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": project_heredoc}}},
        )
        self.assertEqual(
            res_proj_hd["overwrite"]["CommandLine"],
            '~/.optmem/memo note - <<\'MEMO\'\n[slice-player] Hook rewrites memo note "text" automatically\nMEMO',
        )

        # 2. git commit / echo mentioning `~/.optmem/memo note "foo"` must NOT be rewritten
        git_commit_cmd = 'git commit -m \'Fix ~/.optmem/memo note "bug" in hook\''
        res_commit = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": git_commit_cmd}}},
        )
        self.assertEqual(res_commit, {"decision": "allow"})

        # 3. Subagent running read-only grep/diff on ~/.optmem/memo as an argument must be allowed
        with tempfile.TemporaryDirectory() as tmp:
            art_dir = os.path.join(tmp, "brain", "subagent-conv")
            msg_dir = os.path.join(art_dir, ".system_generated", "messages")
            os.makedirs(msg_dir, exist_ok=True)
            with open(os.path.join(msg_dir, "msg1.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "renderDetails": {"messageTitle": "Message from Parent Agent"},
                        "content": "Task instructions",
                        "sourceMetadata": {"tool": {"toolCall": {"name": "invoke_subagent"}}},
                    },
                    f,
                )
            sub_grep = {
                "workspacePaths": ws,
                "artifactDirectoryPath": art_dir,
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": 'grep "ranked" ~/.optmem/memo'},
                },
            }
            self.assertEqual(run_hook("pre-tool-use", sub_grep), {"decision": "allow"})

    def test_quoting_variants_escaped_double_quotes_posix_apostrophes_backslash_heredoc_and_herestring(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        escaped_dq_cmd = r'~/.optmem/memo note "Set \"strict\": true in tsconfig.json"'
        res_escaped = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": escaped_dq_cmd}}},
        )
        self.assertEqual(
            res_escaped["overwrite"]["CommandLine"],
            r'~/.optmem/memo note "[slice-player] Set \"strict\": true in tsconfig.json"',
        )

        posix_sq_cmd = r"~/.optmem/memo note 'Gohans'\''s rule uses strict mode'"
        res_posix = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": posix_sq_cmd}}},
        )
        self.assertEqual(
            res_posix["overwrite"]["CommandLine"],
            r"~/.optmem/memo note '[slice-player] Gohans'\''s rule uses strict mode'",
        )

        bs_heredoc_cmd = "~/.optmem/memo note - <<\\MEMO && echo ok\nCache decoded AudioBuffer\nMEMO"
        res_bshd = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": bs_heredoc_cmd}}},
        )
        self.assertEqual(
            res_bshd["overwrite"]["CommandLine"],
            "~/.optmem/memo note - <<\\MEMO && echo ok\n[slice-player] Cache decoded AudioBuffer\nMEMO",
        )

        herestring_cmd = '~/.optmem/memo note - <<< "Use AudioWorklet for low latency"'
        res_hs = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": herestring_cmd}}},
        )
        self.assertEqual(
            res_hs["overwrite"]["CommandLine"],
            '~/.optmem/memo note - <<< "[slice-player] Use AudioWorklet for low latency"',
        )

    def test_cd_tracking_supports_home_vars_cd_dash_and_closed_subshells(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # 1. cd $HOME/projects/other-repo
        cd_home_cmd = 'cd $HOME/projects/other-repo && ~/.optmem/memo note "Use Hono RPC client"'
        res_cd_home = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": cd_home_cmd}}},
        )
        self.assertEqual(
            res_cd_home["overwrite"]["CommandLine"],
            'cd $HOME/projects/other-repo && ~/.optmem/memo note "[other-repo] Use Hono RPC client"',
        )

        # 2. cd into other-repo then `cd -` back to original workspace
        cd_dash_cmd = 'cd /home/gohans-linux/projects/other-repo && cd - && ~/.optmem/memo note "Back in slice"'
        res_cd_dash = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": cd_dash_cmd}}},
        )
        self.assertEqual(
            res_cd_dash["overwrite"]["CommandLine"],
            'cd /home/gohans-linux/projects/other-repo && cd - && ~/.optmem/memo note "[slice-player] Back in slice"',
        )

        # 3. Closed subshell `(cd /home/gohans-linux/projects/other-repo && bun test) && memo note`
        subshell_cmd = (
            '(cd /home/gohans-linux/projects/other-repo && bun test) && '
            '~/.optmem/memo note "Subshell cd must not leak"'
        )
        res_subshell = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": subshell_cmd}}},
        )
        self.assertEqual(
            res_subshell["overwrite"]["CommandLine"],
            '(cd /home/gohans-linux/projects/other-repo && bun test) && '
            '~/.optmem/memo note "[slice-player] Subshell cd must not leak"',
        )

    def test_short_project_segments_and_over_280_byte_untagged_notes(self):
        # 1-char segment project `x-player`: mentioning only "player" must still get tagged `[x-player]`
        ws_short = ["/home/gohans-linux/projects/x-player"]
        only_player_cmd = '~/.optmem/memo note "The audio player uses Web Audio API"'
        res_short = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws_short, "toolCall": {"name": "run_command", "args": {"CommandLine": only_player_cmd}}},
        )
        self.assertIn("overwrite", res_short)
        self.assertEqual(
            res_short["overwrite"]["CommandLine"],
            '~/.optmem/memo note "[x-player] The audio player uses Web Audio API"',
        )

        # Already mentions `x-player` -> no overwrite
        already_short_cmd = '~/.optmem/memo note "In x-player we use Web Audio API"'
        self.assertNotIn(
            "overwrite",
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws_short, "toolCall": {"name": "run_command", "args": {"CommandLine": already_short_cmd}}},
            ),
        )

        # Untagged note already > 280 bytes (e.g. 285 bytes) must be denied immediately with clear max budget
        ws = ["/home/gohans-linux/projects/slice-player"]
        over_280_cmd = f'~/.optmem/memo note "{"B" * 285}"'
        res_over = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": over_280_cmd}}},
        )
        self.assertEqual(res_over["decision"], "deny")
        self.assertIn("265", res_over["reason"])

    def test_git_worktree_submodule_and_non_project_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            main_repo = os.path.join(tmp, "main-project")
            os.makedirs(main_repo, exist_ok=True)
            subprocess.run(["git", "init", "-q", main_repo], check=True)
            subprocess.run(["git", "-C", main_repo, "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", main_repo, "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", main_repo, "commit", "--allow-empty", "-q", "-m", "init"], check=True)

            worktree_dir = os.path.join(tmp, "wt-feature-branch")
            subprocess.run(
                ["git", "-C", main_repo, "worktree", "add", "-q", "-b", "feat-x", worktree_dir],
                check=True,
            )
            nested_wt_dir = os.path.join(worktree_dir, "src", "components")
            os.makedirs(nested_wt_dir, exist_ok=True)

            cmd = '~/.optmem/memo note "Worktree note must tag main repo"'
            res = run_hook(
                "pre-tool-use",
                {
                    "workspacePaths": [nested_wt_dir],
                    "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
                },
            )
            self.assertEqual(
                res["overwrite"]["CommandLine"],
                '~/.optmem/memo note "[main-project] Worktree note must tag main repo"',
            )

            # Arbitrary non-git directory outside ~/projects (like ~/Downloads) must NOT be treated as a project
            res_downloads = run_hook(
                "pre-tool-use",
                {
                    "workspacePaths": ["/home/gohans-linux/Downloads"],
                    "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
                },
            )
            self.assertEqual(res_downloads, {"decision": "allow"})

            # Symlink pointing to a nested subdirectory inside main_repo must still resolve "main-project"
            real_sub = os.path.join(main_repo, "packages", "core", "src")
            os.makedirs(real_sub, exist_ok=True)
            symlink_sub = os.path.join(tmp, "linked-src")
            os.symlink(real_sub, symlink_sub)
            res_symlink = run_hook(
                "pre-tool-use",
                {
                    "workspacePaths": [symlink_sub],
                    "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
                },
            )
            self.assertEqual(
                res_symlink["overwrite"]["CommandLine"],
                '~/.optmem/memo note "[main-project] Worktree note must tag main repo"',
            )

            # Git submodule (.git file pointing to ../.git/modules/sublib) must resolve superproject
            submod_git_dir = os.path.join(main_repo, ".git", "modules", "sublib")
            submod_work = os.path.join(main_repo, "vendor", "sublib")
            os.makedirs(os.path.dirname(submod_git_dir), exist_ok=True)
            os.makedirs(submod_work, exist_ok=True)
            subprocess.run(
                ["git", "init", "-q", f"--separate-git-dir={submod_git_dir}", submod_work],
                check=True,
            )
            res_submod = run_hook(
                "pre-tool-use",
                {
                    "workspacePaths": [submod_work],
                    "toolCall": {"name": "run_command", "args": {"CommandLine": cmd}},
                },
            )
            self.assertEqual(
                res_submod["overwrite"]["CommandLine"],
                '~/.optmem/memo note "[main-project] Worktree note must tag main repo"',
            )

    def test_shell_scanner_handles_comments_heredoc_apostrophes_ansic_and_dq_subshells(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # 1. Comment with apostrophe `# Don't forget` before `memo note` must NOT break auto-tagging
        comment_cmd = "# Don't forget to record this\n~/.optmem/memo note - <<'MEMO'\nUse Web Audio API\nMEMO"
        res_comment = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": comment_cmd}}},
        )
        self.assertIn("overwrite", res_comment)
        self.assertEqual(
            res_comment["overwrite"]["CommandLine"],
            "# Don't forget to record this\n~/.optmem/memo note - <<'MEMO'\n[slice-player] Use Web Audio API\nMEMO",
        )

        # 2. Commented-out `# ~/.optmem/memo note "foo"` must NOT be rewritten
        commented_out_cmd = 'echo ok\n# ~/.optmem/memo note "Do not touch comment"'
        self.assertEqual(
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": commented_out_cmd}}},
            ),
            {"decision": "allow"},
        )

        # 3. Two heredocs in one command where the first heredoc body has an unmatched apostrophe (`Gohans's`)
        two_hd_cmd = (
            "~/.optmem/memo note - <<'MEMO'\n"
            "[global] Gohans's runtime is Bun\n"
            "MEMO\n"
            "~/.optmem/memo note - <<'MEMO'\n"
            "Decode audio in Web Worker\n"
            "MEMO"
        )
        res_two_hd = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": two_hd_cmd}}},
        )
        self.assertIn("overwrite", res_two_hd)
        self.assertEqual(
            res_two_hd["overwrite"]["CommandLine"],
            "~/.optmem/memo note - <<'MEMO'\n"
            "[global] Gohans's runtime is Bun\n"
            "MEMO\n"
            "~/.optmem/memo note - <<'MEMO'\n"
            "[slice-player] Decode audio in Web Worker\n"
            "MEMO",
        )

        # 4. Non-memo heredoc (`cat <<'EOF'`) containing a literal `memo note` line must NOT be corrupted
        cat_hd_cmd = 'cat <<\'EOF\' > doc.md\n~/.optmem/memo note "example line"\nEOF'
        self.assertEqual(
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": cat_hd_cmd}}},
            ),
            {"decision": "allow"},
        )

        # 5. ANSI-C `$'...'` with `\'` followed by another `memo note`
        ansic_chain_cmd = r"~/.optmem/memo note $'[global] Gohans\'s rule' && ~/.optmem/memo note 'Second note'"
        res_ansic = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": ansic_chain_cmd}}},
        )
        self.assertIn("overwrite", res_ansic)
        self.assertEqual(
            res_ansic["overwrite"]["CommandLine"],
            r"~/.optmem/memo note $'[global] Gohans\'s rule' && ~/.optmem/memo note '[slice-player] Second note'",
        )

        # 6. Subagent attempting command substitution inside double quotes `"$(~/.optmem/memo wake)"` must be denied
        with tempfile.TemporaryDirectory() as tmp:
            art_dir = os.path.join(tmp, "brain", "subagent-conv")
            msg_dir = os.path.join(art_dir, ".system_generated", "messages")
            os.makedirs(msg_dir, exist_ok=True)
            with open(os.path.join(msg_dir, "msg1.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "renderDetails": {"messageTitle": "Message from Parent Agent"},
                        "content": "Task instructions",
                        "sourceMetadata": {"tool": {"toolCall": {"name": "invoke_subagent"}}},
                    },
                    f,
                )
            sub_dq = {
                "workspacePaths": ws,
                "artifactDirectoryPath": art_dir,
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": 'echo "$(~/.optmem/memo wake)"'},
                },
            }
            self.assertEqual(run_hook("pre-tool-use", sub_dq)["decision"], "deny")

    def test_security_rejects_unsafe_project_names_and_unexpanded_cd_vars(self):
        ws = ["/home/gohans-linux/projects/slice-player"]
        # 1. Quote breakout / command injection attempt via single-quoted `cd` into unsafe dir name
        inj_cmd = 'cd \'/home/gohans-linux/projects/a"$(id)"b\' || ~/.optmem/memo note "hello"'
        res_inj = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": inj_cmd}}},
        )
        self.assertEqual(
            res_inj["overwrite"]["CommandLine"],
            'cd \'/home/gohans-linux/projects/a"$(id)"b\' || ~/.optmem/memo note "[slice-player] hello"',
        )

        # 2. Single-quote breakout via apostrophe in project name
        sq_inj = 'cd "/home/gohans-linux/projects/Gohans\'s-app" || ~/.optmem/memo note \'fact\''
        res_sq = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": sq_inj}}},
        )
        self.assertEqual(
            res_sq["overwrite"]["CommandLine"],
            'cd "/home/gohans-linux/projects/Gohans\'s-app" || ~/.optmem/memo note \'[slice-player] fact\'',
        )

        # 3. Unexpanded shell variable `$REPO` in `cd` must NOT tag literal `[$REPO]`
        var_cd = "cd ~/projects/$REPO && ~/.optmem/memo note - <<'MEMO'\nFact after var cd\nMEMO"
        res_var = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": var_cd}}},
        )
        self.assertEqual(
            res_var["overwrite"]["CommandLine"],
            "cd ~/projects/$REPO && ~/.optmem/memo note - <<'MEMO'\n[slice-player] Fact after var cd\nMEMO",
        )

    def test_security_bitshift_hyphen_heredoc_and_decoy_quote_consumption(self):
        ws = ["/home/gohans-linux/projects/slice-player"]
        # 1. Arithmetic left-shift `$(( 1 << 2 ))` must NOT be treated as an unclosed heredoc
        shift_cmd = 'echo $(( 1 << 2 ))\n~/.optmem/memo note "Fact after bitshift"'
        res_shift = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": shift_cmd}}},
        )
        self.assertEqual(
            res_shift["overwrite"]["CommandLine"],
            'echo $(( 1 << 2 ))\n~/.optmem/memo note "[slice-player] Fact after bitshift"',
        )

        # 2. Hyphenated heredoc delimiter `EOF-1` must close properly and tag subsequent `memo note`
        eof_cmd = 'cat << EOF-1 > /dev/null\nhello\nEOF-1\n~/.optmem/memo note "Fact after EOF-1"'
        res_eof = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": eof_cmd}}},
        )
        self.assertEqual(
            res_eof["overwrite"]["CommandLine"],
            'cat << EOF-1 > /dev/null\nhello\nEOF-1\n~/.optmem/memo note "[slice-player] Fact after EOF-1"',
        )

        # 3. Quoted decoy `; ~/.optmem/memo note "` inside `echo '...'` must NOT swallow subsequent real `memo note`
        decoy_cmd = 'echo \'Example: ; ~/.optmem/memo note "\' && ~/.optmem/memo note "Untagged real note"'
        res_decoy = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": decoy_cmd}}},
        )
        self.assertIn("overwrite", res_decoy)
        self.assertEqual(
            res_decoy["overwrite"]["CommandLine"],
            'echo \'Example: ; ~/.optmem/memo note "\' && ~/.optmem/memo note "[slice-player] Untagged real note"',
        )

    def test_security_subagent_gate_blocks_prefixes_subshells_and_corrupt_msg_files(self):
        ws = ["/home/gohans-linux/projects/slice-player"]
        with tempfile.TemporaryDirectory() as tmp:
            art_dir = os.path.join(tmp, "brain", "subagent-sec")
            msg_dir = os.path.join(art_dir, ".system_generated", "messages")
            os.makedirs(msg_dir, exist_ok=True)
            # Create corrupt / non-dict JSON files alongside valid parent message
            for idx, bad_content in enumerate(("{corrupt json", "[1, 2, 3]", '"just a string"', "42")):
                with open(os.path.join(msg_dir, f"000_bad_{idx}.json"), "w", encoding="utf-8") as f:
                    f.write(bad_content)
            with open(os.path.join(msg_dir, "zzz_valid.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "renderDetails": {"messageTitle": "Message from Parent Agent"},
                        "content": "You are a subagent. Don't run memo.",
                        "sourceMetadata": {"tool": {"toolCall": {"name": "invoke_subagent"}}},
                    },
                    f,
                )

            bypass_attempts = [
                "/usr/bin/python3 ~/.optmem/memo wake",
                "/bin/bash ~/.optmem/memo wake",
                "{ ~/.optmem/memo wake; }",
                "command ~/.optmem/memo wake",
                "exec ~/.optmem/memo wake",
                "time ~/.optmem/memo wake",
                "timeout 5 ~/.optmem/memo wake",
                "if ~/.optmem/memo check; then echo ok; fi",
                "cd ~/.optmem && ./memo wake",
                'bash -c "echo ok && ~/.optmem/memo wake"',
                'env bash -c "echo ok && ~/.optmem/memo wake"',
                'command bash -c "echo ok && ~/.optmem/memo wake"',
                'sh -c "cat ~/.optmem/memory/LOG.txt"',
                'python3 -c "import subprocess; subprocess.run([\'/home/gohans-linux/.optmem/memo\', \'wake\'])"',
                '~/.optmem/"memo" wake',
                "~/.optmem/'memo' wake",
                r"~/.optmem/m\emo wake",
                "rm -rf ~/.optmem",
                "cp /dev/null ~/.optmem/memo",
                'echo $(( 1 << 2 ))\n~/.optmem/memo wake',
                'cat << EOF-1 > /dev/null\nhi\nEOF-1\n~/.optmem/memo wake',
                "rm -rf ~/.optmem/memory/LOG.txt",
                'cat <<< hello\n~/.optmem/memo wake',
                'cat <<EOF\nEOF\n~/.optmem/memo wake',
                'cat <<EOF\n$(~/.optmem/memo wake)\nEOF',
                "bash <<'EOF'\n~/.optmem/memo wake\nEOF",
                'sh <<< "~/.optmem/memo wake"',
                "python3 - <<'EOF'\nimport subprocess; subprocess.run(['/home/gohans-linux/.optmem/memo', 'wake'])\nEOF",
                'cat "$HOME/.optmem/memory/LOG.txt"',
                "cat '/home/gohans-linux/.optmem/memory/LOG.txt'",
                "cd ~/.optmem && cat memory/LOG.txt",
                r"~/.opt\mem/m\emo wake",
                "~/.opt'mem'/m'emo' wake",
                "env FOO=1 ~/.optmem/memo wake",
                "FOO=1 command ~/.optmem/memo wake",
                'eval "~/.optmem/memo wake"',
                'bash --norc -c "~/.optmem/memo wake"',
                "bash -c $'~/.optmem/memo wake'",
                "cat <<EOF\n$(~/.optmem/memo wake)",
                'cat <<EOF\n$(echo "$(date)" && ~/.optmem/memo wake)\nEOF',
                "cd ~/.optmem && rm -rf memory",
                "cd ~/.optmem && rm -f memo agy-hook.py",
                "cd ~/.optmem && cat memory/config",
                "rm -rf ~/.opt'mem'",
                r"rm -rf ~/.opt\mem",
                'cp /dev/null ~/.opt"mem"/memo',
                "bash -c 'echo '\\''hello'\\'' && ~/.optmem/memo wake'",
                "eval ~/.optmem/memo wake",
                "dash ~/.optmem/memo wake",
                "python3.12 ~/.optmem/memo wake",
                "uv run ~/.optmem/memo wake",
                "~/.optmem/memo --help",
                "~/.opt*/m* wake",
                "~/.optmem/m* wake",
                "/home/*/.optmem/memo wake",
                "rm -rf ~/.opt*",
                "uv run python3 -c \"import subprocess; subprocess.run(['/home/gohans-linux/.optmem/memo', 'wake'])\"",
                "bun -e \"Bun.spawnSync(['/home/gohans-linux/.optmem/memo', 'wake'])\"",
                'bash -c \'"$0" "$1"\' ~/.optmem/memo wake',
                "echo wake | xargs ~/.optmem/memo",
                "find ~/.optmem -delete",
                "bash <<'EOF'\ncat memory/LOG.txt\nEOF",
                "D=~/.optmem; $D/memo wake",
                "source ~/.optmem/memo wake",
                "echo ${#} && ~/.optmem/memo wake",
                "echo $(true)#foo && ~/.optmem/memo wake",
                'echo "$(( (1 + 2)))" && ~/.optmem/memo wake',
                'echo "${MSG:-"Don\'t"}" && ~/.optmem/memo wake',
                "~/.o\\\nptmem/me\\\nmo wake",
                "~/.optmem/memo \\\n  wake",
                "rm -rf \\\n  ~/.optmem",
                "case x in x) ~/.optmem/memo wake ;; esac",
                "coproc ~/.optmem/memo wake",
                "env -u FOO ~/.optmem/memo wake",
                "python3 -X utf8 ~/.optmem/memo wake",
                "timeout -k 1 -s 9 2 ~/.optmem/memo wake",
                "echo '~/.optmem/memo wake' | bash",
                "bash <(echo '~/.optmem/memo wake')",
                "export M=~/.optmem/memo && $M wake",
                "A=~/.opt; B=mem/memo; $A$B wake",
                "sed -e 's/a/b/' -i ~/.optmem/agy-hook.py",
                'echo "$(case x in a) ~/.optmem/memo wake ;; esac)"',
            ]
            for attempt in bypass_attempts:
                with self.subTest(attempt=attempt):
                    res = run_hook(
                        "pre-tool-use",
                        {
                            "workspacePaths": ws,
                            "artifactDirectoryPath": art_dir,
                            "toolCall": {"name": "run_command", "args": {"CommandLine": attempt}},
                        },
                    )
                    self.assertEqual(res["decision"], "deny", f"Bypass succeeded for: {attempt}")

            # Subagent with Cwd inside ~/.optmem must be denied even for simple commands
            res_cwd_optmem = run_hook(
                "pre-tool-use",
                {
                    "workspacePaths": ws,
                    "artifactDirectoryPath": art_dir,
                    "toolCall": {
                        "name": "run_command",
                        "args": {"Cwd": "/home/gohans-linux/.optmem", "CommandLine": "ls -la"},
                    },
                },
            )
            self.assertEqual(res_cwd_optmem["decision"], "deny")

        # Main agent must also auto-tag notes invoked via `command` or `/usr/bin/python3`
        cmd_wrapped = 'command ~/.optmem/memo note "Wrapped with command builtin"'
        res_wrapped = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": cmd_wrapped}}},
        )
        self.assertEqual(
            res_wrapped["overwrite"]["CommandLine"],
            'command ~/.optmem/memo note "[slice-player] Wrapped with command builtin"',
        )

    def test_unquoted_heredoc_closed_sub_and_hd_rest_chaining(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # 1. Closed `$(...)` or `` `...` `` inside an unquoted heredoc must NOT cause literal lines after it to be rewritten
        readme_hd = (
            'cat <<EOF > README.md\n'
            'Run `bun test` or $(echo ok)\n'
            '~/.optmem/memo note "example line"\n'
            'EOF'
        )
        self.assertEqual(
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": readme_hd}}},
            ),
            {"decision": "allow"},
        )

        # 2. Chained note on `hd_rest` after an untagged/global heredoc when starting outside a project (`workspacePaths: ["/tmp"]`)
        hd_chain = (
            "~/.optmem/memo note - <<'MEMO' && cd ~/projects/slice-player && ~/.optmem/memo note \"Second note\"\n"
            "[global] First note\n"
            "MEMO"
        )
        res_chain = run_hook(
            "pre-tool-use",
            {"workspacePaths": ["/tmp"], "toolCall": {"name": "run_command", "args": {"CommandLine": hd_chain}}},
        )
        self.assertIn("overwrite", res_chain)
        self.assertEqual(
            res_chain["overwrite"]["CommandLine"],
            "~/.optmem/memo note - <<'MEMO' && cd ~/projects/slice-player && ~/.optmem/memo note \"[slice-player] Second note\"\n"
            "[global] First note\n"
            "MEMO",
        )

        # 3. `command cd` and empty quoted `cd ""`
        cmd_cd = 'command cd ~/projects/other-repo && cd "" && ~/.optmem/memo note "Stay in target directory"'
        res_cmd_cd = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": cmd_cd}}},
        )
        self.assertEqual(
            res_cmd_cd["overwrite"]["CommandLine"],
            'command cd ~/projects/other-repo && cd "" && ~/.optmem/memo note "[other-repo] Stay in target directory"',
        )

        # 4. Parameter expansion `${#}`, `$(true)#foo`, nested `$(( (1 + 2)))`, and nested quotes `"${MSG:-"Don't"}"`
        for prefix_expr in (
            "echo ${#}",
            "echo $(true)#foo",
            'echo "$(( (1 + 2)))"',
            'echo "${MSG:-"Don\'t"}"',
        ):
            with self.subTest(prefix_expr=prefix_expr):
                full_cmd = f'{prefix_expr} && ~/.optmem/memo note "After tricky shell syntax"'
                res_expr = run_hook(
                    "pre-tool-use",
                    {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": full_cmd}}},
                )
                self.assertEqual(
                    res_expr["overwrite"]["CommandLine"],
                    f'{prefix_expr} && ~/.optmem/memo note "[slice-player] After tricky shell syntax"',
                )

        # 5. Nested arithmetic `$(( (1 + 2)))` inside an unquoted heredoc must NOT corrupt literal lines after it
        readme_arith_hd = (
            'cat <<EOF > README.md\n'
            '$(( (1 + 2)))\n'
            '~/.optmem/memo note "example line"\n'
            'EOF'
        )
        self.assertEqual(
            run_hook(
                "pre-tool-use",
                {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": readme_arith_hd}}},
            ),
            {"decision": "allow"},
        )

        # 6. Unquoted heredoc `<<MEMO` with trailing `\ ` must preserve trailing space so `\` does not escape `\nMEMO`
        uq_hd_esc = "~/.optmem/memo note - <<MEMO\nEnds with backslash-space \\ \nMEMO"
        res_uq_hd = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": uq_hd_esc}}},
        )
        self.assertEqual(
            res_uq_hd["overwrite"]["CommandLine"],
            "~/.optmem/memo note - <<MEMO\n[slice-player] Ends with backslash-space \\ \nMEMO",
        )

        # 7. Backslash-newline continuation and `case` clause in main-agent `memo note`
        cont_note = '~/.optmem/memo \\\n  note \\\n  "Wrapped across lines"'
        res_cont = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": cont_note}}},
        )
        self.assertIn("[slice-player] Wrapped across lines", res_cont["overwrite"]["CommandLine"])

        case_note = 'case x in x) ~/.optmem/memo note "Inside case clause" ;; esac'
        res_case = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": case_note}}},
        )
        self.assertEqual(
            res_case["overwrite"]["CommandLine"],
            'case x in x) ~/.optmem/memo note "[slice-player] Inside case clause" ;; esac',
        )

        # 8. Direct write_file / edit_file on ~/.optmem/memory must be denied
        res_write_mem = run_hook(
            "pre-tool-use",
            {
                "workspacePaths": ws,
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": "/home/gohans-linux/.optmem/memory/LOG.txt"},
                },
            },
        )
        self.assertEqual(res_write_mem["decision"], "deny")

        # 9. needs_post_compact_wake checks transcript_full.jsonl when transcript.jsonl truncates content
        with tempfile.TemporaryDirectory() as tmp:
            t_short = os.path.join(tmp, "transcript.jsonl")
            t_full = os.path.join(tmp, "transcript_full.jsonl")
            ckpt = {"step_index": 1, "source": "SYSTEM", "type": "CHECKPOINT", "content": "Compacted"}
            wake_truncated = {
                "step_index": 2,
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": "#0 2026-10-22 long wake output...",
                "truncated_fields": ["content"],
            }
            wake_full = {
                "step_index": 2,
                "source": "SYSTEM_SDK",
                "type": "SYSTEM_MESSAGE",
                "content": "#0 2026-10-22 long wake output...\nYou are awake.",
            }
            with open(t_short, "w", encoding="utf-8") as f:
                f.write(json.dumps(ckpt) + "\n" + json.dumps(wake_truncated) + "\n")
            with open(t_full, "w", encoding="utf-8") as f:
                f.write(json.dumps(ckpt) + "\n" + json.dumps(wake_full) + "\n")
            self.assertEqual(
                run_hook("pre-invocation", {"workspacePaths": ws, "transcriptPath": t_short, "invocationNum": 2}),
                {},
            )

    def test_security_escaped_trailing_space_and_redos_resistance(self):
        import time

        ws = ["/home/gohans-linux/projects/slice-player"]
        # 1. Trailing `\ ` inside ANSI-C `$'...'` or `"..."` must NOT strip the space and leave a dangling `\`
        ansic_esc = r"~/.optmem/memo note $'Ends with backslash-space \ ' && echo '; id #'"
        res_ac = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": ansic_esc}}},
        )
        self.assertEqual(
            res_ac["overwrite"]["CommandLine"],
            r"~/.optmem/memo note $'[slice-player] Ends with backslash-space \ ' && echo '; id #'",
        )

        dq_esc = r'~/.optmem/memo note "Ends with backslash-space \ " && echo ok'
        res_dq = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": dq_esc}}},
        )
        self.assertEqual(
            res_dq["overwrite"]["CommandLine"],
            r'~/.optmem/memo note "[slice-player] Ends with backslash-space \ " && echo ok',
        )

        # 2. ReDoS resistance: both 30 quoted env assignments AND unquoted `FOO=aaa...a" memo` must finish < 0.5s
        for adv_cmd in (
            " ".join([f'A{i}="1"' for i in range(30)]) + " timeout -k 1 -s 9 2 echo memo",
            'FOO=' + ('a' * 30) + '" memo',
        ):
            with self.subTest(adv_cmd=adv_cmd):
                t0 = time.monotonic()
                res_redos = run_hook(
                    "pre-tool-use",
                    {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": adv_cmd}}},
                )
                elapsed = time.monotonic() - t0
                self.assertEqual(res_redos, {"decision": "allow"})
                self.assertLess(elapsed, 0.5, f"ReDoS regression: took {elapsed:.2f}s")

    def test_herestring_empty_heredoc_strict_closing_delim_and_quoted_cd_semantics(self):
        ws = ["/home/gohans-linux/projects/slice-player"]

        # 1. Herestring `<<<` before `memo note` must NOT be misparsed as an unclosed heredoc `<<`
        hs_before = 'cat <<< hello > /dev/null\n~/.optmem/memo note "After herestring"'
        res_hs = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": hs_before}}},
        )
        self.assertEqual(
            res_hs["overwrite"]["CommandLine"],
            'cat <<< hello > /dev/null\n~/.optmem/memo note "[slice-player] After herestring"',
        )

        # 2. Empty heredoc `cat <<EOF\nEOF` before `memo note` must close properly
        empty_hd = 'cat <<EOF > /dev/null\nEOF\n~/.optmem/memo note "After empty heredoc"'
        res_empty = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": empty_hd}}},
        )
        self.assertEqual(
            res_empty["overwrite"]["CommandLine"],
            'cat <<EOF > /dev/null\nEOF\n~/.optmem/memo note "[slice-player] After empty heredoc"',
        )

        # 3. Indented `  EOF` inside `<<'EOF'` (without `-`) does NOT close the heredoc in bash
        indented_eof = 'cat <<\'EOF\' > doc.md\nfirst line\n  EOF\n~/.optmem/memo note "example"\nEOF'
        res_indented = run_hook(
            "pre-tool-use",
            {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": indented_eof}}},
        )
        self.assertEqual(res_indented, {"decision": "allow"})

        # 4. Single-quoted `cd '$HOME/...'` and quoted `cd "~/..."` do NOT expand `$HOME` or `~` in bash
        for literal_cd in (
            'cd \'$HOME/projects/other-repo\' || ~/.optmem/memo note "Fact"',
            'cd "~/projects/other-repo" || ~/.optmem/memo note "Fact"',
            'cd \'~/projects/other-repo\' || ~/.optmem/memo note "Fact"',
        ):
            with self.subTest(literal_cd=literal_cd):
                res_cd = run_hook(
                    "pre-tool-use",
                    {"workspacePaths": ws, "toolCall": {"name": "run_command", "args": {"CommandLine": literal_cd}}},
                )
                self.assertIn(
                    '"[slice-player] Fact"',
                    res_cd["overwrite"]["CommandLine"],
                )

    def test_explicit_is_subagent_flag_applies_subagent_rules_for_other_hosts(self):
        base = {"workspacePaths": ["/home/gohans-linux/projects/slice-player"]}
        memo_call = {"toolCall": {"name": "run_command", "args": {"CommandLine": "~/.optmem/memo wake"}}}
        self.assertEqual(run_hook("session-start", {**base, "isSubagent": True}), {})
        self.assertEqual(run_hook("pre-tool-use", {**base, **memo_call, "isSubagent": True}).get("decision"), "deny")
        self.assertEqual(run_hook("pre-tool-use", {**base, **memo_call, "isSubagent": False}).get("decision"), "allow")


if __name__ == "__main__":
    unittest.main()
