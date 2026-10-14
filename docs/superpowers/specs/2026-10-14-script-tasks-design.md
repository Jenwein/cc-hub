# 脚本任务、按需任务与限权任务设计

日期：2026-10-14
适用版本：计划为 0.5.0，与"定时任务时间覆盖与指针登记"（`docs/superpowers/specs/2026-10-12-cron-overrides-design.md`）一起发布
关联：`docs/superpowers/specs/2026-09-22-cc-hub-design.md` §4.1、§4.5、§7、§8.2、§8.3、§8.5、§8.9、§11；`hub-apps` 的 `docs/superpowers/specs/2026-10-14-mail-design.md`（第一个用到它的应用）

标注约定：没有标注的内容是用户的决定；标"（Claude 定）"的是 Claude 替用户做的选择，用户可以改；标"（留给实现者）"的由实现者决定。

---

## 1. 为什么

现在每个定时任务都是一段提示词，每次触发都唤醒 agent。有的应用需要频繁地做一件不需要 agent 的小事，只在发现情况时才需要 agent。例如 `hub-apps` 的 `mail`：每 5 分钟查一次新邮件，一天 288 次，绝大多数时候什么都没有。每次都唤醒 agent，既浪费用量，也会在聊天里留下大量空转。

cc-connect 已经具备需要的能力（v1.5.0，已在源码中确认）：

- `cc-connect cron add --exec "<命令>"` 登记一个直接执行 shell 命令、不经过 agent 的任务；
- `cc-connect cron edit <id> mute true` 让一个任务不往聊天里发任何消息（`cron add` 没有对应的参数，只能登记后再改）；
- `cc-connect cron exec <id>` 立即触发一个已登记的任务，任务被停用时也会执行。

缺的是 cc-hub 这一侧：任务定义只能写提示词，登记流程只会登记提示词任务，脚本也没有办法按名字唤醒一个任务。

## 2. 目标和非目标

**目标**

- 任务定义除了现有的提示词任务，还能声明两种任务：
  - **脚本任务**：按时间执行一条命令，不唤醒 agent，不往聊天里发任何东西；
  - **按需任务**：一段提示词，没有时间，平时不运行，只在脚本唤醒它时运行。
- 脚本可以按任务名唤醒按需任务：`cc-hub cron wake <任务>`。
- 两种新任务都由现有的登记流程（`hub-adapt`、`hub-apps` 设置第 3 步）登记、比对、注销，并和时间覆盖配合。
- 总站自带的 `cron/` 和应用的 `cron/` 都能用这两种任务。
- 提示词任务和按需任务可以声明一张命令清单，运行时只能执行清单上的命令（限权任务，§8）。
- `AGENTS.md` 的凭据规则放开一小步，让应用能保存用户在聊天里交给它的凭据（§9）。

**非目标**

- cc-hub 自己做调度：调度仍然属于 cc-connect。
- 脚本任务直接往聊天里发消息：脚本任务一律静音；要对用户说话，就唤醒一个按需任务，由 agent 决定说什么（Claude 定）。
- 登记和删除由 cc-hub 执行：仍然由 agent 执行。`cc-hub cron wake` 是 cc-hub 唯一调用 cc-connect 的地方（§5）。

## 3. 定义格式

三种任务都放在原来的位置（总站 `cron/<name>.md`，应用 `apps/<app>/cron/<task>.md`），frontmatter 决定种类：

**提示词任务**（不变）：

```
---
schedule: "0 3 * * *"
default: true
session: new_per_run
---
Prompt text the agent receives when the task fires.
```

**脚本任务**：有 `exec`。

```
---
schedule: "*/5 * * * *"
default: true
exec: "uv run apps/mail/scripts/mk.py poll"
timeout_mins: 5
---
What the command does, for the user and the agent. Not executed, not sent.
```

