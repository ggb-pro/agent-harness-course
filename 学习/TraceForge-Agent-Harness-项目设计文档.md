# TraceForge Agent Harness 项目设计文档

> 版本：v0.2  
> 状态：可实施设计稿  
> 更新日期：2026-09-08  
> 配套教程：[`Harness工程教学.md`](./Harness工程教学.md)  
> 配套实现：[`代码/agent-harness-course`](../代码/agent-harness-course/README.md)

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

- v0.2 不做通用多 Agent 编排平台；
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

先完成单 Agent、单进程、JSONL 存储；达到可测、可恢复后，再引入数据库、沙箱、MCP 和子 Agent。

## 5. 设计来源与 TraceForge 取舍

本节只标注可明确对应的设计启发。通用软件工程做法不会被包装成某个项目的独有思想。

| TraceForge 设计 | 主要参考 | 采用方式 | TraceForge 取舍 |
| --- | --- | --- | --- |
| 稳定的外围扩展契约、Hooks、Skills、Subagents | Claude Code | 学习产品级能力边界与人机协作入口 | 不假设其未公开内部实现；先提供显式 Python 接口 |
| 插件生命周期、事件溯源、Capability Seam、工具策略流水线 | DeepSeek Harness | 将服务、事件和策略作为可组合能力 | v0.2 不复制完整插件树，保留小型 Profile 组合层 |
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

状态集合：`created -> running -> waiting_approval | completed | failed | cancelled`。

一次标准循环：

1. 构造带来源信息的上下文；
2. 追加 `model.requested`；
3. 调用 Provider，追加 `model.responded`；
4. 如果是最终回答，追加 `run.completed`；
5. 如果含工具调用，交给 ToolRuntime；
6. 将工具结果写回上下文，进入下一轮；
7. 达到轮次限制则以明确原因失败。

Runner 不能吞掉异常。所有异常必须被分类并写入 `run.failed`，但敏感信息在写入前要脱敏。

### 8.2 Provider

```python
class Provider(Protocol):
    def complete(self, messages: list[Message]) -> AssistantResponse: ...
```

`AssistantResponse` 只能是最终文本或零到多个结构化 ToolCall。Provider 适配器负责供应商格式转换、超时、重试元数据和用量采集，不负责业务策略。

`FakeProvider` 接收预先编排的响应序列，是单元测试和 Golden Trace 的默认 Provider。

### 8.3 Event Store

事件最小结构：

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

### 8.4 Projection

Projection 从事件生成：运行摘要、当前状态、工具统计、错误列表和审计时间线。Projection 可删除并重建，不反向修改事件。

### 8.5 Tool Registry

工具定义包含名称、说明、输入校验器、风险等级、是否有副作用和执行函数。注册时拒绝重名；调用时拒绝未知参数；返回值必须是可序列化结构。

### 8.6 Policy Pipeline

策略输入包含运行主体、Profile、工具、参数、工作区和既有授权。输出只能是：

- `allow`：立即执行；
- `deny`：记录理由并停止该调用；
- `require_approval`：挂起运行并等待一次性批准。

默认策略包括敏感路径拒绝、工作区边界、命令 allowlist、网络域名限制和写操作审批。

### 8.7 Effect Journal

记录结构：`effect_id`、工具名、规范化参数哈希、状态、尝试次数、结果引用、错误和更新时间。

状态机：

```text
planned -> started -> completed
                  \-> failed -> started
                  \-> uncertain -> reconciled
```

`effect_id` 由 `run_id + tool_call_id + normalized_args` 派生。同一 ID 与不同参数同时出现属于完整性错误。

### 8.8 Context Builder

每个 Context Item 包含 `source`、`content`、`priority`、`trust`、`created_at` 和 `token_estimate`。构建顺序固定，预算不足时按规则裁剪，不能删除安全策略和当前用户目标。

工具返回的不可信文本要明确标注，防止检索文档中的指令被提升为系统规则。摘要保留来源 ID，便于回到原始事件。

### 8.9 Profile

Profile 是一组显式配置：Prompt Sources、工具集合、策略集合、上下文预算、最大轮次和评测集。v0.2 不允许 Profile 动态修改内核服务，避免过早进入复杂插件生命周期。

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

## 11. 可靠性与恢复

失败分类：模型瞬态错误、模型永久错误、策略拒绝、等待审批、工具失败、超时、进程崩溃和状态完整性错误。

恢复原则：

- 只对明确可重试的错误做有限指数退避；
- 重试信息写入事件，不能隐藏成本；
- 副作用重试前查询 Journal；
- `uncertain` 不自动假定失败，要调用 reconcile；
- 不可恢复错误进入明确终态并输出可操作报告。

