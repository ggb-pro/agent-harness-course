# TraceForge Agent Harness 项目设计文档

> 版本：v0.3（基于仓库 `main` 的 v0.2 原文增量修订）
> 状态：目标架构与实施契约；仓库代码仍是课程原型
> 更新日期：2026-09-15
> 配套教程：[`Harness工程教学.md`](./Harness工程教学.md)  
> 配套实现：[`代码/agent-harness-course`](../代码/agent-harness-course/README.md)
> 面试题与参考答案：[`Agent工程面经与答案.md`](./Agent工程面经与答案.md)

**版本事实**：本版以 GitHub `ggb-pro/agent-harness-course` 的 `main@5a2a51d` 中完整 v0.2 文档为底稿，保留其 22 节及原有设计取舍。下文凡使用“应”“计划”“验收”均指未来实现，不代表当前课程代码已具备。旧版文档中若把 JSONL、Effect Journal 和恢复连在一起描述，应按本版第 11 节的持久化边界理解。

| 能力 | 当前课程代码证据 | 本文目标状态 |
| --- | --- | --- |
| 模型/工具循环与终态 | `runner.py`，21 项测试通过 | 加入预算、取消、循环检测、确定性验收 |
| 事件 | `events.py` 有 JSONL 追加和投影 | 追加原子性、完整性校验、版本迁移与恢复 |
| Effect Journal | `tools.py` 的进程内字典，仅能在同一进程复用成功结果 | 持久化意图、对账与 `uncertain` 状态；不承诺全局恰好一次 |
| 路径策略 | `DenyPathPolicy` 按字符串路径段过滤 | 解析真实路径、符号链接及根目录边界，配合沙箱 |
| Context Builder | `context.py` 是独立示例，Runner 尚未调用；必保留项可超过预算 | 与 Runner 集成，受保护状态不可压缩且超预算时明确停止 |
| RepoFix、审批、沙箱、真实模型评测 | 尚无实现 | 按后文里程碑实现并以独立验收门禁证明 |

## 1. 项目摘要

TraceForge 是一套面向工程实践的 Agent Harness：它不把重点放在“再封装一次模型 API”，而是解决 Agent 长时间运行时最容易失控的部分——状态、上下文、权限、副作用、恢复和评测。

第一阶段提供通用 Harness Core 与 RepoFix Profile。前者负责可审计的运行时，后者提供一个可演示的代码仓库修复场景。项目的核心主张是：

> 每个重要决定都能解释，每个外部副作用都能追踪，每次失败都能安全恢复，每个改动都能通过固定评测验证。

## 2. 背景与问题

常见 Agent Demo 通常由“发送消息—解析工具调用—执行—回传结果”的循环组成。它能展示能力，却没有回答生产系统必须回答的问题：

- 进程崩溃后从哪里继续？
- 同一个写操作会不会被重复执行？
- Prompt、记忆和工具输出分别来自哪里？
- 哪条策略允许或拒绝了某个工具？
- 能否在不再次调用外部系统的情况下还原一次运行？
- 修改 Harness 后，怎样证明成功率没有下降？

TraceForge 把这些问题作为一等设计目标，而不是上线前追加的外围功能。

## 3. 目标与非目标

### 3.1 目标

1. 提供小而清晰、可测试的 Agent 主循环；
2. 用追加式事件记录运行事实，并从事件生成状态投影；
3. 在工具实现之外统一执行策略与审批；
4. 用 Effect Journal 管理幂等、恢复和对账；
5. 对上下文来源、预算、压缩和污染风险进行治理；
6. 使用 FakeProvider、Golden Trace 和故障注入进行确定性评测；
7. 允许通过 Profile 组合面向特定领域的工具、策略和 Prompt。

### 3.2 非目标

- v0.3 不做通用多 Agent 编排平台；
- 不复刻 Claude Code、DeepSeek Harness 或 nanobot 的全部功能；
- 不把 Prompt 当作安全边界；
- 不以支持最多模型或最多工具为首要指标；
- 不承诺跨供应商的 token 计数完全一致；
- 不在第一阶段引入 Docker、远程沙箱或 MCP 作为必需依赖。

## 4. 设计原则

### 4.1 事件是事实，状态是投影

