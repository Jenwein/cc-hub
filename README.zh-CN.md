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

表里 `<…>` 是必须给出的值，`[…]` 是可选项，`a|b` 列出一组命令里的子命令。

| 命令 | 用途 |
|---|---|
| `cc-hub init [dir]` | 播种总站，已有文件不覆盖 |
| `cc-hub doctor [--fix] [--json]` | 体检：必需文件、记忆预算、指针 |
| `cc-hub update [--dry-run]` | 只更新框架拥有的文件，用户文件不动，旧版本有备份 |
| `cc-hub memory log\|search\|recent` | 日志与长期记忆 |
| `cc-hub link <skills-dir>` | 把总站的每个 skill 链接进 agent 的 skills 目录 |
| `cc-hub tap add\|list\|remove` | 登记放应用的 git 仓库（tap） |
| `cc-hub app search\|install\|list\|update\|remove\|sync\|setup-state` | 从 tap 安装、升级、卸载应用 |
| `cc-hub cron list\|set\|reset` | 定时任务：列出、改时间、关掉或打开 |
| `cc-hub report list\|plan\|put\|send\|note\|section\|language\|approve` | 报告：应用按周期往里加内容的日报到年报 |
| `cc-hub feedback [--app NAME] [--json]` | 反馈问题的去处和环境信息，不发送任何东西 |
| `cc-hub where` | 打印总站目录和包的安装位置 |
| `cc-hub version` | 打印版本号 |

例子：

    cc-hub cron list                                # 列出所有定时任务和实际生效的时间
    cc-hub cron set plans/morning "0 7 * * *"       # 让 plans 应用的 morning 任务每天 07:00 运行
    cc-hub cron set ledger/prices --off             # 关掉一个任务（--on 重新打开）
    cc-hub cron reset plans/morning                 # 回到应用定义文件里的时间
    cc-hub cron set report-daily --on               # 打开日报（默认每天 08:00）
    cc-hub cron set report-weekly "0 20 * * 5"      # 周报改到每周五 20:00
    cc-hub report language zh-CN                    # 报告里的标题用中文
    cc-hub report section ledger monthly --off      # 月报里不放记账应用（ledger）那一段

cron 表达式要加引号，否则会被 shell 拆开。总站自带的任务名是 `cron/<名>.md` 的文件名（不含 `.md`），应用的任务名是 `<应用>/<任务>`。你设的时间存在 `hub.toml` 里，`cc-hub update` 和应用升级都不会改掉；`set` 和 `reset` 会打印在 cc-connect 里重新登记这个任务的步骤，由 agent 执行。平时直接跟 agent 说就行。

报告是按日、周、月、季、年发到聊天里的一份摘要，装了供稿的应用就会各加一段（应用里的 `reports/<周期>.md`，写法见 [docs/apps.md](docs/apps.md)）。`report-daily`、`report-weekly`、`report-monthly`、`report-quarterly`、`report-yearly` 五个任务默认关闭，要哪个就像上面那样打开哪个。cc-hub 自己写的标题用你设的语言（内置中文和英文，其他语言用英文）。会运行命令的段落，要你在这台机器上批准过那条命令才会运行：agent 在设置应用时问你，再执行 `cc-hub report approve <应用>`；`cc-hub report list` 列出每个周期、每一段和批准情况。发出的报告存在 `reports/` 下。后台任务没有紧急的话要说时，不单独发消息，而是用 `cc-hub report note` 留一句话给下一份报告。

## 总站布局

    ~/.cc-hub/
    ├── AGENTS.md  AGENTS.local.md  BOOTSTRAP.md      规程
    ├── SOUL.md  IDENTITY.md  USER.md                 人格与用户
    ├── MEMORY.md  memory/YYYY-MM-DD.md               记忆
    ├── skills/  cron/  scripts/                      skills、定时任务、你的脚本
    ├── apps/  apps.lock                              已安装的应用及其记录
    ├── reports/                                      已发出的报告，每份一个文件
    └── hub.toml                                      配置，以及你设的定时任务时间和报告设置

`cc-hub update` 只替换框架拥有的文件：`AGENTS.md` 结尾标记以上的部分、`BOOTSTRAP.md`、`skills/hub-*`、`cron/README.md`、`cron/memory-consolidate.md`、`cron/report-*.md`、`.gitignore` 和 `.gitattributes`。`apps/` 和 `apps.lock` 由 `cc-hub app` 管理；应用声明的数据目录归你。其余都归你，包括你或 cc-connect 写在 `AGENTS.md` 结尾标记以下的内容。

总站是一个 git 仓库：cc-hub 提交它的命令改动的文件，agent 每做完一件事提交一次。备份到私有远程见 [docs/backup.md](docs/backup.md)。

其余文档见英文 README 的链接。

## 许可证

MIT
