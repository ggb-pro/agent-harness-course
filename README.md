# Sonic：从可用的编码助手走向个人通用助手

先让 Sonic 在真实代码仓库里完成读、改、测和交付，再逐步扩展为通用助手。产品行为参考 Claude Code，运行内核自行实现，重点是能理解、能复现、能持续改进。

## 四个入口

| 内容 | 从哪里开始 |
| --- | --- |
| [学习文档](./学习文档.md) | 围绕一个折扣金额 Bug，跑通修复，再制造冲突、超时和恢复，理解 Harness |
| [设计说明](./设计说明.md) | Sonic v0.1 的范围、协议、工具、SQLite、恢复窗口、提交计划和验收 |
| [代码](./代码/sonic/) | 现有教学原型与 Mini Sonic 实验；产品 CLI 尚待实现 |
| [面经](./面经.md) | 独立题库与来源更新，项目能力以设计说明为准 |

## 先运行课程实验

从仓库根目录执行，Python 3.10+，只用标准库，无需 API Key：

```powershell
python 代码/sonic/examples/mini_sonic.py --case normal
python 代码/sonic/examples/mini_sonic.py --case stale
python 代码/sonic/examples/mini_sonic.py --case resume
```

分别观察正常修复、用户修改引发的冲突、由第二个进程接续工作。文件和测试真实发生在临时目录，决策来自假模型；这些结果不代表真实模型成功率。全部七个实验见[学习文档第二章](./学习文档.md#二运行同一个实验)。

## 当前能运行什么

`sonic_agent 0.5.0` 是旧教学包，已有同步循环、事件存储、纯文本 Provider 和只读仓库工具。尚无产品 `sonic` CLI、真实模型工具流、通用编辑和检查命令闭环。

本轮文档定义的是新的产品 **Sonic v0.1**，不是已经发布的版本。现有代码处理方式见[迁移表](./设计说明.md#十一当前代码与迁移)，下一步从[提交 C1](./设计说明.md#十按提交推进而不是一次造完)开始。

验证旧原型与新课程实验：

```powershell
cd 代码/sonic
python -m pip install -e ".[openai]"
python -m unittest discover -s tests -v
python scripts/check_repo.py
```

这组测试不发真实模型请求。安装依赖需要联网；Windows 下无法创建符号链接、以及 POSIX 专用测试可能跳过，CI 同时运行 Windows/Linux。

## 维护方式

GitHub main 是基准，通过分支、PR 和 CI 更新；仓库保持四份 Markdown。新机制以可运行实验和任务证据决定是否采用，范围及细则见[仓库维护约束](./设计说明.md#十三仓库维护约束)。