关键动作先形成事件，再更新可查询状态。任何仪表盘、报告或恢复点都应能从事件重建。

### 4.2 权限单调收紧

Profile、用户审批和子任务可以缩小权限，但不能静默扩大权限。真正的隔离由操作系统、容器或远程沙箱实现，Prompt 只负责行为引导。

### 4.3 副作用显式化

文件写入、命令执行、网络请求等动作必须具有稳定的 `effect_id`，并在 Effect Journal 中经历明确状态转换。

### 4.4 确定性内核优先

模型不确定，Harness 核心应尽可能确定。Provider、时钟、标识生成器和工具运行时均可替换，以便单元测试和重放。

### 4.5 渐进复杂度

先完成单 Agent、单进程、JSONL 教学链路；进入跨进程恢复里程碑时使用能原子提交事件和 Effect 意图的持久化存储。RepoFix 接入真实命令执行前必须建立沙箱，然后才考虑 MCP 和子 Agent。

## 5. 设计来源与 TraceForge 取舍

本节只标注可明确对应的设计启发。通用软件工程做法不会被包装成某个项目的独有思想。

| TraceForge 设计 | 主要参考 | 采用方式 | TraceForge 取舍 |
| --- | --- | --- | --- |
| 稳定的外围扩展契约、Hooks、Skills、Subagents | Claude Code | 学习产品级能力边界与人机协作入口 | 不假设其未公开内部实现；先提供显式 Python 接口 |
| 插件生命周期、事件溯源、Capability Seam、工具策略流水线 | DeepSeek Harness | 将服务、事件和策略作为可组合能力 | v0.3 不复制完整插件树，保留小型 Profile 组合层 |
| 可读主循环、Provider/Tool/Channel 分离、Workspace | nanobot | 保持端到端调用链短且可读 | 额外强化事件、策略和副作用恢复 |
| Effect Journal、幂等键、对账与补偿 | Outbox/事务日志等通用可靠性模式 | 自主组合为副作用协议 | 不归因于上述三个 Agent 项目 |
| Golden Trace、故障注入、固定评测集 | 测试与分布式系统工程实践 | 用于 Harness 回归 | 先测结构不变量，再测真实模型表现 |

## 6. 用户与核心场景

### 6.1 目标用户

- 希望理解 Agent 基础设施的开发者；
- 需要把内部 Agent 从 Demo 推向稳定服务的团队；
- 希望在作品集中展示运行时工程能力的求职者。

### 6.2 RepoFix 场景

用户提交一个仓库问题，Agent 读取受限工作区、检索代码、提出修改、运行测试并生成结果报告。所有文件访问经过路径策略；所有写操作进入 Effect Journal；任何模型或工具失败都进入事件日志。

### 6.3 审计场景

开发者输入 `run_id`，查看完整时间线、Prompt 来源、模型轮次、工具参数、策略决定、输出摘要、错误与最终状态。

### 6.4 恢复场景

进程在工具执行后崩溃。重启后系统读取事件与 Effect Journal：已完成的幂等操作直接复用结果；不确定操作进入核对；安全的未执行步骤从最近检查点继续。

## 7. 总体架构

```text
CLI / API / UI
      |
      v
Profile (RepoFix)
      |
      v
AgentRunner ---- ContextBuilder ---- Prompt Sources
   |    |
   |    +---- Provider (Fake / real model)
   |
   +---- ToolRuntime ---- Policy Pipeline ---- Tool Registry
   |          |
   |          +---- Effect Journal ---- External Systems
   |
   +---- Event Store ---- Projectors ---- Timeline / Metrics / Recovery
```

`AgentRunner` 只负责状态机和依赖协调；Provider 不直接执行工具；Tool 不直接决定权限；UI 不拥有事实状态。

## 8. 模块设计

### 8.1 AgentRunner

目标状态集合：`created -> ready -> model_pending -> action_proposed -> waiting_approval | tool_pending -> observed -> verifying -> completed | failed | cancelled | budget_exhausted | needs_reconciliation`。每次迁移携带 `expected_revision`；终态不可再次调用 Tool。课程代码目前只实现简化的 `started/completed/failed` 事件，不能将目标状态机当作现有功能。

一次标准循环：

