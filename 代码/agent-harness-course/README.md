# Agent Harness Course：TraceForge 最小实现

这是《Harness 工程教学》的配套代码。它用 Python 标准库实现一条可运行、可测试的 Agent Harness 主链路，不需要 API Key，也不访问网络。

## 你会看到什么

- `AgentRunner`：拥有模型/工具循环和明确终态；
- `FakeProvider`：用脚本化响应替代真实模型；
- `JsonlEventStore`：按顺序追加运行事件；
- `ToolRegistry` 与 `ToolRuntime`：把工具实现和执行治理分开；
- `DenyPathPolicy`：在执行前拒绝敏感路径；
- `EffectJournal`：缓存完成结果，避免重复副作用；
- `ContextBuilder`：按来源、优先级和预算构造上下文；
- `project_run`：从事件重建只读运行摘要；
- 21 个自动化测试：覆盖成功、拒绝、失败、幂等和恢复语义。

## 目录

```text
agent-harness-course/
├── examples/demo.py
├── src/traceforge_harness/
│   ├── context.py
│   ├── events.py
│   ├── model.py
│   ├── projections.py
│   ├── runner.py
│   └── tools.py
└── tests/
```

## 运行演示

Windows PowerShell：

```powershell
$env:PYTHONPATH = "src"
python examples/demo.py
```

macOS / Linux：

```bash
PYTHONPATH=src python examples/demo.py
```

演示会让 FakeProvider 先调用 `add` 工具，再返回最终回答，并打印事件投影。

## 运行测试

Windows PowerShell：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

macOS / Linux：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

预期结果：`Ran 21 tests`，全部通过。

## 推荐阅读顺序

1. `model.py`：理解模型边界为什么可以被替换；
2. `events.py`：理解事件为何是运行事实；
3. `tools.py`：观察策略检查与 Effect Journal；
4. `runner.py`：沿一次完整循环阅读；
5. `projections.py`：从事实生成可查询状态；
6. `tests/`：把失败语义当成公开契约阅读。

## 从课程代码继续演进

这个实现有意保持小型和同步。下一步可以依次加入 SQLite Event Store、真实 Provider、审批挂起/恢复、工作区沙箱和固定 RepoFix 评测集。不要先加入多 Agent；先用评测证明单 Agent 的瓶颈在哪里。

更完整的取舍与路线见仓库中的 `学习/TraceForge-Agent-Harness-项目设计文档.md`。

