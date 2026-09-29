# cc-hub 设计规格

日期：2026-09-22
状态：待用户审阅
调研依据：[docs/research/2026-09-22-research-brief.md](../../research/2026-09-22-research-brief.md)

> **2026-09-29 变更**：总站定位收敛为"规范 + 路由"，不重复 cc-connect 和 agent 运行时已经提供的能力。据此删除 j 安全护栏（`cc-hub hook`：黑名单、审计日志）和 b 后台任务（`cc-hub jobs`、`hub-jobs` skill）。权限交给 cc-connect 的审批模式和 agent 自身的权限设置；长任务交给 agent 运行时自己的后台机制，这些任务随 cc-connect 会话一起结束（`/new`、`/switch`、空闲超时、daemon 重启）。2026-09-28 在原生 Windows 上的实测也显示 hook 在 Claude Code 和 Codex 下都会失效放行。以下第 2 节的 b、j 两项，§6.5、§6.7、§7 的 `hub-jobs` 行、§9 和 §14 的第 6、8 步均已作废；`doctor` 新增 `stale-hooks` 检查，`update` 会备份并移除已退役的框架文件。同一原则下还删除了：`hosts check/run/push/pull`（只保留 `hosts.toml` 和 `hosts list` 作注册表，agent 自己用 ssh）、`memory stats`、`doctor` 的 `daemon-path` 检查与 `ENV.md` 的 daemon 可见性标注、`hub-adapt` 的权限目标（禁读规则与 Codex `writable_roots`）。

---

## 1. 背景与目标

cc-connect 把 Claude Code、Codex 等编码 agent 桥接到飞书、微信、Telegram 等 IM。agent 在 cc-connect 配置的 `work_dir` 里启动。cc-connect 对 `work_dir` 里有什么完全不关心，只在里面建 `.cc-connect/attachments/`。

cc-hub 填这个空位：把 `work_dir` 变成一个"总站"，一套目录约定加一个小工具，让从聊天里拉起来的 agent 能稳定地操作用户的机器：记住事情、找到项目、派后台任务、连远程主机、把结果发回聊天，并且有一道不依赖审批的安全地板。

目标：

- 开源，MIT，跨平台（Linux、macOS、Windows、WSL2）。
- 与 agent 无关、与 bot 无关。总站按通用 AI 生态约定布局，agent 自己适配自己的生态。
- 框架可升级，用户的人格、记忆、注册表永远不被升级覆盖。

## 2. 核心决策

以下决定在设计讨论中已定，不再重开：

| 决定 | 内容 |
|---|---|
| 工作模式 | 总站是唯一 `work_dir`。日常任务 agent 直接 cd 到项目目录干；长任务派后台。 |
| agent 无关 | 总站不含任何 agent 专属指针。指针由 agent 在首次运行时按自己的生态生成，做成可重复的 `hub-adapt` skill。 |
| bot 无关 | 几个 bot、几个 agent、谁连谁，全是 cc-connect 的配置，总站不管。 |
| 脚本语言 | Python，用 uv 运行。编码规范见第 11 节。 |
| 发布形态 | PyPI 包 `cc-hub`，`init` 播种到用户目录，`doctor` 体检，`update` 只覆盖框架文件。不做 Go 二进制。 |
| 默认位置 | `~/.cc-hub/`，可 `init <dir>` 指定别处。 |
| 模板语言 | 框架拥有的文件用英文。用户拥有的文件内容任意语言。 |
| CLI 框架 | typer 分发，rich 只用于给人看的命令。 |
| 砍掉的命令 | `cron`（cc-connect 自带 `cc-connect cron add`）、`send`（`cc-connect send` 够用）。两者写成 skill 说明。 |
| v1 能力 | a 项目注册表、b 后台任务、c 定时任务清单、d 结果回传约定、e 记忆、f 环境探测、g 远程主机、j 安全护栏。 |
| 留到 v2 | h 浏览器自动化、i 桌面 GUI 控制。 |

## 3. 范围

### 3.1 v1 交付物

1. PyPI 包 `cc-hub`，命令行入口 `cc-hub`。
2. 总站模板：人格文件、规程、注册表、6 个内置 skills、1 个内置 cron 任务。
3. 文档：安装、cc-connect 配置示例、Windows 说明、Codex 沙箱说明、手工验收清单。

### 3.2 非目标（v1 不做）

- 浏览器自动化、桌面 GUI 控制。
- 向量或语义记忆检索。ripgrep 级别的文本检索够用。
- 多总站、多用户。
- MCP 配置生成。用户按各自 agent 的方式配置 MCP。
- 子 agent 定义文件。
- 使用 cc-connect 的 `[[hooks]]` 事件。
- Go 或 Rust 二进制。
- 自动删除或压缩 `memory/` 日志。

