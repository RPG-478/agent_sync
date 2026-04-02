"""Tests for agent_sync.notifier — notification watcher system."""
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Use the notifier module directly
from agent_sync.notifier import (
    check_notifications,
    clear_notifications,
    _write_notification,
    BASE,
)


@pytest.fixture(autouse=True)
def cleanup_notification_files():
    """Clean up notification files before and after each test."""
    agent = "agent-b"
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"
    # Cleanup before
    notif_file.unlink(missing_ok=True)
    bell_file.unlink(missing_ok=True)
    yield
    # Cleanup after
    notif_file.unlink(missing_ok=True)
    bell_file.unlink(missing_ok=True)


def test_write_notification_creates_files():
    """_write_notification should create both jsonl and bell files."""
    agent = "agent-b"
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"

    _write_notification(notif_file, bell_file, {
        "type": "test",
        "text": "hello",
        "ts": time.time(),
    })

    assert notif_file.exists()
    assert bell_file.exists()

    with open(notif_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["type"] == "test"
    assert data["text"] == "hello"


def test_write_notification_appends():
    """Multiple notifications should be appended to the same file."""
    agent = "agent-b"
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"

    _write_notification(notif_file, bell_file, {"type": "msg1", "ts": 1.0})
    _write_notification(notif_file, bell_file, {"type": "msg2", "ts": 2.0})
    _write_notification(notif_file, bell_file, {"type": "msg3", "ts": 3.0})

    with open(notif_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 3


def test_check_notifications_reads_and_acknowledges():
    """check_notifications should return all notifications and remove bell."""
    agent = "agent-b"
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"

    _write_notification(notif_file, bell_file, {"type": "phase_change", "ts": 1.0})
    _write_notification(notif_file, bell_file, {"type": "message", "text": "hi", "ts": 2.0})

    result = check_notifications(agent)
    assert len(result) == 2
    assert result[0]["type"] == "phase_change"
    assert result[1]["type"] == "message"

    # Bell should be removed after reading
    assert not bell_file.exists()


def test_check_notifications_no_bell_returns_empty():
    """If no bell file, check_notifications should return empty list."""
    result = check_notifications("agent-b")
    assert result == []


def test_clear_notifications_removes_all():
    """clear_notifications should remove both files."""
    agent = "agent-b"
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"

    _write_notification(notif_file, bell_file, {"type": "test", "ts": 1.0})
    assert notif_file.exists()
    assert bell_file.exists()

    clear_notifications(agent)
    assert not notif_file.exists()
    assert not bell_file.exists()


def test_check_notifications_handles_corrupt_jsonl():
    """check_notifications should skip corrupt lines gracefully."""
    agent = "agent-b"
    notif_file = BASE / f".notifications_{agent}.jsonl"
    bell_file = BASE / f".notify_bell_{agent}"

    with open(notif_file, "w", encoding="utf-8") as f:
        f.write('{"type": "good", "ts": 1.0}\n')
        f.write('THIS IS NOT JSON\n')
        f.write('{"type": "also_good", "ts": 2.0}\n')
    bell_file.touch()

    result = check_notifications(agent)
    assert len(result) == 2
    assert result[0]["type"] == "good"
    assert result[1]["type"] == "also_good"
