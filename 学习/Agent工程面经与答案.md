# Agent 工程面经：问题、参考答案与 TraceForge 拷问

> 2026-09-15 版。面向 Agent/Coding Agent 中高级岗位。题目按公开应聘者面经中反复出现的主题去重，并用 GitHub 上可核验的开源实现更新答案；**公司面经是个人自述，不是公司官方题库**。每题中的「TraceForge」状态依据本仓库 `main@5a2a51d` 的课程代码和 v0.2 原设计核对：**已实现、待实现、不能声称已实现**必须分开。配套设计见[TraceForge 项目设计文档](./TraceForge-Agent-Harness-项目设计文档.md)。

## 如何回答

面试时先用一句话给结论，再讲控制流/失败窗口/验证指标，最后拿出自己写的代码、测试或 Trace。没有数据就说没有，不把预期提升说成实测。本文 48 道题不是背诵模板；方括号中的 S 编号对应末尾 GitHub 来源。

## A. Agent 与 Harness 核心链路

### Q01. Agent、Workflow、Harness 各是什么？
**答**：Workflow 的控制流由代码预先定义；Agent 在有限动作集合里让模型根据观察选择下一步；Harness 则负责上下文、模型调用、Tool 调度、权限、状态、预算、恢复和观测。选择依据是步骤是否稳定、风险是否可接受、环境反馈是否会改变下一步，而不是名字是否“智能”。[S1][S2]
**TraceForge 拷问**：课程 `AgentRunner` 已有模型/工具循环；RepoFix 外层确定性流程尚未实现。不能说已有完整 Workflow/Profile。

### Q02. 从零设计一次 Agent Loop，状态怎样流转？
**答**：加载带 revision 的 RunState，检查预算/取消；构造上下文，记录请求，调用模型；解析并验证 Action；副作用前落意图并过策略；执行后记录观察，交 Verifier 判断成功或继续。每步有 `run_id/step_id/tool_call_id` 与明确终态。模型返回 `Finish` 只是候选完成，不是验收结论。[S2][S3]
**TraceForge 拷问**：现有 Runner 见无 ToolCall 就直接 `run.completed`，没有 Verifier、预算或取消；v0.3 将此列为首要补强。

### Q03. ReAct、Plan-Execute、固定 Workflow 怎么选？
**答**：可枚举且可验证的业务步骤用 Workflow；需要依环境观察持续决策时用短 ReAct 循环；长任务用显式计划，但只有证据变化或失败阈值触发重规划。用相同任务集比较成功率、调用轮次、P95、成本与安全失败率，别凭感觉选。[S1]
**TraceForge 拷问**：RepoFix 设为外层固定阶段，定位与修复方案用模型决策；当前仓库还没有 RepoFix 运行代码。

### Q04. 如何防止 Agent 无限循环或路径震荡？
**答**：硬上限包括步数、deadline、token 与费用。对目标、规范化动作、参数、关键观察计算指纹，识别相同动作、`A→B→A` 和连续无新证据；已知错误用确定性恢复表，未知语义问题才让模型提出有界候选。停止时给出失败证据，而不是生成虚假答案。
**TraceForge 拷问**：当前仅有 `max_turns`；还缺指纹、预算账本与进展检查。

### Q05. 模型返回多个并行 ToolCall 时怎么处理？
**答**：先检查每个动作的权限、读写集与依赖。独立只读动作可有界并发；共享文件写、审批和有副作用动作需串行或隔离工作区。所有子任务继承取消/deadline，结果以调用 ID 配对，失败不得悄悄吞掉。并行收益要扣除冲突与聚合成本。[S3]
**TraceForge 拷问**：现有 Runner 顺序执行 ToolCall；并行是扩展，不应把顺序实现描述为并发框架。

### Q06. Multi-Agent 什么时候比单 Agent 好？
**答**：任务可独立验收、可并行、需要权限或上下文隔离时才拆分。先测单 Agent 基线，计算额外模型轮次、通信成本和冲突率；主 Agent 对结果复核与最终提交负责。多个 Agent 同时写同一 checkout 是高风险设计。[S1][S4]
**TraceForge 拷问**：Explore Subagent 当前仅在设计里；目标是只读隔离 worktree，输出带文件引用的结构化发现。