## 4. 总站目录布局与所有权

```
~/.cc-hub/                   所有权        说明
├── hub.toml                 框架(结构)    模板版本、名称、少量配置；update 只改版本号并合并新键
├── AGENTS.md                框架          操作规程
├── AGENTS.local.md          用户          用户和 agent 的补充规程，init 时建空文件
├── BOOTSTRAP.md             框架(一次性)  首次仪式，完成后 agent 删除；update 不重建
├── SOUL.md                  用户          人格、语气、边界
├── IDENTITY.md              用户          名字、气质、emoji
├── USER.md                  用户          关于用户的稳定信息
├── MEMORY.md                用户          长期精选记忆，上限 200 行
├── memory/YYYY-MM-DD.md     用户          日志
├── projects.toml            用户          本机项目注册表
├── hosts.toml               用户          远程主机注册表
├── cron/                    混合          README.md 与内置任务归框架，用户任务归用户
├── skills/<name>/SKILL.md   混合          hub- 前缀的归框架，其余归用户
├── scripts/                 用户          用户和 agent 自己写的脚本
├── secrets/                 用户 gitignore  .env、密钥
├── ENV.md  env.json         派生 gitignore  cc-hub env 生成
├── jobs/                    派生 gitignore  <id>.json 状态，<id>.log 输出
├── logs/YYYY-MM-DD.jsonl    派生 gitignore  hook 写的操作日志
├── .cc-hub/backups/         派生 gitignore  update 前的框架文件备份
├── .cc-connect/             派生 gitignore  cc-connect 自己建的附件目录
├── CLAUDE.md .claude/ .agents/ .codex/  派生 gitignore  agent 按自身生态生成的指针
└── .gitignore               框架
```

三条规则：

1. **所有权按清单不按目录。** 包内 `manifest.py` 列出框架拥有的相对路径。`update` 只覆盖清单内的文件。用户在 `skills/`、`cron/` 下新建的文件不在清单里，永不被碰。
2. **一次性仪式和可重复适配分开。** `BOOTSTRAP.md` 只做一次的事。为当前 agent 生态生成指针是 `hub-adapt` skill，`BOOTSTRAP.md` 调用它，`AGENTS.md` 也要求"指针缺失就跑它"。
3. **总站必须在所有代码仓库之外。** `init` 检查目标目录是否已在某个 git 仓库内，是则拒绝。原因：Claude Code 会加载所有父目录的 `CLAUDE.md`，auto-memory 也会挂到父仓库。`init` 默认在总站里 `git init`，`--no-git` 可关。

## 5. 核心文件设计

### 5.1 AGENTS.md（框架拥有，上限 150 行，英文）

唯一常驻的规程。9 段，顺序即 agent 每次会话的执行顺序：

1. **你在哪**：这是总站，一句话定义，文件地图。
2. **会话开始**：若 `BOOTSTRAP.md` 存在先执行它；读 `IDENTITY.md`、`SOUL.md`、`USER.md`、`MEMORY.md`、今天和昨天的 `memory/` 日志、`AGENTS.local.md`；`ENV.md` 缺失或超过 7 天则跑 `cc-hub env`；自己生态的指针缺失则跑 `hub-adapt`。
3. **记忆规则**：做完一件有结果的事、做出决策、发现环境事实，就 `cc-hub memory log`；用户表达的稳定偏好写 `USER.md`；`MEMORY.md` 只在整理任务或用户明确要求时改；群聊里不复述 `USER.md`、`MEMORY.md` 的私人内容。
4. **跨目录工作**：先查 `projects.toml`；日常任务用绝对路径或 cd 到项目里干；项目文件不进总站；长任务和后台编码用 `cc-hub jobs`，编码任务在新 worktree 里跑。
5. **后台任务约定**：启动后告诉用户任务 id；被问进度用 `jobs status`；完成后把结果摘要写进 memory log。
6. **远程主机**：查 `hosts.toml`，用 `cc-hub hosts run`；远端破坏性操作必须用户明确要求。
7. **和 cc-connect 配合**：收到的附件在 `.cc-connect/attachments/`；回传用 `cc-connect send --file <绝对路径>`；长输出先落文件再回传；定时任务用 `cc-connect cron add`。
8. **安全规则**：黑名单由 hook 强制，不要试图绕过；`secrets/` 不读不打印；`SOUL.md` 只在用户要求时改，改了要说；命令找不到就查 `ENV.md` 里的绝对路径。
9. **最后读 `AGENTS.local.md`**。

