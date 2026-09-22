# 调研简报：cc-connect 总站（Agent Hub）设计前调研

日期：2026-09-22 · 范围：cc-connect、同类项目、Claude Code + Codex 机制、"操作机器"能力面与安全、发布形态

---

## 1. cc-connect 是什么，它对 work_dir 做了什么

- 仓库 `chenhg5/cc-connect`，Go 单二进制，MIT，1.56 万星，v1.5.0（2026-08）。把 Claude Code / Codex / Gemini / Cursor / OpenCode / Copilot / 任意 ACP agent 桥接到飞书、钉钉、Slack、Telegram、Discord、企微、微信、QQ、Matrix、LINE。
- **驱动方式**
  - Claude Code：每个会话一个**常驻进程**，`claude --output-format stream-json --input-format stream-json --permission-prompt-tool stdio`，可带 `--permission-mode`、`--resume`、`--append-system-prompt-file`、`--plugin-dir`、`--allowedTools`。进程的 cwd = `work_dir`。斜杠命令（/compact /clear /resume）透传 stdin。
  - Codex：默认 `codex exec ... --cd <work_dir> --sandbox workspace-write`，**每轮新进程**，用 thread id resume；可选 app-server 长连接。
- **配置**（TOML，`~/.cc-connect/config.toml`）：`[[projects]]` = 一个 agent + N 个平台；`[projects.agent.options] work_dir` 就是启动目录，默认 `"."`；`~` 展开是 9 月 21 日刚合入、尚未发版。
- **运行时切目录**：`/dir <path>`（管理员命令，只对**下一个**会话生效，带历史 `/dir 2`、`/dir -`）；`mode = "multi-workspace"` + `base_dir`，按频道名映射到 `base_dir/<channel>`。
- **文件进出**：收到的附件写到 `<work_dir>/.cc-connect/attachments/<msgid>/`，并在提示词后追加绝对路径；Agent 回传用 `cc-connect send --image|--file|--tts <绝对路径>`（50 MB 上限）。
- **权限**：`/mode default` 把每次工具审批转发到聊天（按钮 allow / deny / allow all）；`/mode yolo` 全自动；`/allow <tool>` 预放行。
- **定时/后台**：`/cron add <expr> "<prompt>"`、`/timer`、`[projects.heartbeat]`（在主会话里按间隔跑一段提示词）、webhook、生命周期 hook。
- **记忆文件**：`/memory` 查看编辑 CLAUDE.md / AGENTS.md；`/bind setup`、`/cron setup` 会把 cc-connect 自己的使用说明写进记忆文件。
- **自定义命令**：`[[projects.commands]]`，以及自动发现 agent `commands/` 目录下的 .md。
- **安装**：npm / brew / GitHub release（linux、darwin、windows × amd64、arm64）；`cc-connect daemon install` 支持 systemd / launchd / Windows 计划任务。
- **cc-connect 里没有的东西**：没有任何"总站 / workspace 模板 / 人格文件"概念，没有 examples 目录。它对 work_dir 唯一的约束就是 `.cc-connect/attachments/`。这正是我们要填的空。
- **相关坑**：Windows 上 `run_as_user` 不可用；#1426 用 junction 装的 skills 在原生 Windows 不可见（`GODEBUG=winsymlink=0` 绕过）；`/dir` 只影响下一会话；#859 `/memory` 看不到 Claude 的 auto-memory 目录。

## 2. 同类项目：可以直接借鉴的设计

### 2.1 OpenClaw workspace（你目录里那套文件名的出处）
- 位置 `~/.openclaw/workspace`（Windows `%USERPROFILE%\.openclaw`）。**硬性分离**：workspace 可进私有 git 仓库；配置、凭据、会话 sqlite 放 state dir，永不入库。
- 注入顺序：`AGENTS.md → SOUL.md → IDENTITY.md → USER.md → BOOTSTRAP.md（仅新 workspace） → MEMORY.md`。空文件跳过，超长截断并注入提示，缺必需文件注入"missing file"标记。**子 agent 只拿 AGENTS.md**（曾有 bug：BOOTSTRAP 在子 agent 里跑了，把身份抹掉）。
- 文件职责：
  - `AGENTS.md`：操作规程 + 怎么用记忆；`## Tools` 小节记环境/工具备注（原 TOOLS.md 已并入）。
  - `SOUL.md`：人格、语气、边界；"改了要告诉用户"。
  - `IDENTITY.md`：`- Name: / - Vibe: / - Emoji:` 行格式，工具可解析。
  - `USER.md`：指令式行 + `<!-- observed: 日期 | status: active -->`，过期的标记不删；4000 字符上限。
  - `MEMORY.md`：长期精选记忆，**只在主私聊会话注入，群聊不注入**。
  - `memory/YYYY-MM-DD.md`：日志，按需检索。
  - `BOOTSTRAP.md`：首次仪式（起名、气质、头像、推荐 skills、安全提示），完成后删除；一旦 SOUL/IDENTITY/USER 偏离模板或出现 memory/ 就自动清理。
  - **已废弃**：`HEARTBEAT.md`（迁到数据库 scratch，任务转 cron）、`TOOLS.md`（并入 AGENTS.md）。