1. 构造带来源信息的上下文；
2. 追加 `model.requested`；
3. 调用 Provider，追加 `model.responded`；
4. 如果是最终回答，先调用 Profile 的确定性 `Verifier`；通过才追加 `run.completed`，否则追加可定位的失败/继续事件；
5. 如果含工具调用，交给 ToolRuntime；
6. 将工具结果写回上下文，进入下一轮；
7. 检查轮次、总时间、每次请求与总 token/费用预算、用户取消及无进展阈值；任何上限触发均产生明确终态。

动作含 `call_id, tool_name, canonical_args, expected_state_delta`。连续相同动作无新证据、`A→B→A` 和连续三轮无可验证进展会触发停止或受控重规划；模型不能自行清空失败记录和预算。`Finish` 必须带证据引用；对 RepoFix 而言“我已修好”不构成完成证明。模型流式输出不完整时不得执行半个 ToolCall。

Runner 不能吞掉异常。所有异常必须被分类并写入 `run.failed`，但敏感信息在写入前要脱敏。

### 8.2 Provider

```python
class Provider(Protocol):
    def complete(self, messages: list[Message]) -> AssistantResponse: ...
```

`AssistantResponse` 只能是最终文本或零到多个结构化 ToolCall。Provider 适配器负责供应商格式转换、超时、重试元数据和用量采集，不负责业务策略。

`FakeProvider` 接收预先编排的响应序列，是单元测试和 Golden Trace 的默认 Provider。

### 8.3 Event Store

课程原型的事件最小结构：

```json
{
  "run_id": "run-123",
  "sequence": 4,
  "type": "tool.completed",
  "timestamp": "2026-09-08T10:00:00Z",
  "payload": {"tool": "read_file", "effect_id": "..."}
}
```

约束：

- 同一 `run_id` 的 `sequence` 严格递增；
- 已写事件不可原地修改；
- Payload 经过版本化与脱敏；
- JSONL 适合本地版本，生产可替换为支持并发控制的数据库；
- 事件 schema 变更必须提供 upcaster 或兼容读取逻辑。

目标事件信封新增 `event_id, revision, causation_id, correlation_id, schema_version, payload_hash`。单进程 JSONL 也必须约束一个 writer、写后 flush/fsync 与尾部半行识别；下一阶段优先使用 SQLite 事务将事件、run revision、Effect Journal 意图一起提交。恢复读取必须检查连续序号、校验和、schema 版本与快照边界；损坏时 fail closed 并给出修复报告。`replay --offline` 只重建状态/策略结果，不重新执行模型或外部副作用；真实模型再运行是另一种评测，不保证字节级复现。

### 8.4 Projection

Projection 从事件生成：运行摘要、当前状态、工具统计、错误列表和审计时间线。Projection 可删除并重建，不反向修改事件。

### 8.5 Tool Registry

目标工具定义包含名称与版本、正反用途、输入/输出 Schema、风险等级、读写性质、权限、超时、输出上限、幂等与对账能力。注册时拒绝重名；调用时拒绝未知参数，并在代码中重新验证类型、范围和业务前置条件；返回值需结构化、可序列化，并携带状态、证据引用、截断标记及可回取句柄。课程原型 `ToolRegistry` 目前只有名称与 handler，不具备这些校验，不能以“已有 Tool Registry”替代目标契约。

### 8.6 Policy Pipeline

策略输入包含运行主体、Profile、工具、参数、工作区和既有授权。输出只能是：

- `allow`：立即执行；
- `deny`：记录理由并停止该调用；
- `require_approval`：挂起运行并等待一次性批准。