### Q07. Manager-as-tool 与 handoff 有何区别？
**答**：Manager-as-tool 保留主控和最终汇总；handoff 把后续对话控制权转给专职 Agent。两者都要限定可见历史和权限，转交本身也要被审计；不能假定普通 Tool guardrail 自动覆盖 handoff。[S4]
**TraceForge 拷问**：v1 先用主控调用只读 Explore，暂不做任意 Agent 间 handoff。

### Q08. 如何判断 Agent 已完成用户任务？
**答**：使用外部可验证的验收器：文件改动范围、测试退出码、期望行为、约束遵守和证据引用。模型文本是建议，不能作为唯一成功信号。若测试不可运行，应输出 `UNVERIFIED` 和原因，不可声称已修复。
**TraceForge 拷问**：当前 Runner 无验证器；这是 v0.2 最关键的“完成即成功”漏洞。

## B. Context、Memory 与检索

### Q09. 对话历史、执行状态、长期 Memory 为什么分开？
**答**：历史是可回溯证据；RunState 保存预算、待审批动作和未完成步骤等权威状态；长期 Memory 是跨任务、可纠错和过期的候选知识。摘要仅是模型输入视图，不能替代执行状态。[S5]
**TraceForge 拷问**：当前消息数组只在 Runner 内存；尚无持久化 RunState 或长期 Memory。

### Q10. Context 压缩怎样保证不丢需求？
**答**：把用户目标、否定条件、权限、关键实体/数值、待完成事项和证据引用存为 `protected_state`。只摘要可回取的旧观察和重复推理，摘要记录原事件 ID；压缩前后做结构化约束 diff，不一致即回滚。评测约束保留率、成功率、压缩率和成本。
**TraceForge 拷问**：独立 `ContextBuilder` 尚未接入 Runner；现有 `required` 项甚至可超预算返回，目标是明确停止。

### Q11. Tool 结果巨大，怎样放进上下文？
**答**：结果保留结构化状态、关键证据、截断标记和可回取句柄；按问题需要分段读取。不要让模型仅凭截断摘要做无法验证的结论，也不要直接把全部日志塞进窗口。量化证据遗漏率、token 成本和任务成功率。
**TraceForge 拷问**：当前 Runner 把 ToolResult.value 直接塞进 messages，没有尺寸限制。

### Q12. 如何治理几百个 Tool？
**答**：先按权限、场景和版本过滤，再召回 Top-K 候选；描述中写清适用与不适用案例，参数用 Schema 验证。评测 Tool Recall@K、Top-1、参数一次通过率与冗余调用率，不能只看最终回答。
**TraceForge 拷问**：当前 Registry 仅保存名称和 handler，连 Schema 与版本都没有。

### Q13. Prompt Cache 如何设计且不泄露用户数据？
**答**：缓存稳定的系统前缀、版本化 Tool Schema 与公共规则；缓存键包含模型/推理配置、模板、工具集和权限域。用户 Memory、仓库私有内容和实时数据不能跨权限域复用；版本变化要失效。看命中率、TTFT、费用和错误复用率。
**TraceForge 拷问**：尚未实现缓存；先做好 Prompt 来源与权限隔离，不应为了命中率破坏边界。

### Q14. 长期 Memory 如何提取、纠错与遗忘？
**答**：候选记忆需来源、时间、主体、置信度和适用范围；写入前去重，读取时带权限与 TTL，冲突时保留来源并允许用户更正/删除。低信任检索内容不能变成系统指令。先证明真实任务有收益再引入存储。[S5]
**TraceForge 拷问**：v0.3 非目标，不得写进当前功能或简历。

### Q15. Query Rewrite 如何避免偏离用户意图？
**答**：输出改写文本、保留约束、新增词与置信度；低置信时原查询和改写查询双路检索，关键歧义请用户澄清。评估 Recall@K、MRR、约束保留率和语义漂移率。
**TraceForge 拷问**：RepoFix 的代码搜索可先用原始关键词与符号引用，复杂 Rewrite 不是 MVP 必需。