### 5.2 BOOTSTRAP.md（框架拥有，一次性，英文）

开头一句：这是仪式不是门槛，用户的请求永远优先。9 步：

1. 跑 `cc-hub env`，读 `ENV.md`；找不到 `cc-hub` 就报告安装问题并停下。
2. 跑 `hub-adapt`。
3. 问用户怎么称呼你，一句气质 + emoji，写 `IDENTITY.md`，气质同步到 `SOUL.md` 开头。不许自己起名。
4. 问用户三件事：称呼、语言、主要在忙什么，写 `USER.md`。
5. 登记 1 到 3 个常用项目到 `projects.toml`，可跳过。
6. 问有没有远程主机，有就登记 `hosts.toml`，可跳过。
7. 把 `cron/` 下 `default: true` 的任务用 `cc-connect cron add` 注册；cc-connect 不可用就记进 memory log 留待以后。
8. 一句话说明黑名单和审批机制。
9. 写第一条 memory log，删除 `BOOTSTRAP.md`，跑 `cc-hub doctor` 汇报结果。

### 5.3 人格与记忆文件格式

`IDENTITY.md`，固定三行，可被脚本解析：

```
- Name:
- Vibe:
- Emoji:
```

`SOUL.md`：自由 Markdown。模板给四个小节：核心气质、沟通方式、边界、不做的事。只在用户要求时修改，修改后告知。

`USER.md`：指令式行，每行带观察日期。过时的行加 `superseded` 标记，不删。上限 100 行。

```
- Address the user as X <!-- observed: 2026-09-22 -->
- Reply in Chinese; keep technical terms in English <!-- observed: 2026-09-22 -->
```

`MEMORY.md`：四个小节：Decisions、Facts、Environment & tools、Pitfalls。每条 `- 2026-09-22: 内容`。上限 200 行 / 25 KB。只由整理流程或用户明确要求修改。

`memory/YYYY-MM-DD.md`：扁平列表。文件首行 `# YYYY-MM-DD`。`cc-hub memory log` 追加 `- [HH:MM] 内容`，多行内容缩进续行。agent 也可以手写。

### 5.4 注册表与配置

```toml
# projects.toml
[[project]]
name = "unifx"
path = "~/dev/UnifX"
description = "..."
notes = "tests: uv run pytest"
added = 2026-09-22
```

```toml
# hosts.toml
[[host]]
name = "nas"
target = "user@nas.local"       # ssh 目标，或 ~/.ssh/config 里的别名
port = 22
shell = "bash"                  # bash | pwsh | powershell，决定远端解码方式
key = "secrets/nas_ed25519"     # 可选，相对总站根目录
notes = ""
```

```toml
# hub.toml
[hub]
name = "hub"
template_version = "0.1.0"      # init 写入，update 更新
created = 2026-09-22

[memory]
max_lines = 200
recent_days = 2

[env]
tools = ["git", "uv", "python", "node", "docker", "tmux", "ssh", "rg", "jq", "claude", "codex", "cc-connect"]

[hooks]
blocklist_extra = []            # 用户追加的黑名单正则
```

### 5.5 cron 任务文件

`cron/<name>.md`，frontmatter 加正文：

```
---
schedule: "0 3 * * *"
default: true
session: new_per_run          # reuse | new_per_run，对应 cc-connect 的 session_mode
---
Run the memory consolidation procedure described in the hub-memory skill.
```

内置一个 `cron/memory-consolidate.md`，每天 03:00，`new_per_run`。`cron/README.md` 说明格式和注册方法。

## 6. cc-hub CLI 设计

### 6.1 通用约定

- **定位总站**，按顺序：`--hub <path>`、环境变量 `CC_HUB_DIR`、从 cwd 向上找 `hub.toml`、`~/.cc-hub`（存在 `hub.toml` 时）。找不到退出 1 并说明四种方式。
- **输出**：给 agent 读的命令默认纯文本无颜色，所有查询类命令支持 `--json`。给人看的 `init`、`doctor`、`update` 用 rich 表格；非 TTY 下 rich 自动关色。错误写 stderr，退出 1。退出码 2 只给 hook 阻断用。
- **依赖**：typer、rich、tomli-w、charset-normalizer、psutil。Python ≥ 3.11（tomllib 在标准库）。
- **写文件**：json 和 toml 一律先写临时文件再 rename。
- **编码**：见第 11 节。

### 6.2 init / doctor / update

`init [dir] [--name NAME] [--no-git]`

