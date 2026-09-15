# sonic：从 Harness 工程走向通用 AI 助手

`sonic` 的目标是成为聪明、强大且可信的通用人工智能助手。我们先把一个垂直场景做成真正可用的产品，再验证同一运行内核能否支持更多任务。当前仓库仍处在**教学内核阶段**：可以运行 FakeProvider 演示和 29 项测试，尚不能自行修复真实仓库。

仓库有三条互相配合、但不混写的主线：

| 你想做什么 | 从这里开始 | 读完能得到什么 |
| --- | --- | --- |
| 系统学习 Harness | [文档学习地图](./文档/README.md) | 从任务例子理解循环、状态、工具、恢复、上下文与评测；再深入比较公开项目。 |
| 理解并运行 sonic | [sonic 设计](./文档/sonic设计/README.md) → [代码](./代码/sonic/README.md) | 看清目标架构与当前实现的差距，运行可审计的教学内核。 |
| 准备面试并跟进外部问题 | [面经入口](./面经/README.md) | 按主题查问题、工程答案、来源及每周新增/纠错。 |

## 现在实际能做什么

当前 `代码/sonic` 是不需要 API Key 的 Python 标准库教学实现：FakeProvider、模型/工具循环、JSONL/SQLite 事件、可重建 RunState、显式完成契约、模型/工具上限、截止时间/取消与精确重复观察停止，以及 29 项自动化测试。它**没有**真实模型接入、RepoFix 闭环、真实沙箱、跨进程副作用去重或恢复继续执行。逐项证据见[能力状态表](./文档/sonic设计/02-能力状态.md)。

在 `代码/sonic` 目录快速验证：

```powershell
$env:PYTHONPATH = "src"
python examples/demo.py
python -m unittest discover -s tests -v
```

若系统的 `python` 不可用，请换成已安装的 Python 3.10+ 可执行文件。演示的 `completed` 仅由固定文本契约验收，不等于完成真实代码修复。

## 如何继续演进

第一垂直场景建议为**受限的仓库问题助手**：先只读定位，再在经授权的隔离工作区修改、测试并交付 diff 与证据。核心不得写死 RepoFix；第二个只读资料研究场景需要复用同一运行内核。路线与每阶段门禁见[演进路线](./文档/sonic设计/04-演进路线.md)。

所有修改以最新 GitHub `main` 为基准，验证后同步远端；具体规则见 [AGENTS.md](./AGENTS.md) 和 [CONTRIBUTING.md](./CONTRIBUTING.md)。仓库不保存与源码重复的生成 ZIP；下载离线包应使用具体提交的 GitHub 源码归档或带版本的 Release。