### Q16. RAG 的 Recall@K、Faithfulness 分别如何算？
**答**：Recall@K 需要标注相关证据集合，算 Top-K 命中的相关项比例；没有标注不能宣称具体 Recall。Faithfulness 检查答案每个事实是否被检索证据支持，可用人工抽检与校准过的 Judge 辅助，关键事实保留引用。检索是 Agent 的证据工具，不自动保证答案正确。
**TraceForge 拷问**：本项目首要评测是 RepoFix 行为，RAG 留给后续 KnowledgeAudit Profile。

## C. Tool、权限、安全与协议

### Q17. 生产 Tool 契约应包含什么？
**答**：`name/version`、用途和反例、输入/输出 Schema、权限、风险、超时、输出上限、错误码、幂等与对账能力。ToolCall 先解析和 Schema 校验，再经业务/权限检查，最后执行。Schema 约束格式，不代表授权。[S3]
**TraceForge 拷问**：当前 Registry 无 Schema，`DenyPathPolicy` 只是示例性拒绝策略。

### Q18. Tool 错误怎么分类与重试？
**答**：至少区分瞬态超时/限流/5xx、参数错误、权限拒绝、业务终态与副作用结果未知。只对安全失败有界退避；参数错误定向修复；权限拒绝不可模型绕过；未知写操作先对账。记录每次重试费用与延迟。
**TraceForge 拷问**：现有 ToolResult 主要是 `ok/error/denied`，没有上述错误类型与退避策略。

### Q19. 如何定义 Tool Calling 准确率？
**答**：拆为候选工具召回、Top-1 选择、参数一次通过、执行成功、结果正确解释和任务成功。按错误环节建立样本与 Trace，不把模型选对工具但参数越权算成功。线上还要观察无效调用率和成本。
**TraceForge 拷问**：需在 RepoFix 评测集中为每个样本标注可接受工具路径，而不只验最终文本。

### Q20. Prompt Injection 防护在哪里生效？
**答**：仓库文件、网页、检索和 Tool 输出属于低信任数据；它们可以提供任务事实，不能扩大指令或权限。确定性 Policy Gate、隔离执行、敏感数据拦截和攻击回归样本形成分层防护。只在 Prompt 写“不要泄露”不够。
**TraceForge 拷问**：现有路径段过滤挡不住符号链接、路径解析竞态或未挂载的敏感目录，目标须有真实沙箱。

### Q21. 审批怎样绑定到真正执行的动作？
**答**：审批保存 `run revision、Tool 与服务器身份、规范化参数哈希、资源、策略版本、有效期`；恢复执行前重新检验。参数、工作区或权限变化须重批。审批是中断/恢复状态，不是模型对话中的一句“用户同意”。[S6]
**TraceForge 拷问**：当前没有审批挂起/恢复，文档不能说已实现。

### Q22. Sandbox 的边界是什么？
**答**：工作目录、挂载、进程、网络、CPU/内存、时间和凭据都应显式受控；启动失败则停止，不回退宿主机。执行参数用结构化 argv，真实路径检查与 Tool 权限检查仍需保留。沙箱是能力边界，不能替代审计和审批。
**TraceForge 拷问**：当前课程代码没有沙箱；RepoFix 上线前必须实现。

### Q23. MCP 是 Tool Registry 的替代品吗？
**答**：MCP 定义外部工具、资源和提示的交互协议；Harness 仍负责可信服务器选择、候选 Tool 暴露、输入校验、权限、审计和成本。远程授权须校验 token audience，禁止把收到的 token 原样透传下游。[S7]
**TraceForge 拷问**：MCP 是 v0.3 之后的适配器，不能先接协议再补安全边界。

### Q24. Skill 与普通 Prompt 文件的区别？
**答**：可发布 Skill 应有版本、Owner、依赖、权限、适用场景、回归集与回滚路径；按需加载后仍受 Tool 权限约束。若只是几段提示词，不应称为可治理的 SkillHub。评测选择准确率、任务收益、越权率与成本。
**TraceForge 拷问**：当前 Profile 是设计，SkillHub 尚不存在；先实现稳定内核。

## D. 状态、恢复、并发与观测