- 预算：每文件 20000 字符，总计 60000。
- 记忆：压缩前"flush"轮；session-memory hook 落盘；夜间"dreaming" cron 提炼进 MEMORY.md；**没有自动删除**。
- Skills：AgentSkills 规范 SKILL.md，`metadata.openclaw` 里声明 `requires.bins / os / install`；优先级 workspace/skills > .agents/skills > ~/.agents/skills > 内置；每个 skill 约 24 token 常驻；第三方 skill 视为不可信代码。

### 2.2 其它
- **Hermes**（Python）：`~/.hermes`，SOUL.md 永不覆盖，MEMORY.md 2200 字符 / USER.md 1375 字符硬上限，只能通过 memory 工具写；代码与数据分离（`~/.hermes/hermes-agent` vs `~/.hermes`）；`hermes update`；Windows 自带便携 Git Bash。
- **nanobot / PicoClaw / ZeroClaw**：文件集与 OpenClaw 结构相同（PicoClaw 有 `migrate` 一比一拷贝）；nanobot 有 `memory/history.jsonl` + 2 小时 Dream + GitStore 追踪。
- **Letta MemFS**：git 作记忆底座，`system/{persona,human}.md` 常驻，`reference/` 按需，**文件树本身常驻做路标**，每次编辑一个 commit。
- **Agent OS / LifeOS**：`profiles/`（用户的，升级保留）vs `commands/ scripts/`（升级替换）；LifeOS 的 `USER/` 永不被安装器碰，settings 合并不覆盖。
- **kindomLee/openclaw-workspace-template**：`MEMORY_COMPACT.md`（约 200 token 每会话必载）、`.learnings/` 三次复现自动晋升、`scripts/ cron/ .claude/{hooks,skills}`。
- **@adiasg/agentsmd**：从"已提交的公共源 + 未跟踪的个人偏好 + 模板片段"重新生成 AGENTS.md，git hook 在 pull 后再生成——"公共骨架 vs 个人定制"的具体解法。
- **通用共识**：磁盘上的 Markdown 是唯一真相；小而精的常驻文件 + 带日期的日志 + 检索；硬预算；压缩前 flush；每个拥有人格 workspace 的运行时都是 **二进制/包 + onboard 播种到用户自有目录**，从不让用户 clone 模板仓库；播种一次后归用户所有，用 doctor 做迁移。

## 3. Claude Code vs Codex：总站能复用哪些机制

