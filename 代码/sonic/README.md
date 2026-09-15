# sonic 代码：可审计的教学内核

这里是 sonic 产品的代码起点，不是已经能处理真实任务的通用助手。当前版本沿用旧课程原型的 0.3.0 教学基线，把包名改为 `sonic_agent` 并按责任重排模块；不需要 API Key，也不联网。能力和缺口的唯一汇总见[状态表](../../文档/sonic设计/02-能力状态.md)。

## 三分钟跑通

Windows PowerShell（进入本目录）：

```powershell
$env:PYTHONPATH = "src"
python examples/demo.py
python -m unittest discover -s tests -v
```

macOS / Linux：

```bash
PYTHONPATH=src python examples/demo.py
PYTHONPATH=src python -m unittest discover -s tests -v
```

需要 Python 3.10+。演示让 FakeProvider 调用 `add` 工具，再输出固定回答；只有 `ExactTextCompletion` 验证文本后才标为 `completed`。当前预期为 29 项测试通过。

## 从哪里读源码

```text
src/sonic_agent/
├─ core/
│  ├─ runner.py        模型/工具循环、预算、取消与终态
│  ├─ events.py        JSONL、SQLite 和内存事件
│  ├─ state.py         从事件重建运行状态
│  ├─ completion.py    显式完成契约
│  ├─ context.py       尚未接入 Runner 的上下文教学示例
│  └─ projections.py   可查询摘要
├─ models/model.py     Provider 边界与 FakeProvider
└─ capabilities/tools.py  Registry、示例策略、同进程 EffectJournal
```

先读 [Runner](./src/sonic_agent/core/runner.py) 和[循环测试](./tests/test_runner_projection.py)，再看[事件](./src/sonic_agent/core/events.py)、[状态](./src/sonic_agent/core/state.py)、[工具](./src/sonic_agent/capabilities/tools.py)与[完成契约](./src/sonic_agent/core/completion.py)。测试是失败语义的公开证据，不只用于“绿灯”。

## 不能把教学示例说成产品能力

SQLite 只保证本地事件事务，不保证外部 Tool 原子执行；`EffectJournal` 只是进程内字典；路径段拒绝不是沙箱；`ContextBuilder` 未接入 Runner；没有真实模型、可恢复继续执行、RepoFix Profile/Verifier 或固定真实任务评测。当前预算覆盖轮次、工具次数和截止时间，尚无 token/费用账本。目标边界见[架构](../../文档/sonic设计/01-架构与数据流.md)和[路线](../../文档/sonic设计/04-演进路线.md)。

未来新增 `safety/`、`memory/`、`interfaces/` 等模块时，以真实接口和测试落地为前提；不为满足目录树创建空架构。
