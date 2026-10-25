# 课代表 Agent（Todo MCP Agent）

基于 MCP 的待办管家，全部代码在一个文件里：`todo_agent.py`。

同一个文件有两种运行身份：

- `python todo_agent.py`：客户端，命令行对话 + 大模型 + ReAct 循环；
- `python todo_agent.py --server`：MCP 服务端，在 stdio 上暴露 3 个工具。

客户端会以子进程方式拉起 `--server` 模式，两者通过 stdin/stdout 上的 JSON-RPC 通信，所以既是"一个程序"，又保留了真实的 MCP 进程边界。

记录待办时会补全详细信息：截止时间、重要程度（高/中/低）、所属课程。模型漏填的字段，服务端会从原话里推导（"明天""下周三""三天后"、以及"急/重要/不急"）。

## 运行

```bash
cp .env.example .env          # Windows: copy .env.example .env
# 编辑 .env，填入 LLM_API_KEY（DeepSeek / 千问 / GLM 等 OpenAI 兼容接口）

python todo_agent.py
```

没有配 Key 时程序会直接提示先填写 `.env`。

对话示例：

```text
你 > 周五交软件工程实验报告，挺急的
[工具] add_todo({"text": "写软件工程实验报告", "due": "2026-10-30", "priority": "high", "course": "软件工程"})
[结果] 已添加 #1：写软件工程实验报告（软件工程，高优先级，截止 2026-10-30（周五，还剩 5 天））。
```

## 工具

| 工具 | 作用 |
| --- | --- |
| `add_todo(text, due, priority, course)` | 新增待办，记录截止时间、重要程度、课程；缺的字段自动推导 |
| `list_todos()` | 查看待办，返回序号、重要程度、课程、截止时间 |
| `delete_todo(index)` | 按序号删除 |

## 项目结构

```text
todo-mcp-agent/
├── todo_agent.py            # 客户端 + MCP 服务端 + 3 个工具
├── tests/test_todo_agent.py # 6 个测试
├── .env.example
└── README.md
```

## 测试

```bash
python -m pytest tests -q     # 6 passed
```