| 机制 | Claude Code | Codex CLI | 能否共享 |
|---|---|---|---|
| 指令文件 | `CLAUDE.md`（cwd 及**所有父目录**）；v2.1.277+ 只在没有任何 CLAUDE.md 时才读 `AGENTS.md`；支持 `@path` 导入 | `AGENTS.md`（git 根 → cwd，**不看父目录以上**，32 KiB 上限）；无导入 | **内容共享**：总站根放 `AGENTS.md`，再放一个 `CLAUDE.md` 内容为 `@AGENTS.md`（Windows 安全，官方推荐，别用 symlink） |
| Skills | `.claude/skills/`、`~/.claude/skills/`；**不读** `.agents/skills` | `.agents/skills/`、`~/.agents/skills/` | **SKILL.md 格式共享**，目录不同 → 两个目录都放（复制或 junction） |
| 斜杠命令 | `.claude/commands/*.md`（已等同 skills） | `~/.codex/prompts/`（已废弃，转 skills） | 用 skills 覆盖两者 |
| Hooks | settings.json `hooks`，33 个事件，command/http/mcp_tool/prompt/agent | `hooks.json` / config.toml，12 个事件，command/mcp_tool；需 `/hooks` 信任 | **JSON 形状、stdin 协议、退出码 2 = 阻断完全一致**；重叠事件：SessionStart/End、UserPromptSubmit、PreToolUse、PostToolUse、PermissionRequest、Stop、PreCompact |
| MCP | `.mcp.json`、`~/.claude.json` | `~/.codex/config.toml [mcp_servers]`；**不读 .mcp.json** | 协议共享，配置不共享 → 从一份源生成两份 |
| 记忆 | auto-memory `~/.claude/projects/<repo>/memory/`（按 git 仓库路径分，`autoMemoryDirectory` 可重定向到总站） | `~/.codex/memories/`（全局，默认关） | 互不读 → **总站要有自己的记忆** |
| 子 agent | `.claude/agents/*.md` | `.codex/agents/*.toml` | 不共享 |
| 权限 | `permissions.allow/ask/deny` + 模式；沙箱 bwrap/Seatbelt，**原生 Windows 不支持** | `approval_policy` + `sandbox_mode` + `writable_roots`；三平台都有沙箱含原生 Windows | 不共享；基线：Claude `acceptEdits` + allow 列表，Codex `workspace-write` + `--add-dir` |
| 无头模式 | `claude -p --output-format stream-json --resume`；**没有 --cwd**，cwd = 进程 cwd；`--add-dir` 扩权限不扩配置 | `codex exec --json -C <dir>`、`resume <id>` | 都是 NDJSON；两者都有 ACP 适配器 |
| 信任门 | `~/.claude.json` `projects[path].hasTrustDialogAccepted` | `config.toml [projects."path"] trust_level` | 无人值守进新目录都要**预先种下信任** |

**Windows 要点**：symlink 需管理员/开发者模式，junction 不需要；Claude 的 Edit/Write 拒绝穿 symlink 写；CRLF 会让很多加载器静默丢掉 SKILL.md frontmatter（要 `.gitattributes eol=lf`）；Claude 有 Git Bash 用 Bash 工具否则 PowerShell 工具，模型仍倾向输出 bash（#45831）；Codex 原生 PowerShell；hooks 有 `shell: powershell` / `commandWindows` 字段；配置家目录都是 `%USERPROFILE%\.claude`、`\.codex`；WSL 下总站要放 Linux 文件系统，不要 `/mnt/c`。

## 4. "操作机器"的能力面与安全

- **内置核心**（不必重造）：exec、文件、消息、cron 每个 agent 都有。总站应以 **skills（SKILL.md + 脚本）** 为主，重型能力（浏览器、桌面控制）用可选 MCP。
- **浏览器**：Playwright CLI（自带 skills，比 MCP 省 token）、vercel agent-browser（Rust CLI + skill）、Chrome DevTools MCP（调试向）。共识：CLI + skill 优于 MCP。
- **桌面控制**：Windows-MCP、macos-automator-mcp、computer-use-mcp（跨平台 Rust）。
- **剪贴板/通知**：底层都是 notify-send / terminal-notifier / Windows toast，一个三分支脚本比 MCP 便宜。
- **定时/后台**：调度交给 cc-connect `/cron`；OpenClaw 已废弃 HEARTBEAT.md；后台任务需要一个"任务记录"约定（JSON：pid、日志路径、状态），因为 Claude 的 /tasks 从聊天里看不见。
- **跨平台脚本选型**：bash 优先 + 入口点配 .ps1 双胞胎；或 PEP 723 Python 用 `uv run`（Hermes、nanobot 已依赖 uv）；或 Node；或单 Go/Rust 二进制（最稳、成本最高）。会话开始时探测并记录当前 shell。
- **记忆**：`MEMORY.md`（≤200 行 / 25 KB，同时满足 Claude 与 OpenClaw 预算）+ `memory/YYYY-MM-DD.md` + 主题文件；默认不上向量索引，用 ripgrep；总站需要跨项目记忆，Claude auto-memory 是按仓库的。
- **安全分层**：(1) PreToolUse 钩子脚本（bash + ps1）带不可覆盖的硬黑名单（参考 Hermes：`rm -rf /`、fork bomb 即使 --yolo 也拦）；(2) 每项目 allow/deny；(3) 沙箱食谱文档；审批依赖 cc-connect `default` 模式转发到聊天，**永不默认 yolo**；秘密不进总站（`.env` deny-read，`secrets/` gitignore）；`logs/` 只追加。
- **多项目索引**：业界**没有** projects.md 标准 → 自定义注册表（路径、shell、启动命令、沙箱模式、备注），据此生成 `--add-dir` / `additionalDirectories` / cc-connect `/dir` 目标；后台编码跑在**新 worktree**，永不在总站目录里；总站放在所有仓库之外（也避免 Claude 的按仓库 auto-memory 挂到总站上）；指令别用 symlink 指向（Claude 视为外部导入需审批）。

