"""Тесты для desktop.core.husk"""

import json
import time
from urllib.request import Request, urlopen

import pytest

from desktop.core.husk import HuskManager, format_action_caption


def test_format_action_caption():
    assert "main.py" in format_action_caption("Edit", {"file_path": "src/main.py"})
    assert "pytest" in format_action_caption("Bash", {"command": "pytest -v"})
    assert "config.json" in format_action_caption("Read", {"file_path": "config.json"})
    assert "foo" in format_action_caption("Grep", {"pattern": "foo"})


def test_husk_manager_lifecycle_and_hooks(tmp_path):
    spoken = []
    notified = []

    manager = HuskManager(
        on_say=lambda text: spoken.append(text),
        on_notify=lambda t, m: notified.append((t, m)),
        storage_dir=str(tmp_path),
        port=19876,
    )

    manager.start()
    try:
        # Check discovery file exists
        disc = tmp_path / "husk-listener.json"
        assert disc.exists()
        disc_data = json.loads(disc.read_text(encoding="utf-8"))
        assert disc_data["port"] == 19876

        # Post a hook event (Tool start)
        req = Request(
            "http://127.0.0.1:19876/hook",
            data=json.dumps({
                "hook_event_name": "PreToolCall",
                "tool_name": "Edit",
                "tool_input": {"file_path": "agent.py"},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=3) as resp:
            assert resp.status == 200

        # Post an approval request
        req2 = Request(
            "http://127.0.0.1:19876/hook",
            data=json.dumps({
                "hook_event_name": "approval_required",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf build"},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req2, timeout=3) as resp2:
            assert resp2.status == 200

        time.sleep(0.1)

        assert any("подтвердить" in s for s in spoken)
        assert any("agent.py" in m[1] for m in notified)
        assert manager.stats.files_edited == 1
        assert manager.stats.approvals == 1

    finally:
        manager.stop()
