# cc-hub

给 [cc-connect](https://github.com/chenhg5/cc-connect) 拉起的编码 agent 用的"总站"：一套目录约定加一个命令行工具。

cc-connect 把 Claude Code、Codex 等 agent 接到飞书、微信、Telegram 等 IM，并在 `work_dir` 里启动 agent。cc-hub 把这个目录变成 agent 在你机器上的家：人格、记忆、项目和远程主机注册表。权限和后台任务交给 cc-connect 与 agent 运行时自己处理，总站只提供规范和路由。

总站与 agent 无关：不带任何 Claude 或 Codex 专属文件，agent 首次运行时按自己的生态生成指针（`hub-adapt`）。

## 快速开始

    uv tool install cc-hub
    cc-hub init          # 创建 ~/.cc-hub
    cc-hub doctor

请在普通终端里安装；Windows 上不要在 Claude 桌面版内的 shell 里装（原因见 [docs/install.md](docs/install.md)）。

把 cc-connect 的 `work_dir` 指向总站（见 [docs/cc-connect.md](docs/cc-connect.md)），发第一条消息。agent 会按 `BOOTSTRAP.md` 起名、认识你、登记项目、适配自己的运行时，然后删除引导文件。

## 命令

| 命令 | 用途 |
|---|---|
| `cc-hub init [dir]` | 播种总站，已有文件不覆盖 |
| `cc-hub doctor [--fix] [--json]` | 体检：必需文件、记忆预算、指针 |
| `cc-hub update [--dry-run]` | 只更新框架拥有的文件，用户文件不动，旧版本有备份 |
| `cc-hub memory log\|search\|recent` | 日志与长期记忆 |
| `cc-hub link <src> <dst>` | symlink / junction / 复制，按平台自动选 |
| `cc-hub where` | 打印总站目录和包的安装位置 |
| `cc-hub version` | 打印版本号 |

其余文档见英文 README 的链接。

## 许可证

MIT
