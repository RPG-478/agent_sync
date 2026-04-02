"""Integration test for agent_sync v6 — server + hooks.

Run: python agent_sync/tests/test_v6.py
  or: pytest agent_sync/tests/test_v6.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

# Ensure repo root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

PORT = 19876  # Test port (avoid clashing with real server)


# ━━━ TCP helper ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def tcp_cmd(cmd: dict, port: int = PORT, timeout: float = 5) -> dict:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((json.dumps(cmd) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    writer.close()
    return json.loads(line.decode().strip())


# ━━━ Server lifecycle ━━━━━━━━━━━━━━━━━━━━━━━━

async def start_server(port: int = PORT):
    from agent_sync.server_v6 import run_server, S
    # Reset state
    S.phase = "IMPLEMENT"
    S.round_number = 1
    S.agents.clear()
    S.mailboxes.clear()
    S.mail_events.clear()
    S.implementer = ""
    S.discuss_done.clear()
    S.discussion.clear()
    S.test_result = None

    task = asyncio.create_task(run_server("127.0.0.1", port))
    await asyncio.sleep(0.3)  # let server bind
    return task


# ━━━ Tests ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_join_and_status():
    """Test: two agents join, status reflects both."""
    r = await tcp_cmd({"cmd": "join", "agent": "agent-a"})
    assert r["ok"], f"join agent-a failed: {r}"
    assert r["phase"] == "IMPLEMENT"

    r = await tcp_cmd({"cmd": "join", "agent": "agent-b"})
    assert r["ok"], f"join agent-b failed: {r}"

    r = await tcp_cmd({"cmd": "status"})
    assert r["ok"]
    assert "agent-a" in r["data"]["agents"]
    assert "agent-b" in r["data"]["agents"]
    assert r["data"]["phase"] == "IMPLEMENT"
    print("  ✓ join_and_status")


async def test_peek_empty():
    """Test: peek returns 0 pending when no messages."""
    r = await tcp_cmd({"cmd": "peek", "agent": "agent-a"})
    assert r["ok"]
    assert r["pending"] == 0
    assert r["phase"] == "IMPLEMENT"
    print("  ✓ peek_empty")


async def test_send_and_peek():
    """Test: send a message, peek shows 1 pending."""
    r = await tcp_cmd({"cmd": "send", "agent": "agent-b", "to": "agent-a",
                        "text": "hello from b"})
    assert r["ok"]

    r = await tcp_cmd({"cmd": "peek", "agent": "agent-a"})
    assert r["ok"]
    assert r["pending"] == 1
    print("  ✓ send_and_peek")


async def test_listen():
    """Test: listen retrieves the pending message."""
    r = await tcp_cmd({"cmd": "listen", "agent": "agent-a", "timeout": 2})
    assert r["ok"]
    assert len(r["messages"]) == 1
    assert r["messages"][0]["text"] == "hello from b"

    # After listen, peek should be 0
    r = await tcp_cmd({"cmd": "peek", "agent": "agent-a"})
    assert r["pending"] == 0
    print("  ✓ listen")


async def test_impl_done_transition():
    """Test: impl-done transitions IMPLEMENT → TEST."""
    r = await tcp_cmd({"cmd": "impl-done", "agent": "agent-a",
                        "summary": "added feature X"})
    assert r["ok"]
    assert r["phase"] == "TEST"

    r = await tcp_cmd({"cmd": "status"})
    assert r["data"]["phase"] == "TEST"
    print("  ✓ impl_done → TEST")


async def test_test_result_transition():
    """Test: test-result transitions TEST → DISCUSS."""
    r = await tcp_cmd({"cmd": "test-result", "agent": "agent-b",
                        "passed": True, "output": "3 passed", "failures": []})
    assert r["ok"]
    assert r["passed"] is True

    r = await tcp_cmd({"cmd": "status"})
    assert r["data"]["phase"] == "DISCUSS"
    print("  ✓ test_result → DISCUSS")


async def test_discuss_cycle():
    """Test: discuss messages forwarded, both discuss-done → IMPLEMENT round+1."""
    # agent-a discusses
    r = await tcp_cmd({"cmd": "discuss", "agent": "agent-a",
                        "text": "looks good, ship it"})
    assert r["ok"]

    # agent-b should have a message
    r = await tcp_cmd({"cmd": "peek", "agent": "agent-b"})
    assert r["pending"] >= 1

    # Drain agent-b's messages (phase_change + discuss)
    r = await tcp_cmd({"cmd": "listen", "agent": "agent-b", "timeout": 1})
    assert r["ok"]

    # agent-b discusses back
    r = await tcp_cmd({"cmd": "discuss", "agent": "agent-b",
                        "text": "agreed, next round I implement"})
    assert r["ok"]

    # Both signal done
    r = await tcp_cmd({"cmd": "discuss-done", "agent": "agent-a",
                        "next_implementer": "agent-b"})
    assert r["ok"]

    r = await tcp_cmd({"cmd": "discuss-done", "agent": "agent-b",
                        "next_implementer": "agent-b"})
    assert r["ok"]
    assert r["round"] == 2  # Round incremented

    r = await tcp_cmd({"cmd": "status"})
    assert r["data"]["phase"] == "IMPLEMENT"
    assert r["data"]["round"] == 2
    assert r["data"]["implementer"] == "agent-b"
    print("  ✓ discuss_cycle → IMPLEMENT round 2")


async def test_full_cycle():
    """Test: complete cycle IMPLEMENT→TEST→DISCUSS→IMPLEMENT is clean."""
    # Already at round 2 IMPLEMENT, implementer=agent-b
    r = await tcp_cmd({"cmd": "peek", "agent": "agent-b"})
    assert r["phase"] == "IMPLEMENT"
    assert r["round"] == 2
    print("  ✓ full_cycle (at round 2)")


async def test_say_user_intervention():
    """Test: user can send messages to agents."""
    r = await tcp_cmd({"cmd": "say", "text": "stop and review", "to": "agent-a"})
    assert r["ok"]

    r = await tcp_cmd({"cmd": "peek", "agent": "agent-a"})
    assert r["pending"] >= 1

    # Drain
    r = await tcp_cmd({"cmd": "listen", "agent": "agent-a", "timeout": 1})
    assert any(m["type"] == "say" for m in r["messages"])
    print("  ✓ say (user intervention)")


async def test_heartbeat():
    """Test: heartbeat updates last_heartbeat and returns phase/round."""
    r = await tcp_cmd({"cmd": "heartbeat", "agent": "agent-a"})
    assert r["ok"]
    assert "phase" in r
    assert "round" in r
    print("  ✓ heartbeat")


async def test_impl_done_non_implementer_rejected():
    """Test: impl-done from non-implementer is rejected."""
    # At this point phase=IMPLEMENT (post discuss cycle), implementer=agent-b
    r = await tcp_cmd({"cmd": "status"})
    assert r["data"]["phase"] == "IMPLEMENT"
    implementer = r["data"]["implementer"]
    non_implementer = "agent-a" if implementer == "agent-b" else "agent-b"

    r = await tcp_cmd({"cmd": "impl-done", "agent": non_implementer,
                        "summary": "should be rejected"})
    assert not r["ok"], f"Expected rejection but got: {r}"
    assert "implementer" in r.get("error", "")
    print(f"  ✓ impl-done rejected for non-implementer ({non_implementer})")


async def test_broadcast_no_echo():
    """Test: broadcast does not echo back to the sender."""
    # Drain any pending messages first
    await tcp_cmd({"cmd": "listen", "agent": "agent-a", "timeout": 1})
    await tcp_cmd({"cmd": "listen", "agent": "agent-b", "timeout": 1})

    r = await tcp_cmd({"cmd": "broadcast", "agent": "agent-a", "text": "no-echo test"})
    assert r["ok"]

    # Sender (agent-a) should NOT have a pending message
    r_a = await tcp_cmd({"cmd": "peek", "agent": "agent-a"})
    assert r_a["pending"] == 0, f"Sender got their own broadcast: pending={r_a['pending']}"

    # Receiver (agent-b) should have the message
    r_b = await tcp_cmd({"cmd": "peek", "agent": "agent-b"})
    assert r_b["pending"] >= 1, "Receiver did not get broadcast"

    # Drain
    await tcp_cmd({"cmd": "listen", "agent": "agent-b", "timeout": 1})
    print("  ✓ broadcast no-echo to sender")


async def test_discuss_wrong_phase_rejected():
    """Test: discuss and discuss-done are rejected outside DISCUSS phase."""
    r = await tcp_cmd({"cmd": "status"})
    assert r["data"]["phase"] == "IMPLEMENT"

    r = await tcp_cmd({"cmd": "discuss", "agent": "agent-a", "text": "premature discuss"})
    assert not r["ok"]
    assert "DISCUSS" in r.get("error", "")

    r = await tcp_cmd({"cmd": "discuss-done", "agent": "agent-a"})
    assert not r["ok"]
    assert "DISCUSS" in r.get("error", "")
    print("  ✓ discuss/discuss-done rejected outside DISCUSS phase")


async def test_shutdown():
    """Test: shutdown transitions to SHUTDOWN."""
    r = await tcp_cmd({"cmd": "shutdown", "reason": "test complete"})
    assert r["ok"]

    r = await tcp_cmd({"cmd": "status"})
    assert r["data"]["phase"] == "SHUTDOWN"
    print("  ✓ shutdown")


# ━━━ Hook script tests (async subprocess to keep event loop alive) ━━━

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


async def _run_hook(script: str, hook_input: str,
                    env_extra: dict | None = None) -> dict:
    """Run a hook script as async subprocess, return parsed JSON output."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env, cwd=REPO_ROOT,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(hook_input.encode()), timeout=10)
    assert proc.returncode == 0, f"{script} failed (rc={proc.returncode}): {stderr.decode()}"
    return json.loads(stdout.decode().strip())