## 12. 可观测性

每次运行至少提供：耗时、模型轮次、工具调用数、拒绝次数、审批等待、token/费用（若 Provider 提供）、重试次数、完成状态和失败类别。

日志、指标与 Trace 通过 `run_id` 关联。结构化事件是审计依据，普通日志只服务运维诊断。

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

RepoFix 初始评测集包含 20 个小型仓库任务。指标包括任务成功率、测试通过率、中位轮次、成本、误拒绝、越权尝试和恢复成功率。Harness 改动必须与基线比较，不能只展示成功案例。

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
| 1 | FakeProvider、状态机、事件模型 | 无 API Key 跑通终态和工具循环 |
| 2 | JSONL Event Store、Projection | 重启后可重建同一摘要 |
| 3 | Tool Registry、Policy Pipeline | 敏感路径在执行前被拒绝 |
| 4 | Effect Journal | 重复调用不产生重复副作用 |
| 5 | Context Builder、来源追踪 | 超预算可预测裁剪，强规则保留 |
| 6 | RepoFix Profile | 在样例仓库完成读—改—测闭环 |
| 7 | 故障注入与恢复 | 三类崩溃点均有明确恢复结果 |
| 8 | Golden Trace、固定评测集 | 变更前后可自动对比 |
| 9 | Explore Subagent、沙箱接口 | 子任务权限严格小于主任务 |
| 10 | CLI、文档、演示 | 新用户 10 分钟内运行示例 |

## 17. 前 72 小时实施计划

### 第一天

定义 Event、AssistantResponse、ToolCall 和 RunState；实现 FakeProvider；完成无工具的最小 Runner；为事件顺序写测试。

### 第二天

加入 Tool Registry、拒绝策略与 JSONL Event Store；跑通一次 FakeProvider 发起工具调用、工具返回、模型结束的完整路径。

### 第三天

冻结第一条 Golden Trace；实现最小 Effect Journal；模拟“副作用完成后、事件写入前”崩溃并验证不会重复执行。

这 72 小时内不接真实模型、不上 Docker、不接 MCP、不做多 Agent。目标是先证明内核可测试、可追踪、可恢复。

## 18. ADR 清单

- ADR-001：事件日志作为运行事实源；
- ADR-002：Provider 与 Runner 分离；
- ADR-003：Policy 与 Tool 分离；
- ADR-004：副作用必须通过 Effect Journal；
- ADR-005：Profile 采用显式组合而非动态插件树；
- ADR-006：上下文条目保存来源与可信度；
- ADR-007：第一阶段使用 JSONL 与单进程写入；
- ADR-008：多 Agent 仅在评测证明收益后引入。

每份 ADR 记录背景、决定、替代方案、后果和撤销条件。

## 19. 验收标准

v0.2 原型满足以下条件即可进入下一阶段：

- 从空环境按 README 可运行，核心测试无需 API Key；
- 一次工具循环产生完整且有序的事件；
- 对相同 `effect_id` 的重试不会重复执行；
- 敏感路径访问在工具执行前被拒绝；
- 可从 JSONL 重建运行状态与工具统计；
- Provider 或工具故障会产生明确失败事件；
- Golden Trace 不依赖真实时间和随机 ID；
- 教程、设计文档、示例代码三者术语一致。

## 20. 后续演进

第一阶段稳定后再评估：SQLite/PostgreSQL Event Store、真实容器或远程沙箱、MCP Capability Adapter、长期 Memory、KnowledgeAudit Profile、并发运行、分布式 Worker 和 Web 时间线。

每项演进都需回答三个问题：它解决了哪个可复现问题？引入了什么新的失败模式？用哪组评测证明收益大于复杂度？

## 21. 作品集表达

可以将项目描述为：

> 设计并实现可审计、可恢复的 Agent Harness。以追加式事件日志统一运行事实，通过策略流水线隔离工具权限，使用 Effect Journal 解决副作用幂等与崩溃恢复，并以 FakeProvider、Golden Trace 和故障注入建立确定性回归测试。

这比“接入多个模型、实现多个工具”的表述更能体现运行时、可靠性与系统设计能力。

## 22. 结论

TraceForge 的价值不在于让 Agent 看起来更聪明，而在于让系统行为更可控。当事件、权限、副作用、上下文和评测都成为明确协议后，模型可以替换，工具可以增长，运行仍然能够解释与恢复。这也是项目从课程示例走向工程平台的主线。
