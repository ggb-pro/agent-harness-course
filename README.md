# Agent Harness：学习、代码与面经

本仓库按三个方向维护。学习材料用于建立概念和拆解源码；代码用于验证设计是否真的成立；面经把架构问题转化为可回答、可追问的工程证据。**仓库最新提交是文档的基准**，更新前先拉取 GitHub，更新后验证并推送。

| 方向 | 入口 | 内容与维护重点 |
| --- | --- | --- |
| 学习文档 | [从零理解 Agent Harness](./学习文档/从零理解Agent-Harness.md) | 按一条 RepoFix 任务逐层讲解 Loop、状态、工具、安全、恢复、上下文、评测，并以 Claude Code、DeepSeek Harness、nanobot 对照；新读者从这里开始。 |
| 学习文档 | [Harness 工程教学](./学习文档/Harness工程教学.md) | 源码阅读与专题教程；项目设计与面试问题合并在下方的统一文档。 |
| 代码 | [Python 标准库课程工程](./代码/agent-harness-course/) | FakeProvider、AgentRunner、事件、工具策略、进程内 Effect 缓存及 21 项测试；代码变化须同步更新测试和相关文档。 |
| 面经 · 项目设计 | [TraceForge：问题驱动设计与面试答案](./面经/TraceForge-问题驱动设计与面试答案.md) | 一份正文把 48 道题、资深工程师答案、TraceForge 的设计决策、代码差距与验收方法连在一起；来源与答案随公开实现更新。 |

仓库根目录只保留入口、维护约定和许可证。旧的课程工程 ZIP 与源码重复且已过期，因此不再入库；需要离线包时可从 GitHub 下载当前提交的源码。目录维护约定见 [AGENTS.md](./AGENTS.md)。

## 快速验证

在 `代码/agent-harness-course` 目录运行：

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

课程工程不需要 API Key。现有测试证明主循环、事件记录、示例路径拒绝策略、**同进程** Effect 结果复用和状态投影；不证明跨进程副作用去重、真实沙箱或 RepoFix 修复成功率。
