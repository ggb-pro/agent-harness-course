# 从零理解 Agent Harness：一条任务、三套实现、十个工程问题

> 更新于 2026-09-15。适合已经会调用大模型 API、希望理解 Agent 工程内核的开发者。本文是**学习主线**：先用一条 RepoFix 任务讲清因果关系，再分别观察 Claude Code、DeepSeek Harness（下称 DSH）和 nanobot 如何处理相同问题。现有的 [Harness 工程教学](./Harness工程教学.md) 提供更细的专题与源码阅读，[问题驱动的 TraceForge 设计与面试答案](../面经/TraceForge-问题驱动设计与面试答案.md) 是毕业项目规格；不要把设计目标当成课程代码已实现能力。

## 学习路线与最终能力

读完后应能画出一个 Agent Run 的状态机，解释模型输出为何不能直接执行，区分事件、Checkpoint、Trace 和 Memory，指出 Tool 成功后进程崩溃的重复副作用风险，并设计能证明改动没有破坏其他任务的评测。建议每讲先口述结论，再运行[课程工程](../代码/agent-harness-course/README.md)或阅读对应源码；题库里相关追问可用于自测。

本课程贯穿的例子：用户要求“修复某仓库中的边界条件错误，不能改配置文件，修完运行测试并解释原因”。一个正确成果不是一段“已修复”的文字，而是限定范围的补丁、测试退出码、变更解释和审计证据。这个例子逼迫我们逐步回答十个工程问题。

```text
用户任务与约束
    ↓
RunState ─→ ContextBuilder ─→ Provider
    ↑                             │ Action / Finish
    │                             ↓
Event Store ← ToolRuntime ← Policy / Approval
    │              │
    │         Effect Journal ─→ Sandbox / 外部系统
    ↓
Verifier ─→ 通过 / 继续修复 / 明确失败
```

## 第一讲：Harness 究竟解决了什么

模型能提出下一步，但不会替系统承担权限、状态和副作用的责任。最小 Agent Demo 常写成 `while response.tool_calls: execute(); ask_model_again()`；一旦进程中断、工具重复回调、模型要求读凭据、上下文过长或测试没有通过，这个循环没有可靠答案。Harness 是让概率性决策在确定性约束下运行的执行层：管理输入与预算、校验动作、执行工具、持久化事实、恢复和验收。Agent 可以把“是否需要进一步读文件”交给模型，不能把“是否有权读 `.env`”也交给模型。