- `dir` 默认 `~/.cc-hub`。
- 拒绝嵌套在 git 仓库内的目标目录。
- 只创建缺失文件；已存在的一律不碰。
- 写 `hub.toml` 的 `template_version` 为包版本。
- 默认 `git init`。
- 结尾打印"已创建 / 已跳过"清单和下一步：把 cc-connect 的 `work_dir` 指过来，第一次对话触发 bootstrap。

`doctor [--fix] [--json]`

每项检查输出 id、状态（ok / warn / fail）、说明、修复提示。检查项：

| id | 检查 |
|---|---|
| hub-toml | 可解析；`template_version` 是否落后于包版本 |
| required-files | 必需文件齐全 |
| bootstrap-pending | `BOOTSTRAP.md` 仍存在，提示初始化未完成 |
| memory-budget | `MEMORY.md` ≤ max_lines，`USER.md` ≤ 100 行 |
| memory-files | `memory/` 文件名符合 `YYYY-MM-DD.md` |
| projects | `projects.toml` 可解析，路径存在 |
| hosts | `hosts.toml` 可解析，`shell` 取值合法 |
| env-stale | `ENV.md` 缺失或超过 7 天 |
| pointers | 按已安装的 agent 检查指针（见第 8.3 节参考表） |
| link-stale | 有 `.cc-hub-copied` 标记且 `skills/` 比复制件新 |
| daemon-path | 最小 PATH 模拟（Unix `/usr/bin:/bin`，Windows `System32`），报告 `cc-hub`、`uv`、`cc-connect`、`claude`、`codex` 哪些会丢 |
| nested-git | 总站是否在别的 git 仓库内 |
| jobs-lost | 状态 running 但进程已死 |

`--fix` 只做安全的事：补建缺失的用户空文件、重写 `.gitignore`、把死掉的 job 标 lost。指针不由它生成。`daemon-path` 的修复提示指向 cc-connect 的 `[projects.agent.options.env]` 里设 `PATH`。

`update [--dry-run]`

- 覆盖清单内的框架文件。覆盖前把旧文件备份到 `.cc-hub/backups/<旧版本>/`。
- `BOOTSTRAP.md` 已不存在就不重建。
- `hub.toml` 新增键用默认值合并，已有值不覆盖。
- 打印变更列表。

### 6.3 env

`env [--json]`

写 `ENV.md` 和 `env.json`。`ENV.md` 分节：

- System：OS、版本、架构、是否 WSL（内核字符串含 microsoft）、家目录、时区、locale、`PYTHONUTF8`。
- Shell：bash、pwsh、powershell、cmd 哪些存在、路径、默认是哪个。
- Tools：`hub.toml` 的 `tools` 列表里每项的存在与版本。
- Agents & bridge：`claude`、`codex`、`cc-connect` 是否安装及版本；`~/.claude`、`~/.codex`、cc-connect 配置路径是否存在。
- Paths：`cc-hub`、`uv`、`python`、`cc-connect`、`claude`、`codex` 的绝对路径，以及每个在最小 PATH 下是否可见。
- Resources：CPU 数、内存、总站所在盘剩余空间。
- Generated at：时间戳。

### 6.4 memory

- `memory log "<text>"`：追加到今天的文件。文件不存在先写标题行。多行文本的续行缩进两个空格。
- `memory search <query> [--days N] [--limit N] [--regex]`：搜 `memory/*.md` 和 `MEMORY.md`，按日期倒序，每条命中带一行上下文，忽略大小写。
- `memory recent [--days N]`：默认打印 `hub.toml` 的 `recent_days` 天。
- `memory stats`：各文件行数对预算。

### 6.5 jobs

`jobs start [--cwd DIR] [--name NAME] -- <command...>`

