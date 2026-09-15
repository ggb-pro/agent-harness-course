# 学习文档阅读顺序

1. [从零理解 Agent Harness](./从零理解Agent-Harness.md)：新读者从一条 RepoFix 任务进入，十讲串起主循环、状态、工具、恢复、上下文、安全和评测；每讲配三种开源实现的观察点和动手题。
2. [Harness 工程教学](./Harness工程教学.md)：深入比较 Claude Code、DeepSeek Harness 与 nanobot 的架构、源码路径和扩展机制，适合作为专题参考。
3. [TraceForge：问题驱动设计与面试答案](../面经/TraceForge-问题驱动设计与面试答案.md)：用 48 道工程追问讲清项目设计，明确已实现的课程原型与尚待验证的工程目标。

学习时先运行[课程代码](../代码/agent-harness-course/README.md)，再用[统一文档里的问题](../面经/TraceForge-问题驱动设计与面试答案.md)检查能否说清真实失败窗口和验证证据。文档随 GitHub 源码变化更新，不能把外部项目未公开的内部机制当成事实。