- `exec`：要执行的命令。命令在总站根目录下执行（cc-connect 的 `work_dir`），Linux 和 macOS 上用 `sh -c`，Windows 上用 PowerShell。所以命令只写"程序 + 参数"这种两边都能执行的形式，不用 `&&`、管道、重定向和引号嵌套（Claude 定）。
- `timeout_mins`：可选，缺省为 10（Claude 定）。不写的话 cc-connect 自己的缺省值不稳定（登记时不给是 30 分钟，给 0 时实际是 60 秒），所以登记时总是显式传。
- 没有 `session`；写了视为定义错误。
- 正文是给人和 agent 看的说明，登记时不使用。

**按需任务**：有 `on_demand: true`，没有 `schedule`。

```
---
on_demand: true
default: true
session: new_per_run
---
Prompt text the agent receives when a script wakes the task.
```

**静默**：cc-connect 缺省在每次运行开始时往聊天里发一条"⏰ <描述>"，手动 `cron exec` 触发的也发。按需任务一律静默登记，否则每次唤醒都会出现这条提示，即使 agent 最后什么都不说（`NO_REPLY`）。提示词任务可以在 frontmatter 里写 `silent: true` 选择静默，缺省不静默，与现在一致（Claude 定）。脚本任务已经整个静音，不需要这一项。

**定义错误**：同时有 `exec` 和 `on_demand`；按需任务有 `schedule`；其他任务缺 `schedule`；`exec` 为空；`timeout_mins` 不是正整数。应用安装和升级时的校验（§8.3）加上这几条，有错就拒绝；总站 `cron/` 下的错误由 `doctor` 报出（Claude 定）。

## 4. 登记

登记仍由 agent 在和用户本人的私聊里执行，描述仍是 `hub:<名>`。`cc-hub cron list --json` 给出每个任务的种类（`prompt`、`exec`、`on_demand`）和登记要用的全部参数，agent 照着做。

**脚本任务**：

```
cc-connect cron add --cron "<实际生效的时间>" --exec "<exec>" --timeout-mins <n> --desc "hub:<名>"
cc-connect cron edit <id> mute true
```

第二步失败时，删掉刚登记的任务并告诉用户，不留下一个会往聊天里发输出的任务（Claude 定）。

**按需任务**：

```
cc-connect cron add --cron "<占位时间>" --prompt "<指针提示词>" --session-mode <session> --silent --desc "hub:<名>"
cc-connect cron edit <id> enabled false
```

`silent: true` 的提示词任务登记时同样加 `--silent`。

- 提示词用时间覆盖设计里的指针（指向定义文件），和提示词任务一样。
- cc-connect 要求每个任务有时间，所以给一个占位时间，再停用；`cron exec` 照样能触发停用的任务。占位时间的取值留给实现者。

**比对**：登记流程比对 `cc-connect cron list` 和 `cc-connect cron info <id>` 时，脚本任务比对时间、命令、超时和静音；按需任务比对提示词、`session`、静默和停用状态；提示词任务在原有比对之外加上静默。任何一项不一致就删掉重登。

**批准**：脚本任务登记后会在没有 agent 参与的情况下反复执行，所以登记前 agent 把命令和定义正文告诉用户，用户同意才登记；不同意就不登记，在 memory log 里记一笔，并告诉用户这个应用的哪些功能因此不可用（Claude 定）。应用升级改了命令时，设置指纹变化，应用回到 `pending`，重新设置时再问一次。这与 §8.9"执行安装命令前先告诉用户它做什么"是同一条原则：cc-hub 自己仍然不执行应用提供的字符串。

## 5. 唤醒

```
cc-hub cron wake <任务>
```

例子：

```bash
cc-hub cron wake mail/triage
```