- id 形如 `20260922-143012-a1f3`（本地时间 + 4 位十六进制随机）。
- 脱离启动一个 runner（`cc-hub jobs _run <id>`），runner 作为父进程运行命令、等待、写回退出码和结束时间。Unix 用 `start_new_session=True`，Windows 用 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`。stdin 接 devnull。
- 子进程环境追加 `PYTHONUTF8=1`。
- 子进程输出按原始字节写 `jobs/<id>.log`，读取时探测解码。
- 立即返回 id 和日志路径。

`jobs/<id>.json`：

```json
{
  "id": "20260922-143012-a1f3",
  "name": "tests",
  "cmd": ["uv", "run", "pytest"],
  "cwd": "/home/x/dev/foo",
  "pid": 12345,
  "runner_pid": 12340,
  "started": "2026-09-22T14:30:12+08:00",
  "ended": null,
  "status": "running",
  "exit_code": null,
  "log": "jobs/20260922-143012-a1f3.log"
}
```

`status` 取值：running、done（退出码 0）、failed（非 0）、stopped、lost（runner 和进程都死了但没写退出码）。

- `jobs status [id] [--json]`：列表或单个；顺手校正状态。
- `jobs log <id> [--tail N]`：默认末尾 50 行。不做 follow。
- `jobs stop <id> [--force]`：Unix 对 runner 所在进程组发 SIGTERM，10 秒后 SIGKILL；Windows 对 `runner_pid` 执行 `taskkill /T /F` 杀整棵树。
- `jobs clean [--older-than Nd]`：删除结束时间早于 N 天前的任务的 json 和 log，默认 7d。

runner 的健壮性：命令不存在时状态 failed、退出码 127、原因写进 log。

### 6.6 hosts

- `hosts list [--json]`。
- `hosts check <name>`：`ssh -o BatchMode=yes <target> true`。只走密钥，不交互输密码。
- `hosts run <name> [--timeout SEC] -- <command...>`：命令体 base64 后发送。
  - `shell = "bash"`：远端执行 `bash -c "$(printf %s <b64> | base64 -d)"`。base64 字符集不含需要转义的字符，stdin 保持可用。
  - `shell = "pwsh"` 或 `"powershell"`：远端执行 `pwsh -NoProfile -EncodedCommand <b64>` 或 `powershell -NoProfile -EncodedCommand <b64>`，其中 b64 是命令体 UTF-16LE 编码后的 base64，这是 PowerShell 的原生要求。
  - ssh 参数：`-p <port>`、`-i <key>`（有则加，相对总站解析）、`-o BatchMode=yes`。
  - 远端输出按原始字节收回，探测解码后打印。退出码透传。
- `hosts push <name> <local> <remote>`、`hosts pull <name> <remote> <local>`：scp 薄封装，参数同上。

### 6.7 hook

`hook pre-tool-use`

- 从 stdin 读 JSON。在 `tool_input` 里找 `command` 或 `cmd`（字符串或列表）以及 `file_path` 或 `path`。
- 命令：折叠空白后匹配内置黑名单正则加 `hub.toml` 的 `blocklist_extra`。
- 路径：落在总站 `secrets/` 内，或文件名匹配 `.env`、`.env.*`（`.env.example` 除外）即拦。
- 命中：stderr 写原因，退出码 2。未命中或找不到可检查的字段：退出 0。载荷解析失败：退出 0 并在 stderr 留一句。
- `hook test "<command>"`：本地验证规则，打印是否命中及命中的规则名。

内置黑名单初始集（按规则名）：

| 规则名 | 拦截 |
|---|---|
| rm-root | `rm` 带递归强制标志且目标为 `/`、`~`、`$HOME`、`/*` |
| mkfs | `mkfs` 系列 |
| dd-device | `dd` 的 `of=` 指向 `/dev/` |
| redirect-device | 重定向到 `/dev/sd*`、`/dev/nvme*`、`/dev/disk*` |
| fork-bomb | `:(){ :|:& };:` 及变体 |
| pipe-to-shell | `curl` 或 `wget` 的输出管道到 `sh`、`bash`、`zsh` |
| power | `shutdown`、`reboot`、`poweroff`、`halt`、`Stop-Computer`、`Restart-Computer` |
| force-push-main | `git push` 带 `-f` 或 `--force` 且目标含 `main` 或 `master` |
| chmod-root | `chmod -R` 或 `chown -R` 作用于 `/` |
| win-remove-root | `Remove-Item -Recurse -Force` 或 `rd /s /q` 作用于盘根或用户目录 |
| win-format | `format`、`diskpart` |

`hook post-tool-use`

- 从 stdin 读 JSON，追加一行到 `logs/YYYY-MM-DD.jsonl`：`ts`、`session_id`、`tool`、`command` 或 `path`、`success`、`cwd`。
- 任何异常吞掉，永远退出 0。

`hook snippet`

打印两家共用形状的 JSON，命令用 `cc-hub` 的绝对路径：

```json
{"hooks": {
  "PreToolUse": [{"matcher": "Bash|PowerShell|Read",
    "hooks": [{"type": "command", "command": "/abs/path/cc-hub hook pre-tool-use"}]}],
  "PostToolUse": [{"matcher": "Bash|PowerShell",
    "hooks": [{"type": "command", "command": "/abs/path/cc-hub hook post-tool-use", "async": true}]}]
}}
```

agent 自己决定把它放进 `.claude/settings.json` 还是 `.codex/hooks.json`。

### 6.8 projects

- `projects list [--json]`。
- `projects add <path> [--name] [--description] [--notes]`：展开 `~`、校验存在、按规范化路径去重；`name` 缺省取目录名。
- `projects remove <name>`。
- `projects show <name>`。

### 6.9 link

`link <src> <dst>`

- Unix 和 macOS：symlink。
- Windows：先试 junction；失败则复制并在目标内留标记文件 `.cc-hub-copied`。
- 打印实际采用的方式。`doctor` 的 `link-stale` 依赖这个标记。

### 6.10 其它

- `version`。
- `where`：打印总站根目录和包安装位置。

## 7. 内置 skills

6 个，框架拥有，`hub-` 前缀，Agent Skills 规范的 `SKILL.md`，每个不超过 100 行，英文。逻辑都在 `cc-hub` 里，skill 只是说明书。

| skill | 触发场景 | 内容要点 |
|---|---|---|
| `hub-adapt` | 首次运行、换 agent、doctor 报指针缺失 | 见第 8 节 |
| `hub-memory` | 记东西、找东西、整理记忆 | 何时 `memory log`；`memory search` 用法；整理流程 |
| `hub-jobs` | 任务预计超过几分钟、跑测试或构建、派编码任务 | 何时后台何时直接跑；汇报约定；编码任务先 `git worktree add` 再 `jobs start --cwd <worktree>`；完成后合并与清理 |
| `hub-hosts` | 提到某台远程机器 | `hosts` 各子命令；远端破坏性操作需用户明确要求；怎么登记新主机 |
| `hub-projects` | 提到某个项目、要去别的目录干活 | 查注册表、`projects add`、项目文件不进总站 |
| `hub-cc-connect` | 要把文件或图发回聊天、收到附件、设定时任务 | `cc-connect send --file <绝对路径>`；附件位置；长输出先落文件；`cc-connect cron add`；`/dir` 只对下一会话生效 |

`hub-memory` 的整理流程：读近 7 天日志；把仍成立的事实并入 `MEMORY.md` 四个小节；超预算则合并同类、删过时条目；`USER.md` 里被新观察推翻的行标 `superseded`；最后写一条 memory log 记录本次整理。

## 8. hub-adapt 与生态适配

### 8.1 原则

agent 知道自己是谁、自己的生态把文件放哪。skill 不写分支，只列目标，每个目标附上总站提供的确定性工具。

### 8.2 目标清单

1. 让你的生态的指令文件指向 `AGENTS.md`。若你原生读 `AGENTS.md`，什么都不用做。
2. 让你的 skills 发现路径能到达 `skills/`。用 `cc-hub link skills <你的路径>`。
3. 安装两个钩子。`cc-hub hook snippet` 打印 JSON，你放进自己的钩子配置。
4. 在你的权限系统里禁读 `secrets/` 和 `.env`。确保你的沙箱或权限允许写入 `projects.toml` 里登记的路径；`projects add` 之后重做这一条。
5. 你的生态若需要用户做一次交互式信任（信任目录、信任钩子），明确告诉用户怎么做。

做完跑 `cc-hub doctor`，写一条 memory log。整个过程幂等，重跑无副作用。

### 8.3 已知生态参考表（附在 skill 末尾，标注"可能过时，以你的官方文档为准"）

| 生态 | 指令文件 | skills 路径 | hooks 配置 | 权限禁读 | 需要的信任 |
|---|---|---|---|---|---|
| Claude Code | `CLAUDE.md` 内容为 `@AGENTS.md`；v2.1.277 起无 `CLAUDE.md` 时原生读 `AGENTS.md` | `.claude/skills` | `.claude/settings.json` 的 `hooks` | `permissions.deny`：`Read(./secrets/**)`、`Read(./.env)` | 在总站里交互式运行一次 `claude` 接受信任提示，否则 `-p` 模式下项目级权限规则不生效 |
| Codex CLI | 原生读 `AGENTS.md` | `.agents/skills` | `.codex/hooks.json` | 无直接禁读规则；`.codex/config.toml` 的 `[sandbox_workspace_write] writable_roots` 登记项目路径 | 交互式运行一次 `codex`，`/hooks` 信任钩子，把总站标为 trusted |

`doctor` 的 `pointers` 检查用同一张表。

### 8.4 Codex 沙箱限制

Codex 的沙箱对子进程树生效，`jobs start` 起的后台进程同样受 `writable_roots` 约束。Codex 下要么把项目路径登记进 `writable_roots`，要么在 cc-connect 里给 Codex 配 `--add-dir`。Claude Code 没有这个问题，cc-connect 用的是权限模式而非文件系统沙箱。写进文档和 `hub-jobs` skill。

## 9. 安全护栏

三层，从上到下：

1. **cc-connect 审批转发**：`/mode default` 把每次工具调用转发到聊天审批。这是第一道线，但用户会开 yolo 或点 allow all。
2. **agent 运行时钩子**：`hook pre-tool-use` 的黑名单，即使 yolo 也生效。cc-connect 自己的 `[[hooks]]` 只有桥接层生命周期事件（`message.received`、`session.started`、`permission.requested` 等），看不到也拦不住单次工具调用，所以地板只能放在 agent 运行时钩子上。
3. **秘密隔离与审计**：`secrets/`、`.env` 进 gitignore 并被钩子和权限规则禁读；`hook post-tool-use` 写只追加的操作日志。

## 10. 与 cc-connect 的配合

cc-connect 配置片段（写进安装文档）：

```toml
[[projects]]
name = "hub"
admin_from = "<your user id>"

[projects.agent]
type = "claudecode"

[projects.agent.options]
work_dir = "/home/you/.cc-hub"      # 用绝对路径；~ 展开在 cc-connect 1.5.1 之后才支持
mode = "default"

[projects.agent.options.env]
PATH = "/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin"
PYTHONUTF8 = "1"
```

- `PATH`：cc-connect 以 daemon 运行时不读 shell 配置文件，PATH 往往只有系统目录。`[projects.agent.options.env]` 直接给 agent 进程设 PATH。`doctor` 的 `daemon-path` 检查指向这里。
- 附件：cc-connect 把收到的文件放在 `<work_dir>/.cc-connect/attachments/<messageID>/`，并在提示词后追加绝对路径。
- 回传：`cc-connect send --file <绝对路径>`、`--image`、`--tts`。50 MB 上限。
- 定时：`cc-connect cron add --cron "<expr>" --prompt "<text>"`。
- `/dir` 只对下一个会话生效。

## 11. 跨平台与编码规范

Python 代码硬性规则：

- 所有文件读写显式 `encoding="utf-8"`；进程环境设 `PYTHONUTF8=1`。
- 路径一律 `pathlib`。
- 启动时 `sys.stdout.reconfigure(encoding="utf-8")`，stderr 同理。
- 来源不明的字节（子进程输出、远端输出、日志文件）用 `charset-normalizer` 探测后解码。
- 源码文件 UTF-8 无 BOM，首行带编码声明。
- 发往远端的命令体一律 base64。

平台规则：

- 不用 symlink 指向指令文件；`link` 命令在 Windows 上 junction 优先、复制兜底。
- 仓库 `.gitattributes` 设 `* text=auto eol=lf`；模板 lint 测试检查无 CRLF、无 BOM。
- 最小 PATH：Unix `/usr/bin:/bin`，Windows `%SystemRoot%\System32`。
- Windows 上 hook 命令用 `cc-hub` 的绝对路径，避免 `.cmd` shim 问题。
- WSL 下总站放 Linux 文件系统，不放 `/mnt/c`。

## 12. 源码仓库、测试、发布

### 12.1 仓库布局

```
cc-hub/
├── pyproject.toml            name=cc-hub, python>=3.11, 入口 cc-hub
│                             依赖: typer, rich, tomli-w, charset-normalizer, psutil
├── README.md  README.zh-CN.md  LICENSE(MIT)  CHANGELOG.md
├── .gitattributes            * text=auto eol=lf
├── src/cc_hub/
│   ├── cli.py                typer 分发
│   ├── hub.py                定位总站、读写 hub.toml
│   ├── manifest.py           框架拥有的文件清单
│   ├── templates/            AGENTS.md BOOTSTRAP.md SOUL.md IDENTITY.md USER.md MEMORY.md
│   │                         AGENTS.local.md hub.toml .gitignore projects.toml hosts.toml
│   │                         cron/README.md cron/memory-consolidate.md skills/hub-*/SKILL.md
│   ├── commands/             init doctor update env memory jobs hosts hook projects link
│   ├── platform.py           OS 判断、脱离进程启动、link/junction/copy、最小 PATH
│   ├── encoding.py           utf-8 读写、探测解码、base64 包装
│   └── blocklist.py          内置黑名单正则
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/             Claude 和 Codex 的 hook 载荷样本
├── docs/
│   ├── install.md  cc-connect.md  windows.md  codex-sandbox.md  acceptance.md
│   ├── research/
│   └── superpowers/specs/
└── .github/workflows/        ci.yml  release.yml
```

### 12.2 测试策略

- 单元测试只测纯函数：黑名单匹配、bash 与 pwsh 两种 base64 包装、日志文件名和时间戳、清单与磁盘一致、`IDENTITY.md` 解析。
- 集成测试用 subprocess 真跑 `cc-hub`，在临时目录里，路径故意带中文和空格：
  - `init` 后 `doctor` 全绿。
  - 改一个框架文件再 `update`，能备份并覆盖，用户文件纹丝不动，`BOOTSTRAP.md` 删除后不重建。
  - `jobs start` 一个 sleep 脚本，看 running 到 done、退出码正确、`stop` 能杀掉、命令不存在标 failed。
  - hook 喂两家的 fixture：该拦的退出 2 且 stderr 有原因，该放的退出 0，post 永远 0 且写出合法 jsonl，解析失败退出 0。
  - `link` 在 Windows 上 junction 失败回退到复制并留标记。
- hosts 的 ssh 不在 CI 里真连，只测载荷构造；设了 `CC_HUB_TEST_SSH_HOST` 才跑真实连接。
- 模板 lint 测试：`AGENTS.md` ≤ 150 行，每个 `SKILL.md` ≤ 100 行且 frontmatter 合法，全部无 BOM、LF 换行。
- CI 矩阵：ubuntu、macos、windows × Python 3.11、3.12。ruff 检查。
- 端到端不自动化，写成 `docs/acceptance.md` 手工验收清单。

### 12.3 发布

- 语义化版本，`template_version` 即包版本。
- `CHANGELOG.md` 每版一节"迁移说明"，`doctor` 发现版本落后时提示去看。
- 打 tag `v*` 触发 CI：`uv build`，PyPI trusted publishing，同时建 GitHub release。
- PyPI 名 `cc-hub` 于 2026-09-22 查询为未占用，首次发布时注册。

## 13. 错误处理横切规则

- json 和 toml 先写临时文件再 rename。
- hook pre 阶段：解析失败放行并在 stderr 留一句；只有明确命中才阻断。post 阶段任何异常都吞掉，退出 0。
- jobs runner：命令不存在标 failed、退出码 127、原因写 log，不留 running 僵尸。
- 找不到总站退出 1 并说明四种定位方式。
- `update` 覆盖前必备份；备份失败则整个 update 中止。

## 14. 手工验收清单（docs/acceptance.md 的内容）

环境：WSL2，cc-connect 以 daemon 运行，Claude Code 作为 agent，飞书或其它 IM 一个。

1. `uv tool install cc-hub`，`cc-hub init`，`cc-hub doctor` 除 bootstrap-pending 和 pointers 外全绿。
2. 配置 cc-connect `work_dir` 和 `env.PATH`，重启 daemon。
3. 发第一条消息，agent 执行 bootstrap：问名字、写 `IDENTITY.md`、`USER.md`，跑 `hub-adapt`，注册 cron，删除 `BOOTSTRAP.md`。
4. `cc-hub doctor` 全绿。
5. 让 agent 记一件事，`memory/` 出现今天的文件；`memory search` 能找到。
6. 让 agent 在某个登记项目里后台跑测试，收到任务 id；追问进度，agent 用 `jobs status` 回答；完成后 memory log 有摘要。
7. 让 agent 在一台登记的远程主机上执行带中文和引号的命令，输出正确。
8. 让 agent 执行一条会命中黑名单但即使漏拦也无害的命令，例如在一个没有 remote 的临时仓库里 `git push --force origin main`，被拦并解释原因。
9. 让 agent 把一个文件发回聊天，收到。
10. 把包版本号 bump 后 `cc-hub update`，`AGENTS.md` 更新，`SOUL.md`、`USER.md`、`memory/` 未变，备份目录出现旧版本。

## 15. 待验证项

实现时要确认，结论回填本节：

1. Codex 项目级 `.codex/config.toml` 是否接受 `[sandbox_workspace_write]`；不接受则参考表改为用户级 `~/.codex/config.toml`。
2. Codex hook 载荷的实际字段名和工具名，从真实运行中抓取写入 fixtures。`hook snippet` 里的 matcher 用的是 Claude 的工具名；若 Codex 的工具名不同，snippet 增加 `--no-matcher` 变体（匹配所有工具，由 `pre-tool-use` 自己按字段过滤）。
3. Claude Code 在原生 Windows 上对 junction 形式 `.claude/skills` 的发现是否正常（issue #68318 曾报告问题）；不正常则 Windows 上 `link` 直接复制。
4. cc-connect 对 `work_dir` 的 `~` 展开在哪个版本发布；发布前文档一律用绝对路径。
5. rich 在 Windows 旧控制台下的表格渲染是否需要降级为 ASCII 边框。