### Q25. Event Log、Checkpoint、Trace、日志如何分工？
**答**：Event Log 是业务状态事实；Checkpoint 是由事件导出的恢复加速；Trace 解释调用因果与耗时；普通日志用于节点诊断。它们通过 run/step ID 关联，但不能把 Trace 当数据库，也不能用日志反推可靠状态。[S2][S8]
**TraceForge 拷问**：课程只有 JSONL Event Store 和简单 Projection，缺 Snapshot、完整性校验及 Trace span。

### Q26. 离线 Replay 是否能重现模型思考？
**答**：不能保证。离线 replay 应重建已记录事件、状态和策略判断，不重新执行外部副作用；重新请求模型是另一种实验，可能因模型版本和采样变化得到不同轨迹。必须记录 Prompt、工具和代码版本以解释差异。[S2]
**TraceForge 拷问**：当前 `project_run` 是简单事件投影，CLI `replay --offline` 仍是草案。

### Q27. Tool 成功后、Journal 写成功前崩溃怎么办？
**答**：先持久化执行意图，外部调用使用稳定幂等键；恢复时若状态为 `started/unknown`，查询外部 receipt 或对账，不能直接再执行。无对账能力且可能不可逆时停在待人工处理。跨系统不笼统承诺“恰好一次”。
**TraceForge 拷问**：当前 `EffectJournal` 是内存字典，崩溃后丢失；v0.2“第三天验证不重复”必须降为进程内验证。

### Q28. JSONL Event Store 有哪些恢复风险？
**答**：末行部分写入、并发 writer、重复序号、写入未 fsync、schema 迁移和文件损坏都可能改变投影。单机阶段至少一个 writer、尾部检测、校验和与备份；需要事件与意图事务提交时转 SQLite/Postgres。
**TraceForge 拷问**：当前 `JsonlEventStore.append()` 先读全文件计算序号再追加，无并发互斥和持久化屏障。

### Q29. 异步慢 Tool 如何挂起与恢复？
**答**：提交任务后落 `WAITING_TOOL`，worker 以租约执行；先持久化结果，再 ACK/回调；编排器用 revision/CAS 去重消费。取消和迟到结果按持久化顺序裁决，超时不代表 Tool 没执行。
**TraceForge 拷问**：当前同步工具运行时；异步是后续阶段，需先打牢 Effect 语义。

### Q30. 多 Agent 并发写一个仓库怎么办？
**答**：每个子 Agent 用基于同一 SHA 的隔离 worktree，产出补丁；主控检测写集和基线差异，再合并、回归，冲突时重评估或人工处理。共享 RunState 用 CAS，不能最后写入者获胜。
**TraceForge 拷问**：v1 Explore 只读，避免过早承受写冲突。

### Q31. 如何传播取消与 deadline？
**答**：父 Run 的 deadline 传给模型、Tool、worker 与子任务；进程组清理并在日志里记录取消原因。若取消与外部动作成功竞态，不能假定成功被撤销，要照样对账和报告。
**TraceForge 拷问**：当前 Provider.complete 未接 context/cancellation，后续接口需要改造。

### Q32. Token 与 P95 突增怎么定位？
**答**：按模型请求、上下文构造、Tool 排队/执行、重试、压缩和子任务拆分 Trace 与 usage。检查调用轮次、Tool 结果体积、缓存命中、模型版本、提示模板和循环情况；优化后同时看成功率，避免只降成本。[S8]
**TraceForge 拷问**：课程尚无 usage ledger；文档应将未知 token 记为未知，不能记 0。

### Q33. Redis 锁或 MQ 能保证恰好一次吗？
**答**：不能。锁可能过期或失去所有权，消息通常至少一次投递；用 fencing token/状态版本、下游幂等键和结果对账。结果应先持久化再 ACK，重复回调 CAS 去重。
**TraceForge 拷问**：先做单进程持久化与故障注入，再谈分布式 worker。

## E. 评测、发布与项目深挖

### Q34. 一个合格的 Agent 评测集如何构造？
**答**：分任务类型、难度、失败模式和风险；真实脱敏 Bad Case、合成边界和攻击样本分开标记。固定输入、仓库 SHA、环境、预期结果与判定脚本，开发集与留出集分离；报告分桶而不只给总分。
**TraceForge 拷问**：原设计说“初始 20 题”，仓库目前没有题集，属于目标而非成果。