- 只接受按需任务；任务名的写法同时间覆盖（总站任务用文件名，应用任务用 `<应用>/<任务>`）。
- 在 `cc-connect cron list` 里找描述为 `hub:<任务>` 的任务，执行 `cc-connect cron exec <id>`。
- 退出码：0 表示已交给 cc-connect；1 表示没唤醒，原因写 stderr：不是按需任务、任务不存在、没登记、被用户关掉、找不到 `cc-connect`、cc-connect 没在运行。
- 唤醒是"发出去就不管"：退出码 0 只说明 cc-connect 收到了，不说明 agent 已经处理完。应用要靠自己的状态确认处理结果（例如 agent 处理完后调用应用的脚本做标记），没确认的过一段时间再唤醒。重复唤醒同一个按需任务时，避免并发处理同一批数据也是应用自己的事（Claude 定）。
- 为什么由 cc-hub 来做：解析 `cc-connect cron list` 的输出只放在一个经过测试的地方，各个应用的脚本不必各写一遍（Claude 定）。

## 6. 与时间覆盖的关系

- 脚本任务和提示词任务一样，时间可以用 `cc-hub cron set <任务> <表达式>` 覆盖，也可以 `--off`、`--on`、`reset`。例如用户只想每天查一次信：`cc-hub cron set mail/poll "0 8 * * *"`。
- 按需任务没有时间：`cron set <按需任务> <表达式>` 报错且不写任何东西；`--off`、`--on` 可以用，关掉就是注销，之后 `wake` 返回 1（Claude 定）。
- `cron list` 多列出种类，脚本任务多列出命令和超时。

## 7. 运行环境

- 工作目录：总站根目录。`cc-hub` 在这里能找到总站，不需要 `CC_HUB_DIR`。
- 环境变量：脚本任务继承 cc-connect 守护进程的环境，**不是** `[projects.agent.options.env]` 里给 agent 设的那份，也没有 `CC_SESSION_KEY`、`CC_PROJECT`。cc-connect 作为后台服务运行时，PATH 往往只有系统目录，`uv`、`cc-hub`、`cc-connect` 可能都找不到。实现者先在 Linux（systemd 用户服务）上确认这一点，再在 `docs/cc-connect.md` 里写明怎样给守护进程设 PATH；`doctor` 能检查的话也加一条（留给实现者）。
- 输出：脚本任务静音，输出不会出现在任何地方。需要日志的应用自己写日志。

## 8. 限权任务（安全带）

**为什么**：后台的提示词任务和按需任务在没人看着的时候运行。很多用户让 agent 在不需要批准的模式下运行（Claude Code 的 `bypassPermissions`，俗称 YOLO），这时 agent 能执行任何命令。有的任务要读外来的内容，例如 `mail` 的判断任务读的是陌生人写的邮件，内容里可能藏着冲着 agent 来的指令；agent 一旦被骗，就会照做。限权给这类任务系一条安全带：只能执行定义里列出的命令，其他一律拒绝，也不询问。用户平时聊天的会话不受影响。

**定义**：提示词任务和按需任务可以写 `allow`，有 `allow` 的叫限权任务。

```
---
on_demand: true
default: true
session: new_per_run
allow:
  - "uv run apps/mail/scripts/mk.py bg"
---
```

- 每一项是一个命令前缀，任务里执行的每条命令都必须以清单里的某一项开头。
- 任务能读总站里的文件（至少要读自己的定义文件）；写文件、上网、执行清单外的命令都被拒绝。
- 脚本任务不经过 agent，不能写 `allow`，写了视为定义错误。

**在 Claude Code 上的做法**（实现者在真实的 cc-connect 上验证后再定细节）：

- 登记后执行 `cc-connect cron edit <id> mode dontAsk`：这个任务的会话里，没有事先允许的操作一律拒绝，不询问。
- 清单写进总站的 Claude Code 权限设置（`.claude/settings.json` 的 `permissions.allow`，形如 `Bash(<前缀>:*)`；读总站文件需要的条目也一并写入），由 `hub-adapt` 和 `hub-apps` 的设置流程从所有限权任务汇总生成。合并写入，不动用户自己加的条目；任务注销后清掉它带来的条目。`.claude/` 本来就是派生目录，不进 git。
- 这些允许条目对用户平时聊天的会话也生效：清单里的命令平时聊天时也不再询问。所以清单只放安全的命令，应用要为限权任务单独准备一组只读、不对外发东西的命令（Claude 定）。
- **必须验证**：用户把整个项目设成 YOLO 时，任务级的 `dontAsk` 确实覆盖它，清单外的命令确实被拒绝。验证不通过，这项功能就不算完成：要么找到别的办法，要么回来问用户。