## 5. 发布形态候选（初步，待讨论）

| 形态 | 可升级性 | 用户定制安全 | Windows |
|---|---|---|---|
| git 模板仓库（clone / Use this template） | 差（历史无关，手工合并） | 好 | symlink 坏、CRLF 坑 |
| CLI `init/onboard` 播种 + `doctor` 迁移（OpenClaw、Hermes、nanobot 全是这一路） | 好 | 好（只播种缺失文件，检测偏离） | 需 .ps1 双胞胎，复制不链接 |
| 包装进固定家目录（代码 vs 数据分离） | 代码极好，数据靠迁移 | 好 | `%USERPROFILE%\.x` |
| Claude Code 插件 / marketplace | 好（pin SHA） | 只读，覆盖放 .claude/ | 只服务 Claude；**装不了人格/家目录** |
| `npx skills add`（vercel-labs/skills） | 只管 skills | 叶子内容 | Windows 用 junction |
| "按提示词安装"（LifeOS） | 不确定 | 灵活 | 临场处理 |

无自有运行时时最好的纯脚手架方案：copier（自带 update + migrations）或幂等的 `npx create-*`。

## 6. 对设计的关键结论

1. **空位明确**：cc-connect 不管 work_dir 里有什么。总站 = 一个约定好的目录布局 + 让 Claude/Codex 都能读到的文件 + 一组 skills/hooks/脚本。
2. **文件集直接沿用 OpenClaw 约定**（AGENTS/SOUL/IDENTITY/USER/BOOTSTRAP/MEMORY/memory/skills），生态里 5 个项目结构相同，可互迁；但**不要**引入 HEARTBEAT.md / TOOLS.md（已废弃）。
3. **双 agent 兼容的最小公倍数**：根 `AGENTS.md` + `CLAUDE.md`（`@AGENTS.md`）；skills 同时放 `.claude/skills` 与 `.agents/skills`；hooks 用同一份脚本；MCP 从一份源生成两份配置；信任与权限要预先种下。
4. **总站要有自己的记忆和项目注册表**，两个 agent 的原生记忆互不相通且不跨项目。
5. **cc-connect 已提供的别重造**：附件进出、`cc-connect send` 回传、`/cron`、`/dir`、审批转发。总站只需把这些用法写进 AGENTS.md 并配 skills。
6. **发布形态倾向**：`init` 播种 + `doctor` 检查/迁移，而不是让用户 clone 模板仓库；是否需要一个真正的 CLI（Go/Node/Python）还是纯脚本，是接下来第一个要定的事。
7. **跨平台**：Windows 原生要付出 symlink/CRLF/PowerShell 三重代价，WSL2 是省事路线；设计上"复制不链接、LF 换行、入口脚本双胞胎"。

## 来源（精选）
- cc-connect: https://github.com/chenhg5/cc-connect · README · INSTALL.md · config.example.toml · docs/usage.md · agent/claudecode/session.go · agent/codex/session.go · core/message.go
- OpenClaw: https://docs.openclaw.ai/concepts/agent-workspace · /concepts/memory · /tools/skills · /start/bootstrapping · /gateway/heartbeat · /platforms/windows · /reference/templates/*
- Hermes: https://hermes-agent.nousresearch.com/docs · nanobot: https://github.com/HKUDS/nanobot · PicoClaw: https://github.com/sipeed/picoclaw · Letta MemFS: https://docs.letta.com/concepts/memfs · agentsmd: https://github.com/adiasg/agentsmd · kindomLee template: https://github.com/kindomLee/openclaw-workspace-template
- Claude Code: https://code.claude.com/docs/en/memory · /skills · /hooks · /mcp · /permissions · /sandboxing · /headless · /cli-reference · /plugins · /settings
- Codex: https://learn.chatgpt.com/docs/agent-configuration/agents-md · /build-skills · /hooks · /config-file/config-reference · /agent-approvals-security · /non-interactive-mode · /app-server
- 标准: https://agents.md · https://agentskills.io/specification · https://agentclientprotocol.com
- 工具: https://github.com/microsoft/playwright-cli · https://github.com/vercel-labs/agent-browser · https://github.com/vercel-labs/skills · https://github.com/anthropic-experimental/sandbox-runtime
