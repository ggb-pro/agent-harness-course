# Agent Harness Course：TraceForge 最小实现

这是《Harness 工程教学》的配套代码。它用 Python 标准库实现一条可运行、可测试的 Agent Harness 主链路，不需要 API Key，也不访问网络。

## 你会看到什么

- `AgentRunner`：模型/工具循环；在每轮和每个 Tool 前检查模型轮次、工具次数、截止时间与取消请求；相同动作和观察连续重复时停止；没有完成契约时返回 `unverified`；
- `FakeProvider`：用脚本化响应替代真实模型；
- `JsonlEventStore`：按顺序追加运行事件；
- `SqliteEventStore`：事务追加与 `expected_revision` 比较，重开数据库仍可重建 RunState；仅保证本地事件提交，不保证外部 Tool 副作用原子；
- `ToolRegistry` 与 `ToolRuntime`：把工具实现和执行治理分开；
- `DenyPathPolicy`：在执行前拒绝敏感路径；
- `EffectJournal`：在同一进程内缓存完成结果；当前未持久化，不能保证崩溃后的副作用去重；
- `ContextBuilder`：按来源、优先级和预算构造上下文；
- `project_run`：从事件重建只读运行摘要；
- `project_state`：检查连续序号与终态，从事件恢复 model/tool 次数、限制和 revision；
- `CompletionContract`：显式决定 `completed/failed/unverified`；演示中的 `ExactTextCompletion` 只验证固定文本，不验证 RepoFix 副作用；
- 29 个自动化测试：新增虚假完成、SQLite 重开与冲突、工具上限、取消、截止时间和精确重复观察边界；仍不覆盖跨进程副作用恢复。

## 目录

```text
agent-harness-course/
├── examples/demo.py
├── src/traceforge_harness/
│   ├── context.py
│   ├── completion.py
│   ├── events.py
│   ├── model.py
│   ├── projections.py
│   ├── runner.py
│   ├── state.py
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

演示会让 FakeProvider 先调用 `add` 工具，再返回最终回答；固定文本验收契约通过后才显示 `completed`，并打印事件投影。

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

预期结果：`Ran 29 tests`，全部通过。

## 推荐阅读顺序

1. `model.py`：理解模型边界为什么可以被替换；
2. `events.py` 与 `state.py`：理解事务事件与可重建状态；
3. `tools.py`：观察策略检查与 Effect Journal；
4. `runner.py` 与 `completion.py`：沿一次完整循环与验收边界阅读；
5. `projections.py`：从事实生成可查询状态；
6. `tests/`：把失败语义当成公开契约阅读。

## 从课程代码继续演进

这个实现仍是小型同步原型。SQLite 已用于**本地事件事务**，但尚无恢复执行、持久化 Effect 意图/receipt、真实 Provider、RepoFix Verifier、工作区沙箱或固定 RepoFix 评测集。当前预算只覆盖模型轮次、工具次数和截止时间；重复检测只识别**相同动作与相同完整观察**，时间戳等变化仍可掩盖语义震荡。token/费用、进程组取消传播和更稳健的进展指纹尚未实现。下一阶段先完成 Tool Manifest、Context 接入、真实路径与副作用对账，再开放 RepoFix 写操作；多 Agent 要由单 Agent 评测证明需求。

更完整的取舍与路线见[TraceForge 问题驱动设计与面试答案](../../面经/TraceForge-问题驱动设计与面试答案.md)。