async def test_hook_block_stop():
    """Test block_stop.py: with running server, blocks stop."""
    hook_input = json.dumps({
        "hookEventName": "Stop",
        "stop_hook_active": False,
        "timestamp": "2026-01-01T00:00:00Z",
        "cwd": os.getcwd(),
        "sessionId": "test-session",
    })
    out = await _run_hook(
        ".github/hooks/block_stop.py", hook_input,
        {"AGENT_SYNC_NAME": "agent-a", "AGENT_SYNC_PORT": str(PORT)},
    )
    assert "hookSpecificOutput" in out
    assert out["hookSpecificOutput"]["decision"] == "block"
    assert "listen" in out["hookSpecificOutput"]["reason"]
    print("  ✓ hook block_stop (blocks when server active)")


async def test_hook_block_stop_shutdown():
    """Test block_stop.py: with SHUTDOWN phase, allows stop."""
    await tcp_cmd({"cmd": "set-phase", "phase": "SHUTDOWN"})

    hook_input = json.dumps({
        "hookEventName": "Stop",
        "stop_hook_active": False,
    })
    out = await _run_hook(
        ".github/hooks/block_stop.py", hook_input,
        {"AGENT_SYNC_NAME": "agent-a", "AGENT_SYNC_PORT": str(PORT)},
    )
    assert "hookSpecificOutput" not in out
    print("  ✓ hook block_stop (allows when SHUTDOWN)")