目标策略包括敏感路径拒绝、工作区边界、命令 allowlist、网络域名限制和写操作审批；课程代码目前仅实现 `DenyPathPolicy` 的路径段字符串过滤。授权能力取用户授权、Profile、Tool 和子任务权限的交集；低信任的仓库内容、Tool 输出、Skill 不能提升权限。审批记录绑定 `run revision + call_id + 规范化动作哈希 + 资源 + policy_version + 过期时间`，恢复后执行前再次校验；参数或工作区发生变化必须重新审批。权限拒绝不可由模型自动重试绕过。[OpenAI Agents SDK 的审批与恢复](https://github.com/openai/openai-agents-python/blob/main/docs/human_in_the_loop.md)

### 8.7 Effect Journal

记录结构：`effect_id`、工具名、规范化参数哈希、状态、尝试次数、结果引用、错误和更新时间。

状态机：

```text
planned -> started -> completed
                  \-> failed -> started
                  \-> uncertain -> reconciled
```

`effect_id` 由 `run_id + tool_call_id + normalized_args` 派生。同一 ID 与不同参数同时出现属于完整性错误。当前 `EffectJournal` 是进程内字典，**无法证明进程崩溃后不重复执行**。目标实现须先持久化意图，再执行 Tool，再持久化 receipt；若外部动作成功但结果未落盘，重启时进入 `uncertain`，通过外部查询或幂等键对账。无法确认且不可逆的操作转 `needs_reconciliation`，不得盲重试。不能把本地事件提交与外部系统副作用说成原子事务或笼统“恰好一次”。

### 8.8 Context Builder

每个 Context Item 包含 `source`、`content`、`priority`、`trust`、`created_at` 和 `token_estimate`。构建顺序固定，预算不足时按规则裁剪，不能删除安全策略和当前用户目标。

工具返回的不可信文本要明确标注，防止检索文档中的指令被提升为系统规则。摘要保留来源 ID，便于回到原始事件。用户目标、否定约束、授权范围、待审批动作、预算与未完成步骤构成独立 `protected_state`，不能只存在自由文本摘要；压缩前后比较结构化约束，失败则回滚。若必保留内容本身超预算，目标 Runner 必须拒绝下一次模型调用并输出原因，而不是像课程 `ContextBuilder` 示例那样返回超预算列表。Prompt Cache 仅缓存稳定前缀，按模型、模板、Tool Schema 与权限域隔离。

### 8.9 Profile

Profile 是一组显式配置：Prompt Sources、工具集合、策略集合、上下文预算、最大轮次和评测集。v0.3 不允许 Profile 动态修改内核服务，避免过早进入复杂插件生命周期。

### 8.10 Explore Subagent

RepoFix 可选地使用只读 Explore Subagent：它有独立上下文、固定轮次和更窄工具权限，只返回结构化发现及证据位置。主 Agent 对最终决定负责。第一里程碑不启用此模块。

## 9. 数据与目录结构

```text
traceforge/
├── core/               # runner、事件、投影、上下文
├── providers/          # FakeProvider 与真实模型适配
├── tools/              # registry、runtime、内置工具
├── policies/           # 路径、命令、网络、审批
├── effects/            # journal、幂等、reconcile
├── profiles/repofix/   # RepoFix 配置与 Prompt
├── evals/              # 任务集、Golden Trace、评分
├── tests/              # 单元、场景与故障测试
└── runs/               # 本地 JSONL 与派生投影（不提交）
```

配套课程代码采用更小的目录，用于先验证上述核心概念。

## 10. 安全模型

威胁包括 Prompt Injection、敏感文件读取、命令注入、路径逃逸、凭据泄漏、未授权网络访问和子任务权限膨胀。

安全边界分层：

1. 上下文层标注可信度，避免指令优先级混淆；
2. Policy Pipeline 对每次工具调用做确定性判断；
3. Tool 实现使用结构化参数，不拼接未经处理的命令；
4. Sandbox 限制文件、进程与网络的真实能力；
5. Event Store 脱敏且设置保留期限；
6. Subagent 只获得完成任务所需的最小权限。

任何 `allow` 决定都不能突破 Sandbox 的物理限制。

RepoFix 的执行根目录是任务专用、基于固定 commit SHA 的隔离 worktree。每次文件访问应解析真实路径并拒绝符号链接跳出根目录；`.git`、凭据和宿主机敏感目录不挂载。命令执行应使用参数数组、进程组清理、CPU/内存/时间限制及默认禁网策略；沙箱启动失败时 fail closed，不回退到宿主机。即使 Tool 参数通过 Schema，执行前仍重新检查实际路径和权限，以处理 TOCTOU。MCP 留作后续适配器：只连接可信服务器，按服务器与 Tool 身份授权；远程 token 需验证受众且不得透传给下游。[MCP 安全实践](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/docs/2026-07-28/tutorials/security/security_best_practices.mdx)

## 11. 可靠性与恢复

失败分类：模型瞬态错误、模型永久错误、策略拒绝、等待审批、工具失败、超时、进程崩溃和状态完整性错误。

恢复原则：

- 只对明确可重试的错误做有限指数退避；
- 重试信息写入事件，不能隐藏成本；
- 副作用重试前查询 Journal；
- `uncertain` 不自动假定失败，要调用 reconcile；
- 不可恢复错误进入明确终态并输出可操作报告。

目标恢复算法：加载最后有效 Snapshot 和之后的事件，检查序号及哈希；按 run revision 恢复预算、审批与待执行动作；逐条检查未终结 Effect。`planned` 且确认未执行可安全继续；`started` 或结果未知先 `reconcile`；`completed` 只复用 receipt。对外部不可查询的写动作明确要求人工处理。取消与 Tool 完成竞态按事件提交顺序裁决；取消传播至 Provider、进程组与子任务，但不能假定外部副作用被撤销。

故障注入矩阵至少覆盖：意图落盘前/后、外部执行前/后、结果落盘前/后、审批挂起/恢复、事件尾部截断、重复回调、取消与完成竞态。每次检查事件连续性、最终状态、工作区文件哈希、预算不重置、无重复写入。当前 21 项课程测试不覆盖这些跨进程情形。

## 12. 可观测性

每次运行至少提供：耗时、模型轮次、工具调用数、拒绝次数、审批等待、token/费用（若 Provider 提供）、重试次数、完成状态和失败类别。

日志、指标与 Trace 通过 `run_id` 关联。结构化事件是审计依据，普通日志只服务运维诊断。

补充 `step_id, tool_call_id, effect_id, trace_id/span_id`，每个模型调用记录模型/Prompt/Tool Schema/策略/仓库版本、输入输出 token 与费用（未知值明确记 `unknown`），每个工具记录排队、执行、对账和验证耗时。原始 Prompt 与 Tool 输出可能含凭据，默认保存哈希和经过脱敏的可控摘要；需要回取的原文使用受权限保护的制品存储与保留期限。Trace 用于性能和因果分析，Event Store 才是状态恢复事实源。[OpenAI Agents SDK Tracing](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)

## 13. 测试与评测

### 13.1 自动化测试

- 事件追加、序号与持久化；
- Provider 脚本耗尽与响应顺序；
- 工具注册、校验、拒绝和异常；
- Effect Journal 的缓存、失败与参数冲突；
- Context 预算和必保留项；
- Runner 完成、工具循环、轮次上限与错误事件；
- Projection 的状态与计数。

### 13.2 Golden Trace

固定 FakeProvider、固定时钟、固定 ID，比较规范化事件序列。时间戳、耗时等易变字段在断言前剔除。

### 13.3 真实模型评测

RepoFix 初始评测集计划包含至少 20 个小型仓库任务，并分为基础修复、模糊需求、工具/模型故障、安全攻击、恢复与竞态五类；现在仓库中**尚无 RepoFix 评测集**。每个样本固定仓库 SHA、允许修改路径、任务描述、目标测试和判定脚本，开发集与留出集分离。指标包括确定性验收成功率、约束违反率、测试通过率、重复副作用率、恢复成功率、工具选择与参数一次通过率、P50/P95/P99、token/费用和误拒绝率。真实模型固定模型版本、采样参数与环境，多次运行报告方差；不能以 LLM 自评代替文件/测试/策略验证。

每次 Harness 变更与最小 Workflow 和现成 SDK 方案做同题配对基线；先离线回归，再只读 Shadow，真正上线后才有小流量 Canary。安全违规和重复副作用是阻断项；质量、延迟和费用联动判断，不能只报成功案例或虚构提升。Bad Case 必须留下输入、版本、Trace、根因、修复和新增回归样本。模型回放与事件离线重建要分别命名，避免误导。

## 14. CLI 草案

```text
traceforge run --profile repofix --task issue.md
traceforge inspect RUN_ID
traceforge replay RUN_ID --offline
traceforge resume RUN_ID
traceforge eval --suite repofix-v1
traceforge effects reconcile RUN_ID
```

## 15. API 草案

- `POST /runs`：创建运行；
- `GET /runs/{id}`：读取状态投影；
- `GET /runs/{id}/events`：分页读取事件；
- `POST /runs/{id}/approvals/{call_id}`：批准或拒绝；
- `POST /runs/{id}/resume`：恢复；
- `POST /evals`：启动固定评测。

所有写接口接受幂等键。

## 16. 里程碑与十周路线

| 周 | 交付物 | 验收标准 |
| --- | --- | --- |
| 1 | 审计课程原型、冻结 Golden Trace；补 RunState/revision | 现有 21 项测试继续通过，明确状态转移与终态 |
| 2 | 事件完整性、预算账本、取消与无进展检测 | 半行/重复序号被拒绝，预算不因重启重置 |
| 3 | Tool Manifest、结构化错误与真实路径策略 | 参数/路径/权限在副作用前被拒绝 |
| 4 | 持久化 Effect Journal 与意图先写 | 进程重启后可识别已完成与不确定动作 |
| 5 | reconcile 与崩溃故障注入 | 外部成功但本地未记录时不盲重试 |
| 6 | protected state、Context 集成与压缩保真 | 必保留项不丢；超预算明确停机 |
| 7 | RepoFix 隔离 worktree、命令沙箱与确定性 Verifier | 读—改—测闭环，越界与虚假完成被拒绝；沙箱失败不回退宿主机 |
| 8 | 分层任务集与配对基线 | 产出可复现分桶报告，不只列成功样例 |
| 9 | 审批挂起/恢复、只读 Explore 子任务 | 审批绑定原动作，子任务权限不扩张 |
| 10 | CLI、ADR、演示与安全复核 | 新用户按 README 运行，失败路径有证据包 |

## 17. 前 72 小时实施计划

### 第一天

定义 Event、AssistantResponse、ToolCall 和 RunState；实现 FakeProvider；完成无工具的最小 Runner；为事件顺序写测试。

### 第二天

加入 Tool Registry、拒绝策略与 JSONL Event Store；跑通一次 FakeProvider 发起工具调用、工具返回、模型结束的完整路径。

### 第三天

冻结第一条 Golden Trace；实现最小 Effect Journal；在**进程内**验证重复调用复用结果。跨进程“副作用完成后、事件写入前”的恢复只能在持久化 Journal 与外部对账协议完成后验收，不能用当前字典实现声称已解决。

这 72 小时内不接真实模型、不上 Docker、不接 MCP、不做多 Agent。目标是先证明内核可测试、可追踪；跨进程恢复属于后续里程碑。

## 18. ADR 清单

- ADR-001：事件日志作为运行事实源；
- ADR-002：Provider 与 Runner 分离；
- ADR-003：Policy 与 Tool 分离；
- ADR-004：副作用必须通过 Effect Journal；
- ADR-005：Profile 采用显式组合而非动态插件树；
- ADR-006：上下文条目保存来源与可信度；
- ADR-007：第一阶段使用 JSONL 与单进程写入；
- ADR-008：多 Agent 仅在评测证明收益后引入。
- ADR-009：本地事件与外部副作用不承诺原子提交，未知结果通过对账处理；
- ADR-010：RepoFix 成功由确定性 Verifier 判定；
- ADR-011：审批绑定状态版本与规范化动作，恢复后重新校验；
- ADR-012：课程 Python 原型先演进，不在无基线时重写为另一语言。

每份 ADR 记录背景、决定、替代方案、后果和撤销条件。

## 19. 验收标准

课程原型的已验证基线是 21 项自动化测试通过；下面是 **v0.3 目标实现** 进入下一阶段的验收条件，不能与当前代码能力混淆：

- 从空环境按 README 可运行，核心测试无需 API Key；
- 一次工具循环产生完整且有序的事件；
- 对相同 `effect_id` 的进程内重复调用复用结果；跨进程安全性须另由持久化与对账证明；
- 敏感路径访问在工具执行前被拒绝；
- 可从 JSONL 重建运行状态与工具统计；
- Provider 或工具故障会产生明确失败事件；
- Golden Trace 不依赖真实时间和随机 ID；
- 教程、设计文档、示例代码三者术语一致。
- 进程在每个副作用提交边界崩溃后，恢复结果可区分未执行、已完成和未知，未知动作不盲重试；
- 审批恢复后动作参数、状态版本或权限变化会拒绝执行；
- 必保留约束超出上下文预算时明确停止，压缩结果不能改变约束；
- RepoFix 完成需通过目标测试、相关回归、允许路径与差异检查；
- 评测集、基线、样本版本和失败样例均可复现，安全与重复副作用指标零容忍。

## 20. 后续演进

第一阶段稳定后再评估：SQLite/PostgreSQL Event Store、真实容器或远程沙箱、MCP Capability Adapter、长期 Memory、KnowledgeAudit Profile、并发运行、分布式 Worker 和 Web 时间线。

每项演进都需回答三个问题：它解决了哪个可复现问题？引入了什么新的失败模式？用哪组评测证明收益大于复杂度？

## 21. 作品集表达

以下是**完成目标实现且有可复现证据后**才可使用的简历表述草案：

> 设计并实现可审计、可恢复的 Agent Harness。以追加式事件日志统一运行事实，通过策略流水线隔离工具权限，使用 Effect Journal 解决副作用幂等与崩溃恢复，并以 FakeProvider、Golden Trace 和故障注入建立确定性回归测试。

在当前只有课程原型的阶段，应如实写成“独立实现 Python 标准库 Agent Harness 教学原型，覆盖模型/工具循环、JSONL 事件、路径拒绝策略及进程内 Effect 缓存，并通过 21 项测试”；不能声称已经具备跨进程恢复、沙箱或 RepoFix 评测。最终填写真实样本量、基线、P95 和失败案例，不编造收益。

## 22. 结论

TraceForge 的价值不在于让 Agent 看起来更聪明，而在于让系统行为更可控。当事件、权限、副作用、上下文和评测都成为明确协议后，模型可以替换，工具可以增长，运行仍然能够解释与恢复。这也是项目从课程示例走向工程平台的主线。

## 23. 用 48 道面经题反向审查后的决策记录

完整问题与参考答案见[Agent 工程面经](./Agent工程面经与答案.md)。下表只列对架构造成实质改动的追问，并明确可拿什么验证，避免“文档回答得上，但代码无法证明”。

| 题号与压力测试 | v0.2/课程代码暴露的缺口 | v0.3 决策 | 必须交付的证据 |
| --- | --- | --- | --- |
| Q02、Q08、Q44：模型说完成就算成功？ | Runner 无 ToolCall 即结束 | RepoFix 引入确定性 Verifier 和 `UNVERIFIED` | 虚假 Finish 被拒测试；补丁和测试证据包 |
| Q04、Q32：Loop/费用失控？ | 只有 `max_turns` | 持久化预算、deadline、取消和无进展指纹 | 重启不重置预算、震荡终止测试 |
| Q09–Q11：压缩丢约束/超预算？ | ContextBuilder 独立且 required 可超预算 | protected state + Runner 集成 + 约束 diff，无法保真就停止 | 否定约束、路径、数字保留测试 |
| Q12、Q17–Q19：Tool 选对却参数越权？ | Registry 仅名称与 handler | Tool Manifest、Schema、权限和结构化错误 | 错参、越权、错误分类表与回归样本 |
| Q20–Q23：审批和沙箱是假边界？ | 仅路径段过滤，无暂停与沙箱 | 真实路径与隔离 worktree；审批绑定动作和版本；MCP 后置 | 符号链接、TOCTOU、改参后审批失效测试 |
| Q25–Q29：重放与恢复是否可靠？ | JSONL 无写入完整性保证，Journal 是内存字典 | 先写意图、持久化、UNKNOWN 对账；离线重放不执行外部动作 | 每个提交点 crash matrix 与外部 receipt |
| Q30–Q33：并发、取消、消息重复？ | 顺序工具和同步 Provider | 先保证单机状态语义，再加租约/CAS、隔离 worktree | 重复回调与取消竞态测试 |
| Q34–Q41：怎么证明不是套壳？ | 只有 21 项课程测试，无 RepoFix 任务集 | 版本化分层评测、真实基线、Bad Case 回归和诚实的能力表述 | 公开可复现实验脚本及失败报告 |

本次修订保持原有 Python 标准库课程原型及 v0.2 的 22 节骨架。没有引入 Go 重写；Go 并发知识可用于面试，但若项目迁移语言，须单独 ADR 证明收益。只有完成上述交付并重新运行课程测试、故障测试和 RepoFix 评测，项目才可从“设计稿 + 教学原型”改称“可恢复的工程 Harness”。