### Q35. Agent 成功率如何定义？
**答**：以外部可验证的任务验收为主，同时报告约束遵守、测试通过、重复副作用、安全违规、P95 和费用。LLM Judge 可以辅助主观质量，但需要人工标注校准；不能让模型自报任务成功。
**TraceForge 拷问**：RepoFix Verifier 必须检查补丁、测试、路径和证据，缺一不标完成。

### Q36. 修一个 Bad Case 怎么证明没伤别的 Case？
**答**：最小复现进入回归集，旧新版本在同样任务、模型版本和环境下配对运行；比较分桶成功率、延迟、成本和安全门禁，保留失败样本。样本量不足时明确置信限制。
**TraceForge 拷问**：FakeProvider 的结构回归与真实模型任务成功率是两层测试，不能混成一项。

### Q37. Shadow、Canary、A/B 分别用于什么？
**答**：Shadow 在真实请求旁路运行且不执行副作用，用于比较动作与风险；Canary 小比例真实执行，观察系统指标；A/B 对照用户结果。每一步需停机与回滚条件，离线通过不等于可上线。
**TraceForge 拷问**：个人项目当前无线上流量，不能虚构 Canary 结果；可只做离线回归。

### Q38. 如何做模型路由与小模型升级？
**答**：按任务复杂度、风险和可验证性路由；简单可验收步骤先走成本低的模型，失败或低置信升级。比较端到端质量、升级率、P95、总 token 与费用，而不是单看模型单价。
**TraceForge 拷问**：先有评测与 usage ledger，后做路由；目前只有 FakeProvider。

### Q39. 什么情况下 LLM 自动诊断故障？
**答**：超时、限流、权限、参数错误等先由代码分类；未知语义失败可请模型给出结构化根因候选与证据。恢复动作仍走白名单、权限、预算、风险校验，高风险转人工。测根因命中率、误恢复率与额外费用。
**TraceForge 拷问**：不要把 LLM 诊断放在 Effect 对账前，避免“修复”造成重复副作用。

### Q40. 如何证明项目不是套壳？
**答**：列明复用的模型接口/协议和自己写的状态机、Policy、持久化、对账、验收与评测；展示失败案例、设计取舍、代码位置和测试证据。项目叙述区分“已运行课程原型”和“目标生产能力”。
**TraceForge 拷问**：当前可展示 21 项测试与课程链路，但不能写跨进程恢复、沙箱或 RepoFix 成功率。

### Q41. 没有真实线上流量怎样证明工程深度？
**答**：公布固定基准、故障注入、攻击样本、运行脚本、代码覆盖关键边界和失败复盘。说明它证明的是可复现的工程性质，不是生产规模或商业收益。
**TraceForge 拷问**：用 crash matrix 与 event/Effect 不变量作为作品集证据，比不真实的“提升 X%”更可信。

### Q42. 一分钟项目介绍怎么说？
**答**：先讲问题与基线，再说自己实现的边界、最难故障与权衡、验证结果，最后讲局限和下一步。每个数都给样本、版本和运行条件。遇到尚未实现的问题坦诚说明设计与计划，不以文档代替成果。
**TraceForge 拷问**：当前准确说法是“可运行的 Python 标准库教学原型 + 21 项测试 + v0.3 目标设计”。

## F. 补充现场追问

### Q43. Function Calling 参数合法就可以执行吗？
**答**：不可以。解析成功只是协议层；还要检查 Schema、业务条件、主体权限、资源边界、预算和是否需要审批。执行前再次校验状态版本，避免审批后参数或环境改变。[S3][S6]
**TraceForge 拷问**：当前 ToolRegistry 甚至没有严格 Schema，需先补契约。

### Q44. 模型接口的“四层成功”是什么？
**答**：传输成功、协议可解析、语义正确、用户任务完成。HTTP 200 或 JSON 合法并不保证选对 Tool，更不保证代码修复成功。错误码和指标必须分层统计。
**TraceForge 拷问**：现有 `run.completed` 只等价于收到没有 ToolCall 的响应，不代表任务成功。