async def test_hook_check_messages():
    """Test check_messages.py: returns additionalContext when messages pending."""
    await tcp_cmd({"cmd": "set-phase", "phase": "IMPLEMENT"})
    # Drain any phase_change broadcasts first
    await tcp_cmd({"cmd": "listen", "agent": "agent-a", "timeout": 1})
    await tcp_cmd({"cmd": "send", "agent": "agent-b", "to": "agent-a", "text": "test msg"})

    hook_input = json.dumps({
        "hookEventName": "PostToolUse",
        "tool_name": "run_in_terminal",
        "tool_call_id": "test",
    })
    out = await _run_hook(
        ".github/hooks/check_messages.py", hook_input,
        {"AGENT_SYNC_NAME": "agent-a", "AGENT_SYNC_PORT": str(PORT)},
    )
    assert "hookSpecificOutput" in out
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "agent_sync" in ctx
    assert "pending" in hook_input or len(ctx) > 10  # has content
    print("  ✓ hook check_messages (detects pending)")


async def test_hook_check_messages_skip_readonly():
    """Test check_messages.py: skips peek for read-only tools."""
    hook_input = json.dumps({
        "hookEventName": "PostToolUse",
        "tool_name": "read_file",
    })
    out = await _run_hook(
        ".github/hooks/check_messages.py", hook_input,
        {"AGENT_SYNC_NAME": "agent-a", "AGENT_SYNC_PORT": str(PORT)},
    )
    assert "hookSpecificOutput" not in out
    print("  ✓ hook check_messages (skips read_file)")


async def test_hook_block_questions():
    """Test block_questions.py: blocks vscode_askQuestions."""
    hook_input = json.dumps({
        "hookEventName": "PreToolUse",
        "tool_name": "vscode_askQuestions",
    })
    out = await _run_hook(".github/hooks/block_questions.py", hook_input)
    assert out["hookSpecificOutput"]["decision"] == "block"
    print("  ✓ hook block_questions (blocks askQuestions)")

    # Non-blocked tool should pass
    hook_input2 = json.dumps({"hookEventName": "PreToolUse", "tool_name": "run_in_terminal"})
    out2 = await _run_hook(".github/hooks/block_questions.py", hook_input2)
    assert "hookSpecificOutput" not in out2
    print("  ✓ hook block_questions (allows run_in_terminal)")


# ━━━ Runner ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def run_server_tests():
    print(f"\n{'='*60}")
    print(f"agent_sync v6 - Integration Tests (port {PORT})")
    print(f"{'='*60}\n")

    server_task = await start_server(PORT)
    try:
        print("[Server Tests]")
        await test_join_and_status()
        await test_peek_empty()
        await test_send_and_peek()
        await test_listen()
        await test_impl_done_transition()
        await test_test_result_transition()
        await test_discuss_cycle()
        await test_full_cycle()
        await test_heartbeat()
        await test_broadcast_no_echo()
        await test_discuss_wrong_phase_rejected()
        await test_impl_done_non_implementer_rejected()
        await test_say_user_intervention()

        print("\n[Hook Script Tests]")
        # Reset phase for hook tests
        await tcp_cmd({"cmd": "set-phase", "phase": "IMPLEMENT"})
        await test_hook_block_stop()
        await test_hook_block_stop_shutdown()
        await test_hook_check_messages()
        await test_hook_check_messages_skip_readonly()
        await test_hook_block_questions()

        await test_shutdown()

        print(f"\n{'='*60}")
        print("ALL TESTS PASSED ✓")
        print(f"{'='*60}\n")

    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


def main():
    asyncio.run(run_server_tests())


if __name__ == "__main__":
    main()
