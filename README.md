# 导航：sonic 与 Agent Harness

sonic 的最终目标是聪明、强大且可信的通用 AI 助手。现在先把受限仓库问题助手作为第一个真实场景推进；仓库当前仍是可运行的**教学内核**，并非已能自动修复真实仓库的产品。

整个仓库只有四份 Markdown，按目的进入即可：

| 你要找什么 | 唯一入口 | 建议读法 |
| --- | --- | --- |
| Harness 体系知识 | [学习文档](./学习文档.md) | 先读“上篇十讲”的任务故事；再按问题查“下篇专题”。 |
| sonic 的产品与工程设计 | [设计说明](./设计说明.md) | 从目标、当前能力表到安全与演进门禁；设计不等于实现。 |
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

离线 Demo 与 Provider 边界测试不需要 API Key 或联网；安装 OpenAI SDK 后还会运行一项真实 SDK 构造兼容性检查。代码已提供 OpenAI Responses **纯文本 Provider 基线**：每次 `Runner.run(...)` 都要单独传入本 Run 的远程授权，授权不会保存在 Runner 上供下一次复用；凭据只从环境变量读取。当前证据来自离线测试和对 SDK 构造器的 mock，尚未完成真实联网 smoke，也未完成 OpenAI Function Calling 工具闭环、隔离修复、跨进程效果对账或 RepoFix Verifier。逐项状态见[设计说明的能力表](./设计说明.md#当前代码到底实现到哪)。

要自行进行会产生远程请求的纯文本 smoke，先在当前环境安全设置 `OPENAI_API_KEY`，再明确选择模型和放行本次调用：

```powershell
$env:SONIC_OPENAI_MODEL = "<你明确选择的模型>"
$env:SONIC_ALLOW_REMOTE = "1"
python examples/openai_text.py
```

这会把脚本中的固定测试句发送到 `https://api.openai.com`，可能产生费用；仓库维护者尚未把它作为已通过证据。请求显式设置 `store=False`，但这不等于 Zero Data Retention，服务端处理与保留仍受账户及 [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)约束。实现见 [OpenAIResponsesProvider](./代码/sonic/src/sonic_agent/models/openai_responses.py)，安全边界见 [Provider 测试](./代码/sonic/tests/test_openai_provider.py)。

后续维护以 GitHub 最新 `main` 为基准，按[设计说明中的持续维护约束](./设计说明.md#本仓库怎样持续维护这份设计)修改、验证、通过 PR/CI 合入并核对远端。旧分散文档保留在 Git 历史，不把过期 ZIP 作为另一份源码提交。
