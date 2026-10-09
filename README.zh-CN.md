# cc-hub

给 [cc-connect](https://github.com/chenhg5/cc-connect) 拉起的编码 agent 用的家目录。

一个聊天驱动的 agent 由三部分组成：聊天（飞书、微信、Telegram 等平台上的 bot）、把聊天接到你机器上的桥（cc-connect），以及 agent 住的本地目录。cc-hub 就是这个目录，称为**总站**：agent 的人格、对你的了解、记忆、操作规程和 skills，加一个负责播种、体检和升级它们的小工具。它的角色相当于 OpenClaw 的 workspace。

总站与 agent 无关：不带任何 Claude 或 Codex 专属文件，agent 首次运行时按自己的生态生成指针（`hub-adapt`）。

## 快速开始

    uv tool install cc-hub
    cc-hub init          # 创建 ~/.cc-hub
    cc-hub doctor

请在普通终端里安装；Windows 上不要在 Claude 桌面版内的 shell 里装（原因见 [docs/install.md](docs/install.md)）。

把 cc-connect 的 `work_dir` 指向总站（见 [docs/cc-connect.md](docs/cc-connect.md)），发第一条消息。agent 会按 `BOOTSTRAP.md` 适配自己的运行时、起名、认识你、注册定时任务，然后删除引导文件。

## 命令

| 命令 | 用途 |
|---|---|
| `cc-hub init [dir]` | 播种总站，已有文件不覆盖 |
| `cc-hub doctor [--fix] [--json]` | 体检：必需文件、记忆预算、指针 |
| `cc-hub update [--dry-run]` | 只更新框架拥有的文件，用户文件不动，旧版本有备份 |
| `cc-hub memory log\|search\|recent` | 日志与长期记忆 |
| `cc-hub link <skills-dir>` | 把总站的每个 skill 链接进 agent 的 skills 目录 |
| `cc-hub tap add\|list\|remove` | 登记放应用的 git 仓库（tap） |
| `cc-hub app search\|install\|list\|update\|remove\|sync\|setup-state` | 从 tap 安装、升级、卸载应用 |
| `cc-hub where` | 打印总站目录和包的安装位置 |
| `cc-hub version` | 打印版本号 |

## 总站布局

    ~/.cc-hub/
    ├── AGENTS.md  AGENTS.local.md  BOOTSTRAP.md      规程
    ├── SOUL.md  IDENTITY.md  USER.md                 人格与用户
    ├── MEMORY.md  memory/YYYY-MM-DD.md               记忆
    ├── skills/  cron/  scripts/                      skills、定时任务、你的脚本
    └── hub.toml                                      配置

`cc-hub update` 只替换框架拥有的文件：`AGENTS.md` 结尾标记以上的部分、`BOOTSTRAP.md`、`skills/hub-*`、`cron/README.md`、`cron/memory-consolidate.md` 和 `.gitignore`。其余都归你，包括你或 cc-connect 写在 `AGENTS.md` 结尾标记以下的内容。

其余文档见英文 README 的链接。

## 许可证

MIT