从产品视角看 Claude Code，可学习权限、Hooks、Skills、Subagents 等公开的外围契约；其未公开的内部状态机不能靠猜测描述。[Claude Code 插件开发工具](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/README.md)展示了 Hook 等扩展面的公开形态。DSH 的[架构文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)把运行时拆成可组合服务与插件；nanobot 的[架构图](https://github.com/HKUDS/nanobot/blob/main/docs/architecture.md)则让一条消息到模型/工具循环的路径保持易读。三者规模和目的不同，不能按功能数量简单排名。

**动手**：在[课程 `runner.py`](../代码/agent-harness-course/src/traceforge_harness/runner.py) 找到“模型没有 ToolCall 就完成”的分支；说出它为何只能表示模型停止，而不是 RepoFix 任务成功。

## 第二讲：谁拥有 Loop，谁拥有状态

一次 Run 可分为 `CREATED → MODEL_PENDING → ACTION_PROPOSED → TOOL_PENDING → OBSERVED → VERIFYING → SUCCEEDED/FAILED`，另有 `WAITING_APPROVAL、CANCELLED、BUDGET_EXHAUSTED、NEEDS_RECONCILIATION` 等路径。RunState 至少包含目标和不可丢约束、仓库基线、当前阶段、待执行动作、预算、审批和版本号。模型消息只是给模型看的**派生视图**；它不能决定自己的预算已经重置，也不能改写系统记录的审批结果。状态转移以 revision 比较并提交，终态不能继续执行 Tool。

nanobot 明确分开 `AgentLoop`（面向渠道、会话和工作区）与 `AgentRunner`（面向 Provider 和 Tool），适合沿一次消息追源码。[nanobot 架构](https://github.com/HKUDS/nanobot/blob/main/docs/architecture.md)。DSH 的 Loop 由插件树中的默认驱动贡献，更适合研究能力如何替换。[DSH Core](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md)。两者都提醒我们：Loop 的所有权要明确，不能让 UI、Tool 和 Provider 各自偷偷推进状态。

**动手**：为课程 Runner 画出它**目前**真正具有的状态和事件，再用虚线画出设计稿的目标状态。不要把虚线画成已有代码。

## 第三讲：模型建议到 Tool 执行之间必须过哪些门

模型输出 `tool=apply_patch, args={path, patch}` 后，依次检查：完整可解析的调用、输入 Schema、Tool 是否在当前 Profile 可见、主体权限、真实工作区边界、风险级别与审批、预算、外部执行环境。每次拒绝都要写入事件并返回确定性原因。Schema 解决格式，不解决授权；Prompt 解决行为引导，不解决隔离。

Claude Code 的公开 Hook 例子可用于理解执行前/后的确定性检查，不能把 Hook 当成容器或操作系统权限。[Hook 开发参考](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md)。DSH 将受保护的 Tool Registry 和策略执行放在核心服务中，值得学习“Tool 实现”和“调用治理”分离。[DSH 架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)。课程工程当前只有 `DenyPathPolicy` 的路径段过滤；它不会解析符号链接，不能视为沙箱。[课程 `tools.py`](../代码/agent-harness-course/src/traceforge_harness/tools.py)

**动手**：列出 `read_file('.env')`、`read_file('src/../.env')`、符号链接指向仓库外部、审批后改参四个案例应分别在哪一层被拒绝。

## 第四讲：事件日志为什么不等于普通日志

普通日志帮助诊断；Event Log 是运行事实的有序记录；Trace 展示跨模型、Tool、Agent 的调用因果和耗时；Checkpoint 是从事实生成的恢复加速。若一次模型请求实际看到了某条系统提示、Tool Schema 或压缩摘要，却没有记录它们的版本与来源，事后就无法解释它为何做出那个动作。DSH 明确强调“模型可见的内容可从 Session Log 重建”，是强约束而不只是多打日志。[DSH Session](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)。

设计事件时先问：哪些事实必须在重启后仍成立？`tool.requested`、审批决定、预算扣减、外部执行结果属于这个集合。每个 Run 的 sequence 单调、schema 可迁移、写入失败显式报错。课程 [JSONL Event Store](../代码/agent-harness-course/src/traceforge_harness/events.py)可演示追加与投影，但它无事务、并发 writer 保护和落盘完整性保证，不能直接承诺跨进程可靠恢复。

**动手**：用 [Projection](../代码/agent-harness-course/src/traceforge_harness/projections.py) 从事件重建工具次数；再思考“重建统计”与“安全恢复未完成 Tool”为何不是同一件事。

## 第五讲：最难的失败窗口——副作用已发生，结果未记录

设想 `apply_patch` 已写文件，进程在 Journal 写 `completed` 前崩溃。重启后若只看到 `started`，直接重试可能再次写文件；只凭超时也不能判断外部动作没发生。目标协议是：先持久化意图与稳定 idempotency key，再执行；成功时保存 receipt；若状态未知，查询外部结果或比较工作区哈希。无从确认的不可逆动作停在 `NEEDS_RECONCILIATION`。跨本地数据库和外部系统，不能笼统声称“恰好一次”。

当前课程 `EffectJournal` 是内存字典，仅能在同一进程中复用完成结果；进程崩溃后丢失。这是读源码时必须发现的边界。[课程 `tools.py`](../代码/agent-harness-course/src/traceforge_harness/tools.py)。面试时若把它说成“已解决崩溃恢复”，追问一个断电点就会露出问题。

**动手**：画出意图提交、外部执行、结果提交三段时间线，在每个边界注入崩溃，写下恢复时的唯一安全动作。

## 第六讲：Context 不只是“把历史塞进窗口”

模型输入通常来自系统规则、用户当前任务、历史消息、仓库文件、Tool 结果、摘要和技能。每项应带来源、可信度、版本与预算估计。不可丢的用户约束（如“不得改配置”）、审批、待办与证据引用独立存入 protected state；压缩只处理可回取的旧观察与重复推理。压缩后对路径、实体、数字、否定词和授权做差异检查；如果必保留内容本身超预算，应停止并说明，而不是静默删除。

nanobot 把 Session、Workspace、Memory 与 Context 构造放在实际消息链路中，便于学习长期运行的输入来源。[nanobot 架构](https://github.com/HKUDS/nanobot/blob/main/docs/architecture.md)。课程 [ContextBuilder](../代码/agent-harness-course/src/traceforge_harness/context.py)目前独立于 Runner，且 required 条目可超出预算返回；它是教学样例，不是已集成的保真压缩器。

**动手**：为用户约束“只能修改 `src/`，不得新增依赖，先运行已有测试”设计 protected state，并给出一次压缩前后 diff 示例。

## 第七讲：权限、审批和沙箱是三种不同机制

权限回答“主体能做什么”；审批回答“这一个具体高风险动作是否获得许可”；沙箱回答“即使代码出错，进程真正能触及什么”。审批需绑定动作哈希、状态版本、资源、策略版本和有效期；执行前重验，参数一变就重批。沙箱需限制真实路径、挂载、进程、网络和资源，启动失败不能回退宿主机。仓库中的 README、网页或 Tool 输出都是低信任数据，不得通过提示注入提升权限。

OpenAI Agents SDK 的[人工审批文档](https://github.com/openai/openai-agents-python/blob/main/docs/human_in_the_loop.md)展示中断、保存 RunState、决定和恢复的产品语义，可作为比较对象；MCP 的[安全实践](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/docs/2026-07-28/tutorials/security/security_best_practices.mdx)强调 token audience 和禁止透传。MCP 让工具跨进程接入，并不替 Harness 解决授权和沙箱。

**动手**：假设审批的是 `apply_patch` 到 `src/a.py`，恢复时仓库 SHA 或补丁文本改变，写出拒绝条件与事件。

## 第八讲：任务完成如何被验证

RepoFix 的 Verifier 应检查允许路径、diff 是否与用户目标相关、目标测试与相关回归是否通过、结果是否有真实证据。测试不可执行就输出 `UNVERIFIED`；模型说“我修好了”不代替文件与退出码。评测集应固定仓库 SHA、问题、可修改范围、判定脚本和故障类型；开发集与留出集分开。先跑 FakeProvider 的结构回归，再跑真实模型任务评测。质量、安全、P95 和成本一起看，不能只报成功率。[OpenAI Agents SDK Tracing](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)可参考跨调用归因方式。

**动手**：为例子写一个验收表：补丁仅改 `src/`、测试退出码为 0、配置文件 hash 不变、回答引用实际 diff。把“模型自称通过但测试失败”放进 Bad Case 回归。

## 第九讲：三个项目如何回答同一道题

下表是公开契约/仓库实现能支持的比较，不推断 Claude Code 未公开的内核。DSH 处于快速迭代的开发预览，具体接口需要按当前 GitHub 版本复核。[DSH 仓库](https://github.com/deepseek-ai/deepseek-harness)

| 问题 | Claude Code | DeepSeek Harness | nanobot | TraceForge 应学的取舍 |
| --- | --- | --- | --- | --- |
| 扩展能力 | 公开 Hooks、Skills、Subagents 与插件契约；看产品边界 | Cordis 插件树、服务与 Capability Seam；看可替换性 | 可读主循环外接 Provider、Channel、Tool；看端到端路径 | 先有小而显式的接口，不急于全插件化 |
| 状态与上下文 | 只分析公开行为，不猜内部事实源 | Session Log 与模型可见输入的可重建约束 | Session/Workspace/Memory 贯穿消息流 | 把 RunState、事件和模型视图分开 |
| 工具安全 | 学权限交互与执行前后 Hook 契约 | 学 Tool Registry 与执行策略分离 | 读工具实现和工作区边界如何组合 | 权限、审批、沙箱各有独立验收 |
| 目标用户 | 高完成度编码 Agent 产品 | Harness 开发者与运行时组合 | 多渠道、自托管个人 Agent | 学习型可审计 RepoFix，不追逐功能数 |

比较方法是给三者同一个变更请求，例如“禁止读取 `.env`，且每次拒绝可审计”，然后定位入口、事实状态、策略检查、物理隔离和测试；不要摘录一堆功能清单就称为架构分析。

## 第十讲：从课程原型走到作品集项目

建议按证据逐级推进，而非一口气实现完整平台。阶段 A：运行现有 29 项测试，读懂 FakeProvider、Runner、Event Store 和 ToolRuntime；其中“模型自称成功但无验收契约”已新增 `unverified` 回归样本。阶段 B：已有可重建 RunState、SQLite 事件 revision、模型/工具次数与截止时间上限、显式 CompletionContract 和精确重复观察检测；仍需接入 Context、token/费用预算、更稳健的进展检测及 RepoFix Verifier。阶段 C：持久化 Effect 意图、故障注入和对账；证明重启后不盲重试。阶段 D：在隔离 worktree 与真正的沙箱中实现 RepoFix，并建立固定任务集与简单基线。阶段 E：只有单 Agent 数据显示收益时才引入 Explore Subagent、MCP 或远程执行。里程碑与门禁见[统一文档](../面经/TraceForge-问题驱动设计与面试答案.md)。

毕业验收不是“README 写得完整”，而是别人能在固定版本上复现：同一任务输入、代码版本、测试命令、事件轨迹、实际补丁、失败样例和指标。当前仓库只实现了课程原型，尚未达到这些毕业条件。[统一文档](../面经/TraceForge-问题驱动设计与面试答案.md)中的每一道项目追问都应能指向代码或可重复实验。

## 自测：能说清这六句话吗

1. Agent 的模型可以建议动作，但每个动作必须经 Harness 验证。
2. 对话摘要不是权威 RunState；Trace 也不是 Event Store。
3. HTTP/模型返回成功，不代表工具执行或用户任务成功。
4. 写操作结果未知时先对账，不盲重试。
5. Prompt、审批、沙箱分别解决不同问题。
6. “已实现”必须有代码和测试；“设计目标”必须标明尚未验证。

无法解释其中任一句时，回到对应课程讲次并运行课程代码，再读 [Harness 工程教学](./Harness工程教学.md)的专题章节。
