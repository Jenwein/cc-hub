# cc-hub 设计规格

适用版本：0.3.0

---

## 1. 定位

一个聊天驱动的编码 agent 由三部分组成：

| 部分 | 职责 | 在 OpenClaw 里对应 | 在这里 |
|---|---|---|---|
| 聊天 | 用户在 IM 里和 agent 对话 | channels | bot（飞书、微信、Telegram 等） |
| 连接本地 | 会话、路由、审批转发、附件收发、定时调度，以及向 agent 说明这些能力怎么用 | Gateway | [cc-connect](https://github.com/chenhg5/cc-connect) |
| 本地目录 | agent 的家：人格、记忆、规程、skills | [workspace](https://docs.openclaw.ai/concepts/agent-workspace) | **cc-hub** |

cc-connect 在配置的 `work_dir` 里启动 agent（Claude Code、Codex 等）。cc-hub 把这个目录变成 agent 的 workspace，称为**总站**，并提供一个小工具负责它的播种、体检和升级。

cc-hub 的职责只有两件：

1. **把东西放在约定的位置**：人格、用户信息、记忆、规程、skills、定时任务定义，文件格式沿用 OpenClaw workspace 的约定（`AGENTS.md`、`SOUL.md`、`IDENTITY.md`、`USER.md`、`BOOTSTRAP.md`、`MEMORY.md`、`memory/`、`skills/`）。
2. **让 agent 读得到**：OpenClaw 的 Gateway 会把 workspace 文件注入会话，cc-connect 不做这件事。所以总站顺着各 agent 生态的惯例（原生读 `AGENTS.md`、`CLAUDE.md` 导入、skills 发现路径），让 agent 自己读到这些文件。

执行命令和权限属于 agent 运行时；会话、调度、附件和审批属于 cc-connect。总站里除框架文件以外放什么，由用户和 agent 自己决定。

## 2. 原则

- 开源，MIT，跨平台：Linux、macOS、Windows、WSL2。
- **agent 无关**：总站不带任何 agent 专属文件。指向总站的指针由 agent 首次运行时按自己的生态生成（`hub-adapt`）。
- **bot 无关**：几个 bot、几个 agent、谁连谁，都是 cc-connect 的配置。
- **框架可升级，用户文件永不被覆盖**：所有权按清单判定，`update` 只碰清单里的框架文件。
- **小**：Python 包 `cc-hub`，用 `uv tool install` 安装；`init` 播种，`doctor` 体检，`update` 升级。框架拥有的文件用英文，用户文件语言不限。

## 3. 总站布局与所有权

```
~/.cc-hub/                  所有权            说明
├── AGENTS.md               框架（保留尾部）  规程；分界标记以下的内容归用户和 cc-connect
├── AGENTS.local.md         用户              补充规程，init 时建空文件
├── BOOTSTRAP.md            框架（一次性）    首次仪式，完成后 agent 删除；update 不重建
├── SOUL.md                 用户              人格、语气、边界
├── IDENTITY.md             用户              名字、气质、emoji
├── USER.md                 用户              关于用户的稳定信息
├── MEMORY.md               用户              长期精选记忆
├── memory/YYYY-MM-DD.md    用户              日志
├── skills/<name>/SKILL.md  混合              hub- 前缀的归框架，其余归用户
├── cron/                   混合              README.md 与内置任务归框架，其余归用户
├── scripts/                用户              用户和 agent 自己写的脚本
├── hub.toml                框架管结构        值归用户；update 只合并新键和改版本号
├── .gitignore              框架
├── .cc-hub/backups/        派生              update 前的框架文件备份
├── .cc-connect/            派生              cc-connect 自己建的附件目录
└── CLAUDE.md .claude/ .agents/ .codex/   派生   agent 按自身生态生成的指针
```

`.gitignore` 忽略凭据（`.env`、`.env.*`，`.env.example` 除外；`secrets/`）、`.cc-hub/`、`.cc-connect/` 和 agent 指针。

三条规则：

1. **所有权按清单，不按目录。** `manifest.py` 列出框架拥有的相对路径。用户在 `skills/`、`cron/` 下新建的文件不在清单里，永远不被碰。
2. **一次性仪式和可重复适配分开。** `BOOTSTRAP.md` 只做一次的事；生成指针是可重复的 `hub-adapt` skill，`BOOTSTRAP.md` 调用它，`AGENTS.md` 要求指针缺失时再跑。
3. **总站在所有代码仓库之外。** Claude Code 会加载所有父目录的 `CLAUDE.md`，auto-memory 也按仓库挂载，所以 `init` 拒绝在 git 仓库内或已有仓库的根目录播种。`init` 默认在总站里 `git init`，`--no-git` 关闭。

## 4. 核心文件

### 4.1 AGENTS.md（框架，保留尾部，≤ 150 行）

唯一常驻的规程。各节顺序就是 agent 每次会话的执行顺序：

1. **你在哪**：一句话定义总站，加文件地图。
2. **会话开始**：`BOOTSTRAP.md` 存在就先执行它；读 `IDENTITY.md`、`SOUL.md`、`USER.md`、`MEMORY.md`；跑 `cc-hub memory recent`；自己生态的指针缺失就跑 `hub-adapt`；读 `AGENTS.local.md`。
3. **记忆**：做完有结果的事、做出决策、了解到这台机器的事实，就 `cc-hub memory log`；用户表达的稳定偏好写进 `USER.md`；`MEMORY.md` 只在整理任务或用户明确要求时修改；群聊里不复述 `USER.md`、`MEMORY.md` 的私人内容。
4. **cc-connect**：发文件、定时任务等用法由 cc-connect 提供，在系统提示里，或在本文件末尾的 cc-connect 块里；`cron/` 里的任务定义按 `cron/README.md` 注册。
5. **安全**：不读、不打印、不复制凭据（`.env`、密钥、token）；总站外的不可逆操作先确认；`SOUL.md` 只在用户要求时改，改了要说。
6. **本地补充**：最后读 `AGENTS.local.md` 并遵守。

文件最后一行是分界标记：

```
<!-- cc-hub: framework content ends here; everything below is kept by cc-hub update -->
```

标记以下的内容归用户和 cc-connect。cc-connect 对不支持系统提示注入的 agent（如 Codex），会在用户发 `/cron setup` 或 `/bind setup` 时把它的用法追加到 `<work_dir>/AGENTS.md` 末尾；用户在聊天里发 `/memory add` 也会追加到这里。`update` 保留这部分（见 §5.4）。

### 4.2 BOOTSTRAP.md（框架，一次性）

开头一句：这是仪式不是门槛，用户的请求永远优先。6 步：

1. **检查**：跑 `cc-hub version`；找不到 `cc-hub` 就告诉用户安装不完整并停下。
2. **适配**：读 `skills/hub-adapt/SKILL.md` 并照做（这时 skills 还没接通，只能按路径找）。
3. **起名**：问用户怎么称呼你，不许自己起名；商定一句气质和一个 emoji。三者写进 `IDENTITY.md`，气质写进 `SOUL.md` 的 "Core vibe"。
4. **认识用户**：问怎么称呼对方、用什么语言回复，各写成 `USER.md` 里一条带日期的指令，替换占位行。
5. **定时任务**：跑 `cc-connect cron list`；`cron/` 下每个 `default: true` 且 `hub:<name>` 尚未登记的任务（`<name>` 为去掉 `.md` 的文件名），执行
   `cc-connect cron add --cron "<schedule>" --prompt "<body>" --session-mode <session> --desc "hub:<name>"`。
   cc-connect 不可用就记一条 memory log 留待以后。
6. **收尾**：`cc-hub memory log "Bootstrap completed: <name>, <language>"`，删除 `BOOTSTRAP.md`，跑 `cc-hub doctor` 并汇报。

### 4.3 人格与记忆文件

`IDENTITY.md`：固定三行，可被脚本解析。

```
- Name:
- Vibe:
- Emoji:
```

`SOUL.md`：自由 Markdown，模板给四节：Core vibe、How I communicate、Boundaries、Things I do not do。只在用户要求时修改，修改后告知。

`USER.md`：指令式行，每行带观察日期；被取代的行追加 `<!-- superseded: YYYY-MM-DD -->`，不删。上限 100 行。模板只有两条占位：

```
- Address the user as (set during bootstrap) <!-- observed: 2026-10-08 -->
- Reply in (language set during bootstrap) <!-- observed: 2026-10-08 -->
```

`MEMORY.md`：四节 Decisions、Facts、Environment & tools、Pitfalls，每条 `- YYYY-MM-DD: 内容`。上限 200 行（`hub.toml` 的 `memory.max_lines`）。只由整理流程或用户明确要求修改。

`memory/YYYY-MM-DD.md`：扁平列表，首行 `# YYYY-MM-DD`。`cc-hub memory log` 追加 `- [HH:MM] 内容`，多行内容续行缩进两个空格。agent 也可以手写。

`AGENTS.local.md`：用户和 agent 的补充规程，模板只有标题和一行说明。

### 4.4 hub.toml

```toml
[hub]
name = "hub"
template_version = "0.3.0"      # init 写入，update 更新
created = 2026-10-08

[memory]
max_lines = 200
recent_days = 2
```

### 4.5 cron 任务定义

`cron/<name>.md`，frontmatter 加正文：

```
---
schedule: "0 3 * * *"
default: true                 # bootstrap 时注册
session: new_per_run          # reuse | new_per_run，对应 cc-connect 的 --session-mode
---
Prompt text the agent receives when the task fires.
```

调度本身属于 cc-connect：任务从哪个聊天注册，结果就回到哪个聊天。内置 `cron/memory-consolidate.md`，每天 03:00，`new_per_run`，执行 `hub-memory` 的整理流程。`cron/README.md` 说明格式和注册命令。

## 5. CLI

命令：`init`、`doctor`、`update`、`memory log|search|recent`、`link`、`where`、`version`。

### 5.1 通用约定

- **定位总站**，按顺序：`--hub <path>`、环境变量 `CC_HUB_DIR`、从当前目录向上找 `hub.toml`、`~/.cc-hub`（存在 `hub.toml` 时）。找不到退出 1，并列出这四种方式。
- **输出**：给 agent 读的命令输出纯文本，查询类命令支持 `--json`。给人看的 `init`、`doctor`、`update` 用 rich 表格。错误写 stderr，退出 1。
- **依赖**：typer、rich、tomli-w。Python ≥ 3.11（`tomllib` 在标准库）。
- **写文件**：一律先写同目录临时文件再 `os.replace`。

### 5.2 init

`init [dir] [--name NAME] [--git/--no-git]`

- `dir` 默认 `~/.cc-hub`；拒绝 git 仓库内的目录，以及没有 `hub.toml` 的仓库根目录。
- 只创建缺失的文件和目录（`memory/`、`scripts/`），已存在的一律不碰。
- `hub.toml` 的 `template_version` 写包版本。
- 默认 `git init`。
- 结尾打印"已创建 / 已保留"清单和下一步：把 cc-connect 的 `work_dir` 指过来，发第一条消息。总站不在 `~/.cc-hub` 时，提示在 cc-connect 里设置 `CC_HUB_DIR`。

### 5.3 doctor

`doctor [--fix] [--json]`。每项检查输出 id、状态（ok / warn / fail）、说明、修复提示；有 fail 时退出 1。某个文件读不了只让对应检查失败，其它检查照常进行。

| id | 检查 |
|---|---|
| hub-toml | 可解析；`template_version` 是否等于包版本（不等时提示 `cc-hub update`，并先读 CHANGELOG） |
| required-files | 框架文件和用户文件齐全（一次性文件除外） |
| bootstrap-pending | `BOOTSTRAP.md` 仍存在，首次仪式未完成 |
| memory-budget | `MEMORY.md` ≤ `max_lines`，`USER.md` ≤ 100 行 |
| memory-files | `memory/` 下文件名符合 `YYYY-MM-DD.md` |
| pointers | 对本机装了的、且已在总站里设置过的 agent，检查指令文件和每个 skill 的链接（见 §7） |
| nested-git | 总站是否在别的 git 仓库内 |

`--fix` 只做安全的事：重写 `.gitignore`、补建 `memory/` 和 `scripts/`、补建缺失的用户文件。指针不由它生成。

### 5.4 update

`update [--dry-run]`

- 把清单里的框架文件更新到当前包的模板。被改动的旧文件先备份到 `.cc-hub/backups/<旧版本>/`；备份失败则整个 update 中止，什么都不改。
- 一次性文件（`BOOTSTRAP.md`）已不存在就不重建。
- 包里已不再提供的框架文件：备份后删除，目录空了一并删除。
- **保留尾部**：清单里标为保留尾部的文件（`AGENTS.md`）只替换分界标记及以上的部分，标记以下原样接回。文件里没有分界标记、但有 cc-connect 的 `<!-- cc-connect-instructions -->` 时，从该标记起保留到文件末尾；两者都没有则整份替换。替换后与原文件相同的算作未改动。
- `hub.toml`：用模板默认值补齐缺失的表和键，已有的值不覆盖；`template_version` 改为包版本。原地编辑，保留用户的注释和排版；无法原地编辑时退回整份重写。
- 打印每个文件的状态：updated、unchanged、not present (one-time)、removed (retired)。

### 5.5 memory

- `memory log "<text>"`：追加到今天的日志；文件不存在先写标题行。
- `memory search <query> [--days N] [--limit N] [--regex] [--json]`：搜 `MEMORY.md` 和 `memory/*.md`，按日期倒序，忽略大小写，忽略 HTML 注释（模板说明、观察日期），每条命中带下一行作上下文。默认最多 50 条。
- `memory recent [--days N]`：按日期倒序打印最近 N 天的日志，默认取 `hub.toml` 的 `memory.recent_days`。

### 5.6 link

`link <skills-dir>`，把总站 `skills/` 下每个 skill（含 `SKILL.md` 的子目录）链接进一个 agent 的 skills 目录；`<skills-dir>` 相对路径以总站为基准，不存在就创建。

- 每个 skill 一个目录链接：`<skills-dir>/<name>` → `<hub>/skills/<name>`。Linux、macOS 用 symlink，Windows 用 junction。链接建不出来就报错退出。
- 已经指向总站对应 skill 的项报 `existing`；新建的报 `linked`；指向总站里已不存在的 skill 的链接删除并报 `removed`；同名但不是指向该 skill 的项不碰，报 `blocked`，命令退出 1。
- 不是总站 skill 的其它项（agent 自己生态里的 skill 等）不碰。
- 每行输出状态和 skill 名，用制表符分隔。重复运行结果不变；新增或删除 skill 后再跑一次。

### 5.7 where / version

`where` 打印总站根目录和包的安装位置；找不到总站时仍打印包位置，退出 1。`version` 打印包版本。

## 6. 内置 skills

两个，框架拥有，`hub-` 前缀，符合 Agent Skills 规范的 `SKILL.md`，每个 ≤ 100 行，英文。

| skill | 触发场景 | 内容 |
|---|---|---|
| `hub-adapt` | 首次运行、换 agent、增删 skill 后、`doctor` 报指针缺失 | 见 §7 |
| `hub-memory` | 记东西、找东西、整理记忆 | 何时 `memory log`；`memory search`、`memory recent` 用法；整理流程 |

`hub-memory` 的整理流程：读近 7 天日志；把仍然成立、跨天有用的条目并入 `MEMORY.md` 四节；超预算时合并同类、删去被后来条目推翻或已不成立的条目；`USER.md` 里被新观察取代的行标 `superseded`；最后写一条 memory log 记录本次整理。任何记忆文件里都不写凭据。

## 7. hub-adapt 与生态路由

总站是指令（`AGENTS.md`）和 skills（`skills/<name>/`）的唯一事实源，各生态通过指针到达它们。agent 知道自己是谁、自己的生态在哪里找指令和 skills；`hub-adapt` 列目标，agent 按参考表落到具体文件。每一步幂等，重跑无副作用。

目标：

1. **指令**：生态有自己的指令文件，就建它，内容只有导入 `AGENTS.md` 的一行；只读 `AGENTS.md` 的生态什么都不用做。
2. **skills**：运行 `cc-hub link <自己的 skills 目录>`（§5.6）。skills 靠 frontmatter 被发现、正文按需加载，每个 skill 一个目录链接能让 frontmatter、正文和辅助文件都从总站读到。新 skill 一律建在 `skills/<name>/`，增删 skill 后重跑。本次会话开始时 skills 目录还不存在的话，运行时可能要重新加载或开新会话才看得到，告诉用户。
3. **信任**：运行时若需要一次交互式信任才读这个目录的指令或 skills，明确告诉用户怎么做。

做完跑 `cc-hub doctor`，修好它报的问题，再写一条 memory log。

已知生态参考表（附在 skill 末尾，注明"可能过时，以官方文档为准"；`doctor` 的 `pointers` 用同一张表）：

| 生态 | 指令指针 | skills 路径 | 信任 |
|---|---|---|---|
| Claude Code | `CLAUDE.md`，内容只有 `@AGENTS.md` | `.claude/skills`（重新加载：`/reload-skills`） | 读指令和 skills 不需要 |
| Codex CLI | 不需要，原生读 `AGENTS.md` | `.agents/skills` | Codex 要求时把目录标为 trusted |

Claude Code 只在没有 `CLAUDE.md` 时才读 `AGENTS.md`，而 cc-connect 的 `/memory add` 会创建 `CLAUDE.md` 并追加内容。所以 Claude Code 下一律建带导入行的 `CLAUDE.md`，之后追加的内容都在导入行下面。

`pointers` 检查：只评判已在总站里设置过的生态（指令文件或 skills 目录任一存在），本机装了但没在这里用过的 agent 不算问题。对设置过的生态，指令文件要存在且含 `@AGENTS.md`；`skills/` 里每个 skill 在该生态的 skills 目录里都要有指向总站的链接，没有指向已删除 skill 的失效链接。

## 8. 与 cc-connect 的配合

cc-connect 配置片段（写进 `docs/cc-connect.md`）：

```toml
[[projects]]
name = "hub"

[projects.agent]
type = "claudecode"

[projects.agent.options]
work_dir = "/home/you/.cc-hub"      # 绝对路径
mode = "default"

[projects.agent.options.env]
PATH = "/home/you/.local/bin:/usr/local/bin:/usr/bin:/bin"
PYTHONUTF8 = "1"
CC_HUB_DIR = "/home/you/.cc-hub"    # 总站不在 ~/.cc-hub 时需要
```

- `work_dir` 用绝对路径。
- cc-connect 以后台服务运行时不读 shell 配置，PATH 往往只有系统目录；在 `[projects.agent.options.env]` 里给 agent 进程设完整 PATH，`cc-hub` 才找得到。
- cc-connect 自己向 agent 说明发文件、定时、中继等用法：对 Claude Code 通过 `--append-system-prompt` 注入；对 Codex 等不支持注入的 agent，用户在聊天里发一次 `/cron setup`，cc-connect 把说明追加到总站 `AGENTS.md` 末尾，`update` 保留它。
- 定时任务的注册见 §4.2 第 5 步和 §4.5。
- `/dir` 只对下一个会话生效；`work_dir` 保持指向总站。

## 9. 跨平台与编码规范

Python 代码：

- 所有文件读写显式 `encoding="utf-8"`，写入用 LF。
- 路径一律 `pathlib`。
- 启动时把 stdout、stderr 重设为 UTF-8。
- 源码文件 UTF-8 无 BOM，首行 `# -*- coding: utf-8 -*-`。

平台：

- 仓库 `.gitattributes` 设 `* text=auto eol=lf`；模板全部 LF、无 BOM（有些 skill 加载器遇到 CRLF 会静默丢掉 frontmatter）。
- Windows 上建 symlink 需要开发者模式或管理员权限，所以 `link` 用 junction（目录连接点），不需要特殊权限。
- 给人看的表格由 rich 渲染；在旧版 Windows 控制台下 rich 自动换用能显示的边框，agent 读的是纯文本或 `--json`。
- WSL 下总站放 Linux 文件系统，不放 `/mnt/c`。
- Windows 上在普通终端安装 cc-hub，不在 Claude 桌面版内的 shell 里装：桌面版是 MSIX 打包应用，它的 shell 在 `%APPDATA%` 下新建的目录落在应用私有存储里，cc-connect 看不到。

## 10. 仓库、测试、发布

### 10.1 仓库布局

```
cc-hub/
├── pyproject.toml            name=cc-hub，python>=3.11，入口 cc-hub；依赖 typer、rich、tomli-w
├── README.md  README.zh-CN.md  LICENSE  CHANGELOG.md
├── .gitattributes            * text=auto eol=lf
├── src/cc_hub/
│   ├── cli.py                typer 分发，where、version
│   ├── console.py            定位总站、JSON 输出、rich console
│   ├── hub.py                定位总站、读写 hub.toml
│   ├── manifest.py           文件所有权清单、模板渲染
│   ├── platform.py           平台判断、目录链接（symlink / junction）
│   ├── encoding.py           UTF-8 读写、原子写、stdio
│   ├── commands/             init doctor update memory link
│   └── templates/            AGENTS.md BOOTSTRAP.md SOUL.md IDENTITY.md USER.md MEMORY.md
│                             AGENTS.local.md hub.toml _gitignore cron/ skills/hub-*/
├── tests/unit/  tests/integration/
├── docs/                     install.md cc-connect.md windows.md acceptance.md superpowers/
└── .github/workflows/        ci.yml release.yml
```

### 10.2 测试

- 单元测试测纯函数：总站定位、清单与模板一致、模板渲染、记忆日志与检索、`hub.toml` 原地编辑、尾部保留的三种情况。
- 集成测试用 typer 的 CliRunner 或子进程真跑命令，在临时目录里，路径带中文和空格：`init` 后 `doctor` 只剩 `bootstrap-pending`；`update` 备份并覆盖框架文件，用户文件不动，`BOOTSTRAP.md` 删除后不重建，退役文件被备份并删除，`AGENTS.md` 尾部保留；`link` 为每个 skill 建链接、重复运行不变、删除失效链接、不碰别的项；`doctor` 按 skill 报告缺失和失效的链接。
- 模板检查：`AGENTS.md` ≤ 150 行并以分界标记结尾；每个 `SKILL.md` ≤ 100 行、frontmatter 合法且 `name` 与目录名一致；全部 LF、无 BOM；README 提到每个命令。
- CI 矩阵：ubuntu、macos、windows × Python 3.11、3.12；ruff；pytest；`uv build` 后用 wheel 跑 `version`、`init`、`doctor --json` 冒烟。
- 端到端不自动化，写成 `docs/acceptance.md` 手工验收清单。

### 10.3 发布

- 语义化版本；`template_version` 即包版本。
- `CHANGELOG.md` 每个版本一节，有需要时附迁移说明；`doctor` 发现版本落后时提示去看。
- 推送 `v*` 标签触发 release 工作流：测试、`uv build`、建 GitHub release 并附上构建产物；仓库变量 `PUBLISH_PYPI` 为 `true` 时用 trusted publishing 发布到 PyPI。

## 11. 错误处理

- json 和 toml 一律原子写。
- 找不到总站退出 1，并说明四种定位方式。
- `update` 覆盖前必备份；备份失败则中止，不做任何修改。
- `doctor` 中某个文件不可读或格式错误，只让对应检查失败。
- 命令出错时 typer 不打印局部变量，避免把总站内容带进回溯。

## 12. 手工验收清单（docs/acceptance.md）

环境：WSL2，cc-connect 以后台服务运行，Claude Code 作为 agent，一个 IM 平台。

1. 在普通终端 `uv tool install cc-hub`，`cc-hub init`，`cc-hub doctor`：除 `bootstrap-pending` 外全绿。
2. 配置 cc-connect 的 `work_dir` 和 `env.PATH`，重启 cc-connect。
3. 发第一条消息，agent 执行 bootstrap：问名字，写 `IDENTITY.md`、`USER.md`，跑 `hub-adapt`，注册 cron 任务，删除 `BOOTSTRAP.md`。
4. `cc-hub doctor` 全绿。
5. 让 agent 记一件事：`memory/` 出现今天的文件，`cc-hub memory search` 能找到。
6. 换成 Codex 的 bot，在聊天里发 `/cron setup`：`AGENTS.md` 末尾出现 cc-connect 块。
7. 把包版本号提高后跑 `cc-hub update`：`AGENTS.md` 分界标记以上更新、以下（含 cc-connect 块）不变，`SOUL.md`、`USER.md`、`memory/` 不变，`.cc-hub/backups/` 里有旧版本。
