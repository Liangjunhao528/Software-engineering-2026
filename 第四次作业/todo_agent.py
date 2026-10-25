#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课代表 Agent：单文件 MCP 待办智能体。

    python todo_agent.py            # 客户端：对话 + 大模型 + ReAct 循环
    python todo_agent.py --server   # MCP 服务端：stdio 上收发 JSON-RPC
"""
import json, os, re, subprocess, sys, urllib.error, urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
WD = "一二三四五六日"
LABEL = {"high": "高", "medium": "中", "low": "低"}
ALIAS = {"high": "high", "medium": "medium", "low": "low", "高": "high", "中": "medium", "低": "low",
         "重要": "high", "一般": "medium", "不急": "low"}
COURSES = ["软件工程", "高数", "高等数学", "英语", "数据库", "计算机网络", "操作系统", "数据结构", "大学物理"]
SYSTEM = f"""你是「课代表」，一个待办助手。今天是 {date.today():%Y-%m-%d}（星期{WD[date.today().weekday()]}）。
记待办时补全：due（把「明天/下周三/三天后」换算成 YYYY-MM-DD，没说就留空）、
priority（急/重要→high，普通→medium，不急→low）、course（能判断就填）。
用户要记、看、删待办时调用工具；删除前先 list_todos 确认序号。回答简洁，并复述记下的关键信息。"""

TODOS = []

class ToolError(Exception):
    """工具执行失败：包成 isError=true 的结果交还给模型。"""

def guess_due(text):
    today = date.today()
    if m := re.search(r"\d{4}-\d{2}-\d{2}", text):
        return m.group(0)
    if m := re.search(r"(\d{1,2})月(\d{1,2})[日号]", text):
        try:
            return date(today.year, int(m[1]), int(m[2])).isoformat()
        except ValueError:
            return ""
    for word, days in (("今天", 0), ("明天", 1), ("后天", 2)):
        if word in text:
            return (today + timedelta(days=days)).isoformat()
    if m := re.search(r"(\d+)\s*天后", text):
        return (today + timedelta(days=int(m[1]))).isoformat()
    for prefix, week in ((r"下(?:个)?(?:周|星期)", 7), (r"(?:周|星期)", 0)):
        if m := re.search(prefix + r"([一二三四五六日天])", text):
            monday = today - timedelta(days=today.weekday()) + timedelta(days=week)
            target = monday + timedelta(days=WD.index(m[1].replace("天", "日")))
            return (target + timedelta(days=7) if target < today else target).isoformat()
    return ""

def guess_priority(text):
    if re.search(r"不急|有空|随便|之后再说", text):
        return "low"
    return "high" if re.search(r"急|重要|尽快|马上|赶|ddl", text, re.I) else "medium"

def due_text(due):
    if not due:
        return "未设截止时间"
    target = date.fromisoformat(due)
    left = (target - date.today()).days
    if left < 0:
        return f"截止 {due}（周{WD[target.weekday()]}，已逾期 {-left} 天）"
    if left == 0:
        return f"截止 {due}（周{WD[target.weekday()]}，今天截止）"
    return f"截止 {due}（周{WD[target.weekday()]}，还剩 {left} 天）"

def add_todo(text="", due="", priority="medium", course=""):
    text = (text or "").strip()
    if not text:
        raise ToolError("待办内容不能为空。")
    raw_due = (due or "").strip()
    due = raw_due or guess_due(text)
    if raw_due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_due):
        due = guess_due(raw_due)
        if not due:
            raise ToolError(f"无法识别的截止日期：{raw_due}")
    if due:
        try:
            due = date.fromisoformat(due).isoformat()
        except ValueError as exc:
            raise ToolError(f"截止日期不存在：{due}。") from exc
    raw = (priority or "").strip()
    priority = ALIAS.get(raw.lower()) or ALIAS.get(raw)
    if raw and not priority:
        raise ToolError("priority 只能是 high / medium / low。")
    if not priority or priority == "medium":
        priority = guess_priority(text)
    course = (course or "").strip() or next((c for c in COURSES if c in text), "其他")
    TODOS.append({"text": text, "due": due, "priority": priority, "course": course})
    return f"已添加 #{len(TODOS)}：{text}（{course}，{LABEL[priority]}优先级，{due_text(due)}）。"

def list_todos():
    if not TODOS:
        return "当前没有待办。"
    lines = [f"#{i} [{LABEL[t['priority']]}] {t['text']} · {t['course']} · {due_text(t['due'])}"
             for i, t in enumerate(TODOS, 1)]
    return "当前待办：\n" + "\n".join(lines)

def delete_todo(index=0):
    try:
        index = int(index)
    except (TypeError, ValueError) as exc:
        raise ToolError("index 必须是整数。") from exc
    if not 1 <= index <= len(TODOS):
        raise ToolError(f"序号 {index} 不存在，当前共 {len(TODOS)} 条待办。")
    return f"已删除 #{index}：{TODOS.pop(index - 1)['text']}"

TOOLS = [
    {"name": "add_todo",
     "description": "新增待办：text 内容；due 截止日期 YYYY-MM-DD（把「下周三」换算好，没有就留空）；"
                    "priority 重要程度 high/medium/low；course 课程名。",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}, "due": {"type": "string"},
                                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                                    "course": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "list_todos", "description": "查看全部待办（序号、重要程度、课程、截止时间）。删除前先确认序号。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "delete_todo", "description": "按序号删除待办。",
     "inputSchema": {"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"]}},
]
HANDLERS = {"add_todo": add_todo, "list_todos": list_todos, "delete_todo": delete_todo}

def handle(msg):
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None  # 通知，不回复
    if method == "initialize":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion") or "2024-11-05",
            "capabilities": {"tools": {}}, "serverInfo": {"name": "classrep-todo", "version": "1.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, args = (msg.get("params") or {}).get("name", ""), (msg.get("params") or {}).get("arguments") or {}
        try:
            if name not in HANDLERS:
                raise ToolError(f"未知工具 {name!r}，可用：{', '.join(HANDLERS)}。")
            text, failed = HANDLERS[name](**args), False
        except ToolError as exc:
            text, failed = f"工具执行失败：{exc}", True
        except TypeError as exc:
            text, failed = f"{name} 的参数不对（{exc}），请对照 inputSchema。", True
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": text}], "isError": failed}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}

def server_main():
    for line in sys.stdin.buffer:
        line = line.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()

class MCPClient:
    def __init__(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        self.proc = subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), "--server"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", env=env, cwd=str(BASE))
        self._id = 0

    def request(self, method, params=None):
        self._id += 1
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP 服务器提前退出")
        message = json.loads(line)
        if "error" in message:
            raise RuntimeError(message["error"]["message"])
        return message["result"]

    def start(self):
        self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "classrep", "version": "1.0"}})
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()

    def tools(self):
        return self.request("tools/list")["tools"]

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        return (not result.get("isError")), "\n".join(b["text"] for b in result["content"])

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=3)

class LLMClient:
    def __init__(self, base_url, model, api_key):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.api_key = model, api_key

    def chat(self, messages, tools):
        request = urllib.request.Request(
            self.url, data=json.dumps({"model": self.model, "messages": messages, "tools": tools,
                                       "temperature": 0.2}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))["choices"][0]["message"]
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"模型接口返回 {exc.code}：{exc.read().decode('utf-8', 'replace')[:200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"连不上模型接口：{exc.reason}") from exc

class Agent:
    def __init__(self, model, mcp):
        self.model, self.mcp = model, mcp
        self.tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": t["inputSchema"]}} for t in mcp.tools()]
        self.messages = [{"role": "system", "content": SYSTEM}]

    def run(self, text):
        self.messages.append({"role": "user", "content": text})
        for _ in range(6):
            message = self.model.chat(self.messages, self.tools)
            calls = message.get("tool_calls") or []
            if not calls:
                answer = (message.get("content") or "").strip()
                self.messages.append({"role": "assistant", "content": answer})
                return answer
            self.messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
            for call in calls:
                name, raw = call["function"]["name"], call["function"]["arguments"]
                arguments = json.loads(raw or "{}")
                print(f"[工具] {name}({json.dumps(arguments, ensure_ascii=False)})")
                try:
                    _, result = self.mcp.call(name, arguments)
                except Exception as exc:
                    result = f"调用失败：{exc}"
                print("[结果] " + result.replace("\n", "\n       "))
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        return "这轮没处理完，先停一下，请换个说法再试。"

def load_env(path):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

def client_main():
    load_env(BASE / ".env")
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        print("未找到 LLM_API_KEY，程序无法调用大模型。")
        print("请复制 .env.example 为 .env，并填入你的 API Key：")
        print("    LLM_API_KEY=sk-xxxxxxxx")
        print("（DeepSeek / 通义千问 / 智谱 GLM 等 OpenAI 兼容接口都可以）")
        return 1
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    mcp = MCPClient()
    try:
        mcp.start()
        agent = Agent(LLMClient(os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"), model, api_key), mcp)
        print(f"== 课代表 Agent · MCP 待办 ==\n模型：{model}\n工具：add_todo, list_todos, delete_todo")
        print("输入 /quit 退出\n")
        while True:
            try:
                line = input("你 > ").strip().lstrip("\ufeff")
            except (EOFError, KeyboardInterrupt):
                break
            if line in ("/quit", "/exit"):
                break
            if line:
                try:
                    print("[回答] " + agent.run(line) + "\n")
                except Exception as exc:
                    print(f"[错误] {exc}\n")
    finally:
        mcp.close()
    return 0

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if "--server" in sys.argv[1:]:
        server_main()
        return 0
    return client_main()

if __name__ == "__main__":
    sys.exit(main())
