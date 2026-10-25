# -*- coding: utf-8 -*-
"""基础测试：待办字段、自动推导、MCP 协议、Agent 循环。

运行：python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import todo_agent as app  # noqa: E402


def setup_function():
    app.TODOS.clear()


def test_add_with_details():
    message = app.add_todo("写软件工程实验报告", "2026-10-30", "high", "软件工程")
    assert "高优先级" in message and "截止 2026-10-30" in message and "软件工程" in message
    assert app.TODOS[0] == {
        "text": "写软件工程实验报告",
        "due": "2026-10-30",
        "priority": "high",
        "course": "软件工程",
    }


def test_auto_derive_fields():
    next_wednesday = date.today() - timedelta(days=date.today().weekday()) + timedelta(days=9)
    app.add_todo("下周三交软件工程实验报告，挺急的")
    app.add_todo("明天复习英语，不急")
    first, second = app.TODOS
    assert first["due"] == next_wednesday.isoformat()
    assert first["priority"] == "high" and first["course"] == "软件工程"
    assert second["due"] == (date.today() + timedelta(days=1)).isoformat()
    assert second["priority"] == "low" and second["course"] == "英语"


def test_invalid_input():
    with pytest.raises(app.ToolError, match="不能为空"):
        app.add_todo("  ")
    with pytest.raises(app.ToolError, match="high / medium / low"):
        app.add_todo("写实验报告", priority="urgent")
    with pytest.raises(app.ToolError, match="不存在"):
        app.add_todo("写实验报告", due="2026-02-30")
    with pytest.raises(app.ToolError, match="不存在"):
        app.delete_todo(1)


def test_list_and_delete():
    app.add_todo("写软件工程实验报告", "2026-10-30", "high", "软件工程")
    text = app.list_todos()
    assert "#1 [高] 写软件工程实验报告 · 软件工程 · 截止 2026-10-30" in text
    assert "已删除 #1" in app.delete_todo(1)
    assert "没有待办" in app.list_todos()


def test_protocol():
    assert app.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    reply = app.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert reply["result"]["serverInfo"]["name"] == "classrep-todo"
    reply = app.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert {t["name"] for t in reply["result"]["tools"]} == {"add_todo", "list_todos", "delete_todo"}
    assert app.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"] == -32601
    reply = app.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "delete_todo", "arguments": {"index": 5}}}
    )
    assert reply["result"]["isError"] is True


class _FakeModel:
    """固定返回一次工具调用，再给出回答。"""

    def __init__(self):
        self.step = 0

    def chat(self, messages, tools):
        self.step += 1
        if self.step == 1:
            call = {
                "id": "c1",
                "type": "function",
                "function": {
                    "name": "add_todo",
                    "arguments": json.dumps({"text": "交实验报告", "due": "2026-10-30", "priority": "high"}),
                },
            }
            return {"role": "assistant", "content": "", "tool_calls": [call]}
        return {"role": "assistant", "content": "记好了"}


def test_agent_loop_roundtrip():
    """真跑一遍：`--server` 子进程 + ReAct 循环 + 工具执行。"""
    client = app.MCPClient()
    client.start()
    try:
        loop = app.Agent(_FakeModel(), client)
        assert loop.run("记一下交实验报告") == "记好了"
        ok, text = client.call("list_todos", {})
        assert ok and "交实验报告" in text and "高" in text
    finally:
        client.close()