**其他 agent**：Codex 等 agent 的对应做法由实现者调查。找不到等价机制时，限权任务在该 agent 上登记前，agent 告诉用户"这个任务在这里没有安全带"，用户同意才登记（Claude 定）。

**登记和比对**：限权任务的比对加上 `mode` 和权限设置里的条目；`cron list --json` 列出 `allow`。

## 9. 凭据规则

`AGENTS.md` §5 现在写着："Never read, print, or copy credentials: `.env` files, keys, tokens."。`mail` 应用要把用户在聊天里交给 agent 的邮箱专用密码存下来，照这条规则 agent 可能拒绝。用户同意放开这一小步，改为（措辞 Claude 定）：

```
- Never read, print, or copy credentials: `.env` files, keys, tokens. One
  exception: a credential the user gives you in chat for an app may be
  passed to that app's own tool, which stores it under `secrets/`. Never
  print it back or commit it, and suggest the user delete or recall the
  message that contained it.
```

改动随 `cc-hub update` 送到已有总站。`AGENTS.md` 的行数上限（150 行）不变。

## 10. 其他

- `hub-adapt` 第 4 步、`hub-apps` 设置第 3 步、`cron/README.md` 加上两种新任务的登记命令、批准规则和唤醒用法；通过 `cc-hub update` 送到已有总站。
- 卸载应用时注销 `hub:<app>/*` 的规则不变，三种任务一视同仁。
- 设计规格（`2026-09-22-cc-hub-design.md`）§4.1、§4.5、§5、§7、§8.2、§8.3、§8.5、§8.9、§11 相应更新；README 命令表、`docs/apps.md`、`docs/cc-connect.md` 相应更新；CHANGELOG 记在 0.5.0 下。官网命令参考的处理同时间覆盖设计 §7。
- 0.5.0 的实现计划同时覆盖两份设计：先做时间覆盖（本设计依赖它的 `cron list --json`、`cron set` 和指针提示词），再做本设计（Claude 定）。
- 0.5.0 的发布同时间覆盖设计：发布前先问用户。`hub-apps` 的 `mail` 应用要等 0.5.0 发布后才能合并（Claude 定）。

## 11. 测试

- 定义解析：三种任务的合法形式和每一种定义错误；应用校验拒绝错误定义；`doctor` 报出总站 `cron/` 下的错误定义。
- `cron list --json`：种类、命令、超时、登记参数；时间覆盖作用于脚本任务；按需任务没有时间。
- `cron set`：拒绝给按需任务设时间；`--off`、`--on` 对三种任务都有效。
- `cron wake`：用一个假的 `cc-connect`（放在测试的 PATH 里）验证找到正确的 id 并调用 `cron exec`；每一种失败原因的退出码和 stderr。
- 限权：定义里的 `allow` 解析和错误（脚本任务带 `allow`）；权限设置的合并写入不动用户条目、注销后清理；`cron list --json` 列出 `allow`。
- 手工验收（限权）：项目设成 YOLO，登记一个限权的按需任务，唤醒后让它尝试执行清单外的命令，确认被拒绝且聊天里没有批准请求。
- 手工验收：在 Linux 上的真实 cc-connect 里登记一个脚本任务，确认它按时执行、聊天里什么都不出现；脚本调用 `cc-hub cron wake` 后按需任务运行，回复发到聊天里。

## 12. 留给实现者

按需任务的占位时间；权限设置的合并方式和条目写法；`cron list --json` 新字段的名字；比对时读取 cc-connect 任务详情的方式；`docs/cc-connect.md` 里给守护进程设 PATH 的具体写法。