### Q45. 流式响应中断了怎么处理？
**答**：不执行未完整确认的 ToolCall；保存已确认的调用 ID 和请求状态。协议支持续传则按官方语义恢复，否则重新请求，同时避免对已执行副作用重放。报告中区分模型中断与 Tool 结果未知。
**TraceForge 拷问**：当前同步 `complete()`，流式支持是后续适配器能力。

### Q46. Go 中怎样将外部并发调用限制为 3？
**答**：使用继承父 `context` 的 `errgroup.SetLimit(3)` 或信号量；为每个调用设 deadline，结果按 ID 汇集并保留部分成功。共享状态只在聚合点或 CAS 下更新，取消后清理 worker。
**TraceForge 拷问**：本仓库是 Python 教学原型，不为面试叙事临时宣称 Go 实现；Go 并发题可基于既有后端经验单独回答。

### Q47. IVF 的 nlist 与 nprobe 如何权衡？
**答**：nlist 决定索引簇数，nprobe 决定查询探测簇数；更大 nprobe 通常提高召回也增加延迟。用标注集画 Recall@K-P95 曲线，并考虑索引构建和更新成本；不能凭单一默认值给结论。
**TraceForge 拷问**：这是知识检索岗位扩展题，不必强塞进 RepoFix MVP。

### Q48. 检索证据不足或互相冲突怎么办？
**答**：先核对来源、时间、实体和版本；有冲突就保留两边证据，不编造统一结论。关键事实不足时补查或明确拒答；记录证据引用，评测错误接受率与不必要拒答率。
**TraceForge 拷问**：RepoFix 可类比为测试与代码证据冲突，Verifier 应给 `UNVERIFIED`，不能采纳模型自述。

## 来源与更新口径

- **GitHub 实现/规范**：[S1 OpenAI Agents SDK 总览](https://github.com/openai/openai-agents-python/blob/main/docs/agents.md)；[S2 DeepSeek Harness Core](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md) 与 [Session](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)；[S3 OpenAI Tool 生命周期](https://github.com/openai/openai-agents-python/blob/main/.agents/references/tool-execution-lifecycle.md)；[S4 OpenAI Handoffs](https://github.com/openai/openai-agents-python/blob/main/docs/handoffs.md)；[S5 LangGraph 持久化](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx)；[S6 OpenAI 人工审批](https://github.com/openai/openai-agents-python/blob/main/docs/human_in_the_loop.md)；[S7 MCP 安全实践](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/docs/2026-07-28/tutorials/security/security_best_practices.mdx)；[S8 OpenAI Tracing](https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md)。这些用于核对**机制**，不意味着 TraceForge 已实现同等能力。
- **面经主题线索**（应聘者自述，未经公司核实）：[B 站 Agent 开发](https://www.nowcoder.com/discuss/919630524673458176)、[阿里云 Agent 开发](https://www.nowcoder.com/feed/main/detail/42ba29ab006d4bb793112eb263d18f6a)、[字节 AI Agent](https://www.nowcoder.com/feed/main/detail/8a553bb6ea8445d0b0abe11e87614cea)、[影石 Agent/后端](https://www.nowcoder.com/feed/main/detail/b406c87436a54864bfc0cf4a20299f62)。题库还覆盖公开开源项目实际涉及、且中高级面试常追问的失败语义；不按这些帖子计算未经核实的“高频”。
- **维护规则**：新增题先记录原始来源与日期；同题合并；来源仓库更新时重新核对答案；过时接口和未经验证的频率陈述删除。GitHub `main` 链接会随时间变化，本版核对日期为 2026-09-15。

[S1]: https://github.com/openai/openai-agents-python/blob/main/docs/agents.md
[S2]: https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md
[S3]: https://github.com/openai/openai-agents-python/blob/main/.agents/references/tool-execution-lifecycle.md
[S4]: https://github.com/openai/openai-agents-python/blob/main/docs/handoffs.md
[S5]: https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx
[S6]: https://github.com/openai/openai-agents-python/blob/main/docs/human_in_the_loop.md
[S7]: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/docs/2026-07-28/tutorials/security/security_best_practices.mdx
[S8]: https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md
