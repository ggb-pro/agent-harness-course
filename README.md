# 导航：Sonic 与 Agent Harness

Sonic 的最终目标是聪明、强大且可信的个人通用 AI 助手。当前第一主线是先做一个真正可用的 Claude Code 类本地编码 Agent：理解仓库、修改代码、运行测试并用证据交付，再逐步扩展为通用助手。仓库现有代码仍是可复用的**教学原型**，后续允许大幅重构。

整个仓库只有四份 Markdown，按目的进入即可：

| 你要找什么 | 唯一入口 | 建议读法 |
| --- | --- | --- |
| Harness 体系知识 | [学习文档](./学习文档.md) | 从 Agent Loop 开始，系统学习工具、权限、上下文、会话、验证和扩展。 |
| Sonic 的产品与工程设计 | [设计说明](./设计说明.md) | 查看编码 Agent 的完整目标架构、数据契约、路线和验收门禁。 |
| 代码 | [sonic 源码](./代码/sonic/) | 用下面的命令跑演示与完整自动化测试；能力证据在设计说明。 |
| 面试准备与每周变化 | [面经](./面经.md) | 按 48 题的 A→F 主题查答案，来源和周报在同一页底部。 |

## 快速验证

进入 `代码/sonic`，使用 Python 3.10+：

```powershell
python -m pip install -e ".[openai]"
$env:PYTHONPATH = "src"
python examples/demo.py
python -m unittest discover -s tests -v
python scripts/check_repo.py
```

离线 Demo、仓库工具与 Provider 边界测试不需要 API Key 或联网；安装 OpenAI SDK 后还会运行一项 SDK 构造兼容性检查。现有代码提供 OpenAI Responses **纯文本 Provider 基线**和三个**本地只读仓库工具**，尚未实现真实 Provider 工具流、写文件、Shell、交互式 CLI、Session 恢复和上下文压缩。准确现状与迁移决定见[设计说明的现有代码章节](./设计说明.md#13-现有代码怎样处理)，动手入门见[学习文档的最小 Agent Loop](./学习文档.md#2-先亲手写一个最小-agent-loop)。

要自行进行会产生远程请求的纯文本 smoke，先在当前环境安全设置 `OPENAI_API_KEY`，再明确选择模型和放行本次调用：

```powershell
$env:SONIC_OPENAI_MODEL = "<你明确选择的模型>"
$env:SONIC_ALLOW_REMOTE = "1"
python examples/openai_text.py
```

这会把脚本中的固定测试句发送到 `https://api.openai.com`，可能产生费用；仓库维护者尚未把它作为已通过证据。请求显式设置 `store=False`，但这不等于 Zero Data Retention，服务端处理与保留仍受账户及 [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)约束。实现见 [OpenAIResponsesProvider](./代码/sonic/src/sonic_agent/models/openai_responses.py)，安全边界见 [Provider 测试](./代码/sonic/tests/test_openai_provider.py)。

后续维护以 GitHub 最新 `main` 为基准，按[仓库与文档约束](./设计说明.md#19-仓库与文档约束)修改、验证、通过 PR/CI 合入并核对远端。旧内容保留在 Git 历史，不把过期 ZIP 作为另一份源码提交。
