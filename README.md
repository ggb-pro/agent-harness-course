# Agent Harness 学习与实战

本仓库把 Agent Harness 的学习材料与可运行代码整理为两部分，适合系统学习、源码阅读和作品集实践。

## 学习

- [`Harness工程教学.md`](./学习/Harness工程教学.md)：导读 + 20 章工程教程，对比 Claude Code、DeepSeek Harness 与 nanobot，并给出六周学习路线。
- [`TraceForge-Agent-Harness-项目设计文档.md`](./学习/TraceForge-Agent-Harness-项目设计文档.md)：v0.2 项目设计，覆盖事件溯源、权限策略、Effect Journal、上下文治理、恢复与评测。

## 代码

- [`agent-harness-course/`](./代码/agent-harness-course/)：可直接阅读和运行的 Python 标准库示例工程。
- [`agent-harness-course.zip`](./代码/agent-harness-course.zip)：同一工程的下载包。

配套工程不调用真实模型，不需要 API Key。运行 21 项自动化测试即可验证主循环、事件记录、工具策略、幂等副作用和状态投影。

```powershell
cd 代码/agent-harness-course
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

建议先读教程的前八章建立架构视角，再运行代码，最后按 TraceForge 设计文档的十周路线逐步扩展。


