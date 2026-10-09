# cc-hub 设计规格

适用版本：0.4.0

---

## 1. 定位

一个聊天驱动的编码 agent 由三部分组成：

| 部分 | 职责 | 在 OpenClaw 里对应 | 在这里 |
|---|---|---|---|
| 聊天 | 用户在 IM 里和 agent 对话 | channels | bot（飞书、微信、Telegram 等） |
| 连接本地 | 会话、路由、审批转发、附件收发、定时调度，以及向 agent 说明这些能力怎么用 | Gateway | [cc-connect](https://github.com/chenhg5/cc-connect) |
| 本地目录 | agent 的家：人格、记忆、规程、skills | [workspace](https://docs.openclaw.ai/concepts/agent-workspace) | **cc-hub** |

cc-connect 在配置的 `work_dir` 里启动 agent（Claude Code、Codex 等）。cc-hub 把这个目录变成 agent 的 workspace，称为**总站**，并提供一个小工具负责它的播种、体检和升级。

cc-hub 的职责有三件：

1. **把东西放在约定的位置**：人格、用户信息、记忆、规程、skills、定时任务定义，文件格式沿用 OpenClaw workspace 的约定（`AGENTS.md`、`SOUL.md`、`IDENTITY.md`、`USER.md`、`BOOTSTRAP.md`、`MEMORY.md`、`memory/`、`skills/`）。
2. **让 agent 读得到**：OpenClaw 的 Gateway 会把 workspace 文件注入会话，cc-connect 不做这件事。所以总站顺着各 agent 生态的惯例（原生读 `AGENTS.md`、`CLAUDE.md` 导入、skills 发现路径），让 agent 自己读到这些文件。
3. **让总站能扩展**：记账、机器管理这类能力以**应用**的形式装进总站。应用是一个文件夹，里面是教 agent 使用某个软件的 skills、定时任务定义、数据骨架和设置步骤；应用放在 git 仓库（**tap**）里分发。cc-hub 提供登记 tap 和安装、升级、卸载应用的机制，自己不带任何应用。

执行命令和权限属于 agent 运行时；会话、调度、附件和审批属于 cc-connect。总站里除框架文件和应用以外放什么，由用户和 agent 自己决定。

## 2. 原则

- 开源，MIT，跨平台：Linux、macOS、Windows、WSL2。
- **agent 无关**：总站不带任何 agent 专属文件。指向总站的指针由 agent 首次运行时按自己的生态生成（`hub-adapt`）。
- **bot 无关**：几个 bot、几个 agent、谁连谁，都是 cc-connect 的配置。
- **框架可升级，用户文件永不被覆盖**：所有权按清单判定，`update` 只碰清单里的框架文件；应用命令只碰应用自己的目录。
- **只搬文件，不执行**：cc-hub 对应用只做复制、链接和读取 `app.toml`。应用里的指令、脚本和安装命令只由 agent 执行，执行安装命令要经用户批准。
- **先看后做**：安装、升级、卸载应用都分两步，先打印将要发生的事，确认后加 `--yes` 才执行。
- **可回滚、可迁移**：总站是 git 仓库，谁改谁提交；应用代码不进总站的 git，换机器时按 `apps.lock` 恢复。
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
├── apps/<name>/            应用              已安装的应用，不进 git（§8）
├── apps.lock               cc-hub 维护       已登记的 tap 和已安装的应用，进 git
├── <数据目录>/             用户              应用声明的数据目录，如 ledger/；安装时播种，之后归用户
├── hub.toml                框架管结构        值归用户；update 只合并新键和改版本号
├── .gitignore              框架
├── .cc-hub/                派生              backups/、taps/、apps-state.toml、临时目录、锁文件
├── .cc-connect/            派生              cc-connect 自己建的附件目录
└── CLAUDE.md .claude/ .agents/ .codex/   派生   agent 按自身生态生成的指针
```

`.gitignore` 忽略凭据（`.env`、`.env.*`，`.env.example` 除外；`secrets/`）、`apps/`、`.cc-hub/`、`.cc-connect/` 和 agent 指针。

四条规则：

1. **所有权按清单，不按目录。** `manifest.py` 列出框架拥有的相对路径。用户在 `skills/`、`cron/` 下新建的文件不在清单里，永远不被碰。应用的文件也不在清单里：`apps/<name>/` 整个目录归该应用，由 `cc-hub app` 管理；`apps.lock` 只由 `tap`、`app` 命令写。
2. **一次性仪式和可重复适配分开。** `BOOTSTRAP.md` 只做一次的事；生成指针、登记默认定时任务是可重复的 `hub-adapt` skill，`BOOTSTRAP.md` 调用它，`AGENTS.md` 要求指针缺失时再跑。
3. **总站在所有代码仓库之外。** Claude Code 会加载所有父目录的 `CLAUDE.md`，auto-memory 也按仓库挂载，所以 `init` 拒绝在 git 仓库内或已有仓库的根目录播种。`init` 默认在总站里 `git init` 并做初始提交，`--no-git` 关闭。
4. **应用的代码和数据分开。** 应用目录随升级整体替换；用户的数据和个人设置放在应用声明的数据目录里，升级和卸载都不碰。

## 4. 核心文件

### 4.1 AGENTS.md（框架，保留尾部，≤ 150 行）

唯一常驻的规程。各节顺序就是 agent 每次会话的执行顺序：

1. **你在哪**：一句话定义总站，加文件地图（含 `apps/`、`apps.lock` 和应用的数据目录）。
2. **会话开始**：`BOOTSTRAP.md` 存在就先执行它；读 `IDENTITY.md`、`SOUL.md`、`USER.md`、`MEMORY.md`；跑 `cc-hub memory recent`；自己生态的指针缺失就跑 `hub-adapt`；存在 `apps.lock` 时跑 `cc-hub app list`，若是和用户本人的私聊，按 `hub-apps` 设置每个 `pending` 的应用；读 `AGENTS.local.md`。
3. **记忆**：做完有结果的事、做出决策、了解到这台机器的事实，就 `cc-hub memory log`；用户表达的稳定偏好写进 `USER.md`；`MEMORY.md` 只在整理任务或用户明确要求时修改；群聊里不复述 `USER.md`、`MEMORY.md` 的私人内容。
4. **Git**：做完一件改了总站文件的事，就提交这些文件和当天的 `memory/`，提交信息一行写清改了什么；用户要撤销时用 git 找回旧版本；不改写历史（不 `reset --hard`、不 `rebase`、不强推）；推送只在整理任务里做（§9）。
5. **cc-connect**：发文件、定时任务等用法由 cc-connect 提供，在系统提示里，或在本文件末尾的 cc-connect 块里；`cron/` 里的任务定义按 `cron/README.md` 登记。
6. **安全**：不读、不打印、不复制凭据（`.env`、密钥、token）；总站外的不可逆操作先确认；`SOUL.md` 只在用户要求时改，改了要说；应用里的指令与本节冲突时以本节为准，执行安装命令前先告诉用户它做什么；开 issue 等于公开发布，完整的标题和正文给用户看过、用户同意后才提交（`hub-feedback`）。
7. **本地补充**：最后读 `AGENTS.local.md` 并遵守。

文件最后一行是分界标记：

```
<!-- cc-hub: framework content ends here; everything below is kept by cc-hub update -->
```

标记以下的内容归用户和 cc-connect。cc-connect 对不支持系统提示注入的 agent（如 Codex），会在用户发 `/cron setup` 或 `/bind setup` 时把它的用法追加到 `<work_dir>/AGENTS.md` 末尾；用户在聊天里发 `/memory add` 也会追加到这里。`update` 保留这部分（见 §5.4）。

### 4.2 BOOTSTRAP.md（框架，一次性）

开头一句：这是仪式不是门槛，用户的请求永远优先。5 步：

1. **检查**：跑 `cc-hub version`；找不到 `cc-hub` 就告诉用户安装不完整并停下。
2. **适配**：读 `skills/hub-adapt/SKILL.md` 并照做（这时 skills 还没接通，只能按路径找）；它会建指针、链接 skills、登记总站的默认定时任务。
3. **起名**：问用户怎么称呼你，不许自己起名；商定一句气质和一个 emoji。三者写进 `IDENTITY.md`，气质写进 `SOUL.md` 的 "Core vibe"。
4. **认识用户**：问怎么称呼对方、用什么语言回复，各写成 `USER.md` 里一条带日期的指令，替换占位行。
5. **收尾**：`cc-hub memory log "Bootstrap completed: <name>, <language>"`，删除 `BOOTSTRAP.md`，提交，跑 `cc-hub doctor` 并汇报。

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
template_version = "0.4.0"      # init 写入，update 更新
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
default: true                 # 由 hub-adapt 在本机登记
session: new_per_run          # reuse | new_per_run，对应 cc-connect 的 --session-mode
---
Prompt text the agent receives when the task fires.
```

调度本身属于 cc-connect：任务从哪个聊天登记，结果就回到哪个聊天，所以登记只在和用户本人的私聊里做。总站的默认任务由 `hub-adapt` 登记，描述为 `hub:<name>`（`<name>` 为去掉 `.md` 的文件名）：

```
cc-connect cron add --cron "<schedule>" --prompt "<body>" --session-mode <session> --desc "hub:<name>"
```

应用的任务定义放在 `apps/<app>/cron/<task>.md`，格式相同，描述为 `hub:<app>/<task>`，由 `hub-apps` 在设置应用时登记（§8.5）。

内置 `cron/memory-consolidate.md`，每天 03:00，`new_per_run`，执行 `hub-memory` 的整理流程并汇报是否已推送。`cron/README.md` 说明格式和登记命令。

## 5. CLI

命令：`init`、`doctor`、`update`、`memory log|search|recent`、`link`、`tap add|list|remove`、`app search|install|list|update|remove|sync|setup-state`、`feedback`、`where`、`version`。

### 5.1 通用约定

- **定位总站**，按顺序：`--hub <path>`、环境变量 `CC_HUB_DIR`、从当前目录向上找 `hub.toml`、`~/.cc-hub`（存在 `hub.toml` 时）。找不到退出 1，并列出这四种方式。
- **输出**：给 agent 读的命令（`memory`、`link`、`tap`、`app`、`feedback`）输出纯文本，查询类命令支持 `--json`。给人看的 `init`、`doctor`、`update` 用 rich 表格。错误写 stderr，退出 1。
- **依赖**：typer、rich、tomli-w。Python ≥ 3.11（`tomllib` 在标准库）。git 命令行用于总站提交和 tap。
- **写文件**：一律先写同目录临时文件再 `os.replace`。
- **提交**：总站是 git 仓库时，改动总站的命令只提交自己改的路径（`git commit -- <路径>`），提交信息以 `cc-hub: ` 开头（§9）。提交失败（没有 git 身份、索引被别的进程锁住）只打印警告，命令照常成功；遇到索引锁时重试一次。
- **互斥**：同一时间只允许一个 `tap` 或 `app` 命令修改总站，用 `.cc-hub/` 下的锁文件实现；另一个直接报错退出，提示稍后重试。

### 5.2 init

`init [dir] [--name NAME] [--git/--no-git]`

- `dir` 默认 `~/.cc-hub`；拒绝 git 仓库内的目录，以及没有 `hub.toml` 的仓库根目录。
- 只创建缺失的文件和目录（`memory/`、`scripts/`），已存在的一律不碰。
- `hub.toml` 的 `template_version` 写包版本。
- 默认 `git init` 并提交所有不被忽略的文件（`cc-hub: init`）。本机没有任何 git 身份（`user.name`、`user.email`）时，只在总站仓库里设置 `<总站名> (cc-hub)` 和 `hub@cc-hub.invalid`。
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
| pointers | 对本机装了的、且已在总站里设置过的 agent，检查指令文件和每个 skill 的链接，包括已安装应用的 skills（见 §7） |
| apps | `apps.lock` 可解析（否则 fail）；记录里的应用都在 `apps/` 下（缺了提示 `cc-hub app sync`）；链接安装的源目录存在；cc-hub 版本满足各应用的 `min_hub`；`requires` 里的可执行文件在 PATH 上（缺了给出本平台的安装命令）；有 `pending` 或 `waiting` 的应用 |
| git | 总站是 git 仓库、有可用的 git 身份、没有未提交的改动、配置了远程（没有远程就没有备份）；只报 warn |
| nested-git | 总站是否在别的 git 仓库内 |

`--fix` 只做安全、不联网的事：重写 `.gitignore`、补建 `memory/` 和 `scripts/`、补建缺失的用户文件，并提交（`cc-hub: doctor --fix`）。指针不由它生成，`app sync` 也不由它跑。

### 5.4 update

`update [--dry-run]`

- 把清单里的框架文件更新到当前包的模板。被改动的旧文件先备份到 `.cc-hub/backups/<旧版本>/`；备份失败则整个 update 中止，什么都不改。
- 一次性文件（`BOOTSTRAP.md`）已不存在就不重建。
- 包里已不再提供的框架文件：备份后删除，目录空了一并删除。
- **保留尾部**：清单里标为保留尾部的文件（`AGENTS.md`）只替换分界标记及以上的部分，标记以下原样接回。文件里没有分界标记、但有 cc-connect 的 `<!-- cc-connect-instructions -->` 时，从该标记起保留到文件末尾；两者都没有则整份替换。替换后与原文件相同的算作未改动。
- `hub.toml`：用模板默认值补齐缺失的表和键，已有的值不覆盖；`template_version` 改为包版本。原地编辑，保留用户的注释和排版；无法原地编辑时退回整份重写。
- `apps.lock`、`apps/` 和数据目录不在清单里，update 不碰。
- 提交：总站仓库还没有任何提交时，先提交所有不被忽略的文件（`cc-hub: init`）；再提交本次改动和删除的框架文件与 `hub.toml`（`cc-hub: update <旧版本> -> <新版本>`）。
- 打印每个文件的状态：updated、unchanged、not present (one-time)、removed (retired)。

### 5.5 memory

- `memory log "<text>"`：追加到今天的日志；文件不存在先写标题行。不提交，改动随 agent 的下一次提交进入 git。
- `memory search <query> [--days N] [--limit N] [--regex] [--json]`：搜 `MEMORY.md` 和 `memory/*.md`，按日期倒序，忽略大小写，忽略 HTML 注释（模板说明、观察日期），每条命中带下一行作上下文。默认最多 50 条。
- `memory recent [--days N]`：按日期倒序打印最近 N 天的日志，默认取 `hub.toml` 的 `memory.recent_days`。

### 5.6 link

`link <skills-dir>`，把总站的每个 skill 链接进一个 agent 的 skills 目录；`<skills-dir>` 相对路径以总站为基准，不存在就创建。总站的 skill 包括 `skills/` 下每个含 `SKILL.md` 的子目录，以及 `apps.lock` 里每个已安装应用的 `apps/<app>/skills/` 下的同类子目录。

- 每个 skill 一个目录链接：`<skills-dir>/<name>` → 该 skill 的目录。Linux、macOS 用 symlink，Windows 用 junction。链接建不出来就报错退出。
- 已经指向对应 skill 的项报 `existing`；新建的报 `linked`；指向 `skills/` 或 `apps/` 下已不存在的 skill 的链接删除并报 `removed`；同名但不是指向该 skill 的项不碰，报 `blocked`，命令退出 1。
- 不是总站 skill 的其它项（agent 自己生态里的 skill 等）不碰。
- 每行输出状态和 skill 名，用制表符分隔。重复运行结果不变；新增或删除 skill 后再跑一次。`app` 命令结束时会自己对已存在的 skills 目录重跑。

### 5.7 tap

```
cc-hub tap add https://github.com/you/hub-apps
cc-hub tap add ~/dev/hub-apps --name my-apps
cc-hub tap list
cc-hub tap remove my-apps
```

`tap add <source> [--name NAME]`

- `<source>` 是一个 git 仓库：远程地址（https、ssh），或本机上一个仓库的路径。远程仓库克隆到 `.cc-hub/taps/<name>/`（`git clone --no-recurse-submodules -- <地址>`）；本地仓库不克隆，直接读它的提交。
- 名字默认取仓库目录名（去掉 `.git`），须符合命名规则（§8.2），不与已登记的 tap 重名。
- 写入 `apps.lock` 并提交（`cc-hub: tap add <name>`）。

`tap list [--json]`：名字、地址或路径、其中的应用数。

`tap remove <name>`：还有已安装的应用来自它时拒绝并列出这些应用；否则删除本地克隆、从 `apps.lock` 移除并提交（`cc-hub: tap remove <name>`）。

### 5.8 app

```
cc-hub app search ledger
cc-hub app install hub-apps/ledger
cc-hub app install hub-apps/ledger --ref 3f2a9c1 --yes
cc-hub app install ~/dev/hub-apps/machines --link --yes
cc-hub app list
cc-hub app update ledger
cc-hub app remove ledger
cc-hub app setup-state ledger waiting --note "user installs beancount"
```

`app search [words] [--json]`：列出各 tap 里的应用：`<tap>/<app>`、版本、描述、是否已安装。远程 tap 读本地克隆里默认分支的最新提交，本地 tap 读仓库的 `HEAD`。不联网。

`app install <tap>/<app> [--ref REF] [--yes]`

- 不带 `--yes`：拉取远程 tap，把 REF（默认是默认分支的最新提交）解析成 commit，读取该 commit 下的应用并校验（§8.3），打印概览后退出，不改动总站。概览包括：来源和 commit、版本、描述、数据目录、`requires` 及本平台的安装命令、`scripts/` 清单、定时任务及其时间、有没有 `SETUP.md` 和 `REMOVE.md`；最后一行是确认用的完整命令，带 `--ref <commit> --yes`。
- 带 `--yes`：不再拉取，按 REF（没给时用本地克隆当前的默认分支）安装（§8.4）。

`app install <path> --link [--yes]`：从本机一个含 `app.toml` 的目录安装，`apps/<app>` 是指向它的目录链接，改动即时生效，用于开发自己的应用；概览和确认同上。路径不带 `--link` 时报错，并提示把所在仓库登记成 tap。

`app list [--json]`：每个已安装应用的名字、版本、来源（`<tap>@<commit 前 7 位>` 或链接路径）、本机的设置状态（`pending` / `waiting` / `done`，`waiting` 带说明）、缺少的依赖及本平台的安装命令、本地克隆里是否有更新的提交。不联网。

`app update <name>|--all [--ref REF] [--yes]`

- 不带 `--yes`：拉取 tap，列出从已安装 commit 到新 commit 之间应用目录里改动的文件；`app.toml`、`SETUP.md`、`REMOVE.md`、`skills/`、`scripts/`、`cron/` 下的改动给出完整 diff，新增的 `requires` 单独列出；同时列出 `apps/<name>/` 里与已安装 commit 不一致的文件（本地改动）。最后一行是确认用的完整命令。不改动总站。
- 带 `--yes`：不再拉取，执行升级（§8.6）。
- 链接安装的应用跳过并说明。

`app remove <name> [--yes]`

- 不带 `--yes`：打印将删除的目录、保留的数据目录、要注销的定时任务（`hub:<name>/*`）、`requires` 里的软件，以及 `REMOVE.md` 的全文（有的话）。
- 带 `--yes`：执行卸载（§8.7）。

`app sync`：让 `apps/` 与 `apps.lock` 一致。克隆缺少的 tap，按记录的 commit 安装缺少的应用，链接安装的重建链接（源目录不存在就报告），然后对已存在的 skills 目录重新链接。不升级，不播种（数据目录已在总站的 git 里），不需要确认，不提交（它不改动进 git 的文件）。`apps/` 下不在记录里的目录只报告不删除。单个应用失败不影响其它应用。

`app setup-state <name> done|waiting [--note TEXT]`：记录本机上该应用的设置状态（§8.5）。

### 5.9 feedback

`feedback [--app NAME] [--json]`：打印反馈去处和一段环境信息，不发送任何东西（§10）。`--json` 输出 `target`（issue 列表地址或 null）、`new_issue_url`、`github_repo`（`owner/repo` 或 null）、`environment`。

### 5.10 where / version

`where` 打印总站根目录和包的安装位置；找不到总站时仍打印包位置，退出 1。`version` 打印包版本。

## 6. 内置 skills

四个，框架拥有，`hub-` 前缀，符合 Agent Skills 规范的 `SKILL.md`，每个 ≤ 100 行，英文。

| skill | 触发场景 | 内容 |
|---|---|---|
| `hub-adapt` | 首次运行、换 agent、换机器、增删 skill 后、`doctor` 报指针缺失 | 见 §7 |
| `hub-memory` | 记东西、找东西、整理记忆 | 何时 `memory log`；`memory search`、`memory recent` 用法；整理流程 |
| `hub-apps` | 找、装、设置、升级、卸载应用；编写应用 | 见 §8；编写指南放在同目录的 `authoring.md`，也归框架 |
| `hub-feedback` | cc-hub 或某个应用出了问题，或用户有建议 | 见 §10 |

`hub-memory` 的整理流程：读近 7 天日志；把仍然成立、跨天有用的条目并入 `MEMORY.md` 四节；超预算时合并同类、删去被后来条目推翻或已不成立的条目；`USER.md` 里被新观察取代的行标 `superseded`；写一条 memory log 记录本次整理；提交；总站配置了远程就 `git push`，推送失败时记一条 memory log 并在汇报里说明，不自动拉取或合并。任何记忆文件里都不写凭据。

## 7. hub-adapt 与生态路由

总站是指令（`AGENTS.md`）和 skills（`skills/<name>/` 与已安装应用的 skills）的唯一事实源，各生态通过指针到达它们。agent 知道自己是谁、自己的生态在哪里找指令和 skills；`hub-adapt` 列目标，agent 按参考表落到具体文件。每一步幂等，重跑无副作用。

目标：

1. **指令**：生态有自己的指令文件，就建它，内容只有导入 `AGENTS.md` 的一行；只读 `AGENTS.md` 的生态什么都不用做。
2. **skills**：运行 `cc-hub link <自己的 skills 目录>`（§5.6），总站和已安装应用的 skills 一并链接。skills 靠 frontmatter 被发现、正文按需加载，每个 skill 一个目录链接能让 frontmatter、正文和辅助文件都从总站读到。新 skill 一律建在 `skills/<name>/`，增删 skill 后重跑。本次会话开始时 skills 目录还不存在的话，运行时可能要重新加载或开新会话才看得到，告诉用户。
3. **信任**：运行时若需要一次交互式信任才读这个目录的指令或 skills，明确告诉用户怎么做。
4. **定时任务**：只在和用户本人的私聊里做。跑 `cc-connect cron list`；`cron/` 下每个 `default: true` 且 `hub:<name>` 尚未登记的任务，按 §4.5 的命令登记。cc-connect 不可用就记一条 memory log 留待以后。应用的定时任务由 `hub-apps` 登记（§8.5）。

做完跑 `cc-hub doctor`，修好它报的问题，再写一条 memory log。

已知生态参考表（附在 skill 末尾，注明"可能过时，以官方文档为准"；`doctor` 的 `pointers` 和 `app` 命令重新链接时用同一张表）：

| 生态 | 指令指针 | skills 路径 | 信任 |
|---|---|---|---|
| Claude Code | `CLAUDE.md`，内容只有 `@AGENTS.md` | `.claude/skills`（重新加载：`/reload-skills`） | 读指令和 skills 不需要 |
| Codex CLI | 不需要，原生读 `AGENTS.md` | `.agents/skills` | Codex 要求时把目录标为 trusted |

Claude Code 只在没有 `CLAUDE.md` 时才读 `AGENTS.md`，而 cc-connect 的 `/memory add` 会创建 `CLAUDE.md` 并追加内容。所以 Claude Code 下一律建带导入行的 `CLAUDE.md`，之后追加的内容都在导入行下面。

`pointers` 检查：只评判已在总站里设置过的生态（指令文件或 skills 目录任一存在），本机装了但没在这里用过的 agent 不算问题。对设置过的生态，指令文件要存在且含 `@AGENTS.md`；总站和已安装应用的每个 skill 在该生态的 skills 目录里都要有指向它的链接，没有指向已删除 skill 的失效链接。

## 8. 应用

### 8.1 概念

- **应用**：一个含 `app.toml` 的目录，教 agent 用某个软件替用户做事。它不是可执行程序：大部分内容是给 agent 读的文字（skills、`SETUP.md`），软件本身（如 beancount、Fava）是装在机器上的普通程序。
- **tap**：放应用的 git 仓库，根目录下每个含 `app.toml` 的子目录是一个应用，子目录名即应用名。登记一个 tap 等于信任这个仓库。

### 8.2 应用的结构

```
ledger/                         tap 根目录下的子目录
├── app.toml                    必有
├── SETUP.md                    可选：本应用特有的设置步骤
├── REMOVE.md                   可选：卸载前要撤掉的东西（如服务）
├── skills/<name>/SKILL.md      可选：每个子目录一个 skill
├── cron/<task>.md              可选：定时任务定义，格式同 §4.5
├── scripts/                    可选：skills 和 SETUP 调用的脚本
└── seed/<数据目录>/…           可选：数据骨架，按总站相对路径摆放
```

`app.toml`：

```toml
[app]
name = "ledger"                 # 必填，等于目录名
version = "0.1.0"               # 必填，只用于显示
description = "Plain-text bookkeeping with beancount and Fava"   # 必填
min_hub = "0.4.0"               # 可选，需要的最低 cc-hub 版本
issues = "https://github.com/you/hub-apps/issues"   # 可选，反馈地址（§10）

[data]
dirs = ["ledger"]               # 可选，本应用的数据目录

[[requires]]                    # 可选，可多条
name = "beancount"
bin = "bean-check"              # 只检查它是否在 PATH 上，不执行
install = "uv tool install beancount"
```

`install` 是一个各平台通用的字符串，或按平台分开的表，缺某个平台时显示"本平台没有安装步骤"：

```toml
[[requires]]
name = "hledger"
bin = "hledger"

[requires.install]
linux = "sudo apt install hledger"
macos = "brew install hledger"
windows = "winget install hledger"
```

**命名规则**：应用名、skill 名、tap 名只用小写字母、数字和连字符，以字母或数字开头，最长 64 个字符，不以 `hub-` 开头。

**数据目录**：总站下的相对路径，不含 `..`；第一段不能是保留名（总站的框架文件和用户文件、`hub.toml`、`apps.lock`、`memory`、`skills`、`cron`、`scripts`、`apps`、`secrets`，以及任何以 `.` 开头的名字）；不能与别的应用的数据目录相同或互相包含。`seed/` 下的每个文件都必须落在本应用声明的某个数据目录里。

**设置和凭据**：个人设置（账户、币种等）放在数据目录里，比如 `ledger/config.toml`，skills 从那里读。数据目录进 git，所以凭据不放在那里，放 `.env` 或 `secrets/`。

### 8.3 校验

安装和升级前检查以下各项，任何一条不满足就拒绝并说明原因：

- `app.toml` 能解析，必填字段齐全，`name` 等于目录名；
- cc-hub 版本满足 `min_hub`；
- 应用名未被占用（升级时除外）；每个 skill 名与 `skills/` 和其它应用的 skills 都不重名；数据目录符合 §8.2；
- 应用目录在该 commit 下只含普通文件和目录，没有符号链接和子模块。

### 8.4 安装

`app install --yes`：

1. 在 `.cc-hub/` 下的临时目录里取出该 commit 下的应用目录（`git archive`，逐条检查路径），按 §8.3 校验；
2. 整体移到 `apps/<name>/`；
3. 把 `seed/` 里缺的文件复制进数据目录，已存在的不碰；
4. 写 `apps.lock`；
5. 对总站里已存在的 agent skills 目录（§7 参考表）重新链接；
6. 提交 `apps.lock` 和新播种的文件（`cc-hub: app install <name> (<tap>@<commit 前 7 位>)`）；
7. 打印缺少的依赖，以及"设置待执行"。

第 2 步之前失败，`apps/` 不变；之后的步骤失败就报告问题，`apps.lock` 与 `apps/` 保持一致，由 `doctor` 继续提示。

`apps.lock`：

```toml
[taps.hub-apps]
url = "https://github.com/you/hub-apps"

[taps.my-apps]
path = "~/dev/hub-apps"         # 本地 tap

[apps.ledger]
tap = "hub-apps"
commit = "3f2a9c1e07b4…"        # 完整哈希
version = "0.1.0"

[apps.machines]
link = "~/dev/hub-apps/machines"   # 链接安装
```

路径里的家目录写成 `~`，换机器时照样能用。

### 8.5 设置

设置状态按机器记录在 `.cc-hub/apps-state.toml`，不进 git：

- **pending**：本机没有记录，或记录的设置指纹与当前不同；
- **waiting**：设置做到一半，剩下的要用户自己做，附说明；
- **done**：设置完成，记录当时的指纹。

设置指纹是 `SETUP.md`、`app.toml` 的 `requires` 和 `cron/` 下全部任务定义合起来的哈希，其中任何一项变了，应用就回到 `pending`。

`hub-apps` 规定的设置流程由 agent 执行，只在和用户本人的私聊里做（要问问题、要批准、会写入私人信息）；每一步先检查再做，可以重复执行：

1. **依赖**：`cc-hub app list --json` 给出缺少的依赖和本平台的安装命令。告诉用户每条命令做什么，请求批准；批准就执行并再查一遍；不批准或做不到（例如需要 sudo）就把步骤列给用户，执行 `cc-hub app setup-state <name> waiting --note "<还差什么>"` 并停下。
2. **应用自己的步骤**：照 `SETUP.md` 做，例如问用户的账户和币种并写进数据目录，按用户的意愿配置服务。
3. **定时任务**：`cc-connect cron list` 里还没有的 `hub:<name>/<task>`，对 `default: true` 的任务按 §4.5 的命令登记，描述为 `hub:<name>/<task>`。
4. **收尾**：`cc-hub app setup-state <name> done`，提交数据目录的改动，写一条 memory log。

`waiting` 的应用不在会话开始时自动重跑；用户说已经做好，或 `app list` 显示缺的依赖已经出现，agent 再跑一遍。

### 8.6 升级

`app update --yes`：

1. 把 `apps/<name>/` 备份到 `.cc-hub/backups/apps/<name>/<旧 commit 前 7 位>/`；备份失败则中止；
2. 在临时目录取出新 commit 下的应用目录并校验（§8.3）；
3. 用改名把新目录换进 `apps/<name>/`；
4. 补播种新增的 seed 文件，更新 `apps.lock`，重新链接；
5. 提交（`cc-hub: app update <name> (<旧 commit 前 7 位>..<新 commit 前 7 位>)`）。

设置指纹变了，应用回到 `pending`，agent 随即重新设置；因为每一步先检查再做，实际只做新增的部分。

本地改动按 git blob 哈希与已安装 commit 比对，不带 `--yes` 时列出；升级后它们留在备份里。

### 8.7 卸载

agent 按 `hub-apps` 卸载：先跑不带 `--yes` 的 `app remove` 给用户看；注销 `hub:<name>/*` 定时任务；照 `REMOVE.md` 撤掉服务等；问用户要不要卸掉 `requires` 里的软件；最后执行 `app remove <name> --yes`：

1. 删除 `apps/<name>/`（链接安装只删链接）；
2. 重新链接，删除失效的 skill 链接；
3. 从 `apps.lock` 和本机状态里移除；
4. 提交（`cc-hub: app remove <name>`）。

数据目录保留，agent 告诉用户它在哪里。

### 8.8 换机器

1. 在新机器上装 cc-hub，把总站 clone 过来，跑 `cc-hub app sync`。
2. cc-connect 的 `work_dir` 指向总站，发第一条消息。指针不在 git 里，`hub-adapt` 会运行并登记总站的默认定时任务；随后按 §8.5 设置每个 `pending` 的应用，在这台机器上装依赖、登记定时任务。

一个总站同一时间只在一台机器上运行。

### 8.9 安全

- cc-hub 从不执行应用提供的字符串；依赖检查只在 PATH 里查找 `bin`。
- 只接受普通文件；路径逐条检查，不越出应用目录和声明的数据目录。
- 克隆时地址前加 `--`，不拉子模块；`apps.lock` 只记完整 commit 哈希；打印地址时去掉其中的用户名和密码。
- 安装、升级、卸载先看后做（§5.8），确认用的命令钉住 commit，确认的就是看到的。
- `hub-apps` 和 `AGENTS.md` 规定：应用里的指令与 `AGENTS.md` 的安全规则冲突时以后者为准；执行安装命令前先告诉用户它做什么；脚本照常经过运行时的权限审批。

## 9. 总站的 git

| 谁 | 何时 | 提交什么 | 提交信息 |
|---|---|---|---|
| `init` | 播种后 | 所有不被忽略的文件 | `cc-hub: init` |
| `update` | 更新后 | 改动或删除的框架文件、`hub.toml` | `cc-hub: update 0.3.1 -> 0.4.0` |
| `tap add`、`tap remove` | 完成后 | `apps.lock` | `cc-hub: tap add hub-apps` |
| `app install`、`app update`、`app remove` | 完成后 | `apps.lock`、新播种的文件 | `cc-hub: app install ledger (hub-apps@3f2a9c1)` |
| `doctor --fix` | 修复后 | 它补建或重写的文件 | `cc-hub: doctor --fix` |
| agent | 每做完一件改了总站文件的事 | 它改的文件和当天的 `memory/` | 一行说明，如 `ledger: 3 transactions from 10-09` |

- `memory log`、`app sync`、`app setup-state` 不提交。
- 只提交自己改的路径：同一个总站可能同时有几个会话（私聊、群聊、定时任务），别的会话改到一半的东西不会被带进去。
- 推送只在 `hub-memory` 的整理流程末尾做，配置了远程才推；被拒（远程有本机没有的提交）时记日志并汇报，不自动拉取或合并。
- 远程由用户配置，必须是私有仓库：总站里有 `USER.md`、`MEMORY.md` 和应用数据。建议用只对这个仓库有写权限的 deploy key（`docs/backup.md`）。

## 10. 反馈

agent 发现 cc-hub 或某个应用的问题，或用户有建议时，按 `hub-feedback` 帮用户到对应的仓库开 issue。

**去处**，由 `cc-hub feedback` 打印：

- cc-hub 本身：包元数据里的 `Issues` 地址，来自 `pyproject.toml` 的 `[project.urls]`。
- 应用（`--app NAME`）：`app.toml` 的 `issues`；没写时，tap 是 GitHub 仓库（https 或 ssh 地址）就推出 `https://github.com/<owner>/<repo>/issues`；本地 tap 和链接安装的应用没有去处，提示这是用户自己的应用。
- cc-connect、agent 运行时、应用所用的软件（如 beancount）的问题不属于这两处；agent 告诉用户该找哪个项目，不往 cc-hub 或应用的仓库里提。

**环境信息**：cc-hub 版本、Python 版本、操作系统和架构、总站里设置过的 agent 生态；带 `--app` 时加上应用的名字、版本、tap 地址和 commit、设置状态。不含总站路径、用户名和主机名，地址去掉凭据。

**`hub-feedback` 的流程**：

1. 判断归属：cc-hub、哪个应用，或者都不是。
2. 去处是 GitHub 仓库且 `gh` 已登录时，先搜已有 issue（`gh issue list -R <owner/repo> --search "<关键词>" --state all`）；有相同的就给用户看，建议补充评论而不是新开。
3. 起草：标题一行；问题写现象、复现步骤、期望和实际结果，附 `cc-hub feedback` 的环境信息；建议写想要什么、为什么。
4. 去掉隐私：不放 `USER.md`、`MEMORY.md`、日志和数据目录的内容，不放凭据、主机名、IP、带用户名的路径；报错输出只摘必要的几行。
5. 把完整的标题和正文给用户看，用户同意后才提交：`gh` 可用就 `gh issue create -R <owner/repo> --title <标题> --body-file <文件>`；否则把新建 issue 的链接和正文交给用户自己提交。
6. 提交后写一条 memory log，带上 issue 地址。

定时任务和群聊里只起草并记进 memory log，不提交。

## 11. 与 cc-connect 的配合

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
- cc-connect 以后台服务运行时不读 shell 配置，PATH 往往只有系统目录；在 `[projects.agent.options.env]` 里给 agent 进程设完整 PATH，`cc-hub` 和应用依赖的软件才找得到。
- cc-connect 自己向 agent 说明发文件、定时、中继等用法：对 Claude Code 通过 `--append-system-prompt` 注入；对 Codex 等不支持注入的 agent，用户在聊天里发一次 `/cron setup`，cc-connect 把说明追加到总站 `AGENTS.md` 末尾，`update` 保留它。
- 定时任务的登记见 §4.5、§7 第 4 个目标和 §8.5。
- `/dir` 只对下一个会话生效；`work_dir` 保持指向总站。

## 12. 跨平台与编码规范

Python 代码：

- 所有文件读写显式 `encoding="utf-8"`，写入用 LF。应用文件按原样复制，不转换换行符。
- 路径一律 `pathlib`。
- 启动时把 stdout、stderr 重设为 UTF-8。
- 源码文件 UTF-8 无 BOM，首行 `# -*- coding: utf-8 -*-`。

平台：

- 仓库 `.gitattributes` 设 `* text=auto eol=lf`；模板全部 LF、无 BOM（有些 skill 加载器遇到 CRLF 会静默丢掉 frontmatter）。
- Windows 上建 symlink 需要开发者模式或管理员权限，所以 skill 链接和应用的链接安装都用 junction（目录连接点），不需要特殊权限。
- 给人看的表格由 rich 渲染；在旧版 Windows 控制台下 rich 自动换用能显示的边框，agent 读的是纯文本或 `--json`。
- WSL 下总站放 Linux 文件系统，不放 `/mnt/c`。
- Windows 上在普通终端安装 cc-hub，不在 Claude 桌面版内的 shell 里装：桌面版是 MSIX 打包应用，它的 shell 在 `%APPDATA%` 下新建的目录落在应用私有存储里，cc-connect 看不到。

## 13. 仓库、测试、发布

### 13.1 仓库布局

```
cc-hub/
├── pyproject.toml            name=cc-hub，python>=3.11，入口 cc-hub；依赖 typer、rich、tomli-w；
│                             [project.urls] 有 Homepage 和 Issues
├── README.md  README.zh-CN.md  LICENSE  CHANGELOG.md
├── .gitattributes            * text=auto eol=lf
├── src/cc_hub/
│   ├── cli.py                typer 分发，where、version
│   ├── console.py            定位总站、JSON 输出、rich console
│   ├── hub.py                定位总站、读写 hub.toml
│   ├── manifest.py           文件所有权清单、模板渲染
│   ├── platform.py           平台判断、目录链接（symlink / junction）
│   ├── encoding.py           UTF-8 读写、原子写、stdio
│   ├── gitops.py             总站的 git：是否仓库、身份、按路径提交、重试
│   ├── taps.py               克隆、拉取、解析 commit、列出应用、按 commit 取出应用目录
│   ├── apps.py               app.toml 解析与校验、apps.lock、本机设置状态、安装升级卸载
│   ├── commands/             init doctor update memory link tap app feedback
│   └── templates/            AGENTS.md BOOTSTRAP.md SOUL.md IDENTITY.md USER.md MEMORY.md
│                             AGENTS.local.md hub.toml _gitignore cron/
│                             skills/hub-adapt/ hub-memory/ hub-apps/ hub-feedback/
├── tests/unit/  tests/integration/
├── docs/                     install.md cc-connect.md windows.md apps.md backup.md
│                             acceptance.md superpowers/
└── .github/workflows/        ci.yml release.yml
```

`docs/apps.md` 是给人看的应用编写指南（`app.toml` 全部字段、`SETUP.md` 的写法、一个示例应用的骨架）；`docs/backup.md` 讲私有远程和 deploy key。

### 13.2 测试

- 单元测试测纯函数：总站定位、清单与模板一致、模板渲染、记忆日志与检索、`hub.toml` 原地编辑、尾部保留的三种情况；`app.toml` 校验（命名规则、保留名、路径越界、`min_hub`）；`apps.lock` 写入后读出不变；设置状态和指纹；按平台选安装命令；`link` 收集应用的 skills；`gitops` 在有其它已暂存和未暂存改动时只提交指定路径，以及没有身份、不是仓库的情况；`feedback` 从 https、ssh 和带凭据的地址推出 issue 地址，非 GitHub 地址没有去处，环境信息不含家目录。
- 集成测试用 typer 的 CliRunner 或子进程真跑命令，在临时目录里，路径带中文和空格；tap 是测试里现建的本地 git 仓库：
  - `init` 后有初始提交，`doctor` 只剩 `bootstrap-pending` 和 `git`（没有远程）；
  - `update` 备份并覆盖框架文件，用户文件不动，`BOOTSTRAP.md` 删除后不重建，退役文件被备份并删除，`AGENTS.md` 尾部保留，没有提交的仓库先做初始提交；
  - `link` 为每个 skill（含应用的）建链接、重复运行不变、删除失效链接、不碰别的项；`doctor` 按 skill 报告缺失和失效的链接；
  - `tap add` 本地路径和 `file://` 地址；
  - 安装先概览后 `--yes`，seed 不覆盖已有文件，skills 链接进 `.claude/skills`，重名、保留名、符号链接被拒；
  - 升级先 diff 后 `--yes`：有备份、目录被替换、指纹变化回到 `pending`、报告本地改动；
  - 卸载先计划后 `--yes`，数据保留；
  - 把总站 clone 到另一个临时目录后 `app sync`，应用回来并为 `pending`；
  - 提交信息正确，只提交自己的路径；`doctor` 的 `apps` 和 `git` 检查。
- 模板检查：`AGENTS.md` ≤ 150 行并以分界标记结尾；每个 `SKILL.md` ≤ 100 行、frontmatter 合法且 `name` 与目录名一致；全部 LF、无 BOM；README 提到每个命令。
- CI 矩阵：ubuntu、macos、windows × Python 3.11、3.12；ruff；pytest；`uv build` 后用 wheel 冒烟：`version`、`init`、`doctor --json`，以及对现建的测试 tap 跑 `tap add` 和 `app install --yes`。
- 端到端不自动化，写成 `docs/acceptance.md` 手工验收清单。

### 13.3 发布

- 语义化版本；`template_version` 即包版本。
- `CHANGELOG.md` 每个版本一节，有需要时附迁移说明；`doctor` 发现版本落后时提示去看。
- 推送 `v*` 标签触发 release 工作流：测试、`uv build`、建 GitHub release 并附上构建产物；仓库变量 `PUBLISH_PYPI` 为 `true` 时用 trusted publishing 发布到 PyPI。

## 14. 错误处理

- json 和 toml 一律原子写。
- 找不到总站退出 1，并说明四种定位方式。
- `update` 覆盖前必备份；备份失败则中止，不做任何修改。
- 应用的安装和升级先在临时目录准备好再整体换入；升级先备份，备份失败则中止。
- 拉取或克隆失败就报错，不改动总站；`app list`、`app search` 不联网。
- 找不到 git 时，`init` 不建仓库，`tap` 命令和从 tap 安装、升级应用报错退出。
- `app sync` 中单个应用失败（例如记录的 commit 在上游已不存在）只影响它自己。
- `apps.lock` 读不了时 `tap`、`app` 命令报错退出，`doctor` 的 `apps` 为 fail，其它检查照常。
- 提交失败只警告；同一时间只有一个 `tap` 或 `app` 命令修改总站。
- `doctor` 中某个文件不可读或格式错误，只让对应检查失败。
- 命令出错时 typer 不打印局部变量，避免把总站内容带进回溯。

## 15. 手工验收清单（docs/acceptance.md）

环境：WSL2，cc-connect 以后台服务运行，Claude Code 作为 agent，一个 IM 平台。

1. 在普通终端 `uv tool install cc-hub`，`cc-hub init`，`cc-hub doctor`：除 `bootstrap-pending` 和 `git`（没有远程）外全绿；`git log` 有一条 `cc-hub: init`。
2. 配置 cc-connect 的 `work_dir` 和 `env.PATH`，重启 cc-connect。
3. 发第一条消息，agent 执行 bootstrap：问名字，写 `IDENTITY.md`、`USER.md`，跑 `hub-adapt`（建指针、链接 skills、登记 `hub:memory-consolidate`），删除 `BOOTSTRAP.md` 并提交。
4. 给总站配置私有远程；`cc-hub doctor` 全绿。
5. 让 agent 记一件事：`memory/` 出现今天的文件，`cc-hub memory search` 能找到，事情做完后有一条提交。
6. 换成 Codex 的 bot，在聊天里发 `/cron setup`：`AGENTS.md` 末尾出现 cc-connect 块。
7. 把包版本号提高后跑 `cc-hub update`：`AGENTS.md` 分界标记以上更新、以下（含 cc-connect 块）不变，`SOUL.md`、`USER.md`、`memory/` 不变，`.cc-hub/backups/` 里有旧版本，有一条 `cc-hub: update` 提交。
8. 准备一个测试 tap，其中的应用带 `requires`、`cron/`、`seed/` 和 `SETUP.md`。在聊天里让 agent 安装：先给出概览，同意后安装；agent 请求批准安装依赖；登记 `hub:<app>/<task>`；`cc-hub app list` 显示 `done`。
9. 在 tap 里改 `SETUP.md` 并提交，让 agent 升级：先看到改动，同意后升级，设置重新执行。
10. 让 agent 卸载：先看到计划，定时任务被注销，数据目录保留。
11. 手动触发整理任务：远程出现新的提交。
12. 把总站 clone 到另一台机器，`cc-hub app sync`，配置 cc-connect 后发第一条消息：`hub-adapt` 登记默认定时任务，应用重新设置。
13. 让 agent 为一个 cc-hub 的问题起草 issue：给出完整的标题和正文，不含私人信息，同意后才提交。
