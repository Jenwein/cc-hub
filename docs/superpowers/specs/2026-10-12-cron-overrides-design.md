# 定时任务时间覆盖设计

日期：2026-10-12
适用版本：计划为 0.5.0
关联：`docs/superpowers/specs/2026-09-22-cc-hub-design.md` §4.5（cron 任务定义）、§7、§8.5（应用设置）

标注约定：没有标注的内容是用户的决定；标"（Claude 定）"的是 Claude 替用户做的选择，用户可以改；标"（留给实现者）"的由实现者决定。

---

## 1. 为什么

现在每个定时任务的时间写在它的定义文件里（总站的 `cron/<name>.md`，应用的 `apps/<app>/cron/<task>.md`），由作者决定。用户想改时间却留不住：

- 直接在 cc-connect 里改登记的时间，下次设置流程重跑时，`hub-apps` 发现登记的和文件里的不一致，会删掉重新按文件登记；
- 改总站里那份应用文件，应用升级时整个应用目录被替换。

像提醒、打卡这类应用（例如 `hub-apps` 里的 `plans`），时间因人而异，必须能由用户决定。

## 2. 目标和非目标

**目标**

- 用户可以覆盖任何一个定时任务的时间（总站自带的和应用的），也可以关掉或恢复某个任务。
- 覆盖存在总站里，`cc-hub update`、应用升级和设置流程重跑都不会改掉它。
- 登记定时任务的地方（`hub-adapt`、`hub-apps` 的设置流程）一律按"实际生效的时间"登记。

**非目标**

- 修改任务的提示词正文。
- cc-hub 自己调用 cc-connect：登记和删除定时任务仍然由 agent 执行（§5）。

## 3. 覆盖存在哪

存在总站的 `hub.toml`。这个文件归用户，`update` 不碰它，随总站一起提交。

```toml
[cron."memory-consolidate"]        # 总站自带的任务：用文件名
schedule = "30 2 * * *"

[cron."plans/morning"]             # 应用的任务：<应用>/<任务>
schedule = "0 7 * * *"

[cron."ledger/prices"]
enabled = false
```

- 键是任务名：总站任务用文件名（不含 `.md`），应用任务用 `<应用>/<任务>`，与登记时描述里 `hub:` 后面的部分一致。
- `schedule`：五段式 cron 表达式；`enabled`：`false` 表示关掉，缺省为开。
- 实际生效的时间：有覆盖用覆盖，否则用定义文件里的；实际是否登记：定义文件 `default: true` 且没有被 `enabled = false` 关掉；`enabled = true` 的覆盖可以把 `default: false` 的任务打开（Claude 定）。

## 4. 命令

```
cc-hub cron list [--json]
cc-hub cron set <任务> <cron 表达式>
cc-hub cron set <任务> --off
cc-hub cron set <任务> --on
cc-hub cron reset <任务>
```

（`<…>` 表示必填的值；`[…]` 表示可选。）

例子：

```bash
cc-hub cron set plans/morning "0 7 * * *"
```
```bash
cc-hub cron set ledger/prices --off
```
```bash
cc-hub cron reset plans/morning
```

- `cron list`：列出总站和所有已安装应用的定时任务：任务名、来源（总站或哪个应用）、定义文件里的时间、实际生效的时间、是否被覆盖、是否登记、`session`、登记用的描述（`hub:<名>`）和提示词。`--json` 给 agent 用。
- `cron set`：校验任务存在、表达式合法，写进 `hub.toml`，提交（`cc-hub: cron set <任务>`），然后打印 agent 接下来要执行的重新登记步骤（先删旧的 `hub:<任务>`，再按新时间登记，或关掉时只删）。
- `cron reset`：去掉覆盖，回到定义文件里的时间，同样提交并打印重新登记步骤。
- 任务名不存在、表达式不合法时报错，不写任何东西。

## 5. 登记流程的改动

- `hub-adapt`（总站自带任务）和 `hub-apps` 的设置第 3 步（应用任务）改为读取 `cc-hub cron list --json`，按其中的实际生效时间和是否登记来比对 `cc-connect cron list`：时间或提示词不一致的删掉重登；被关掉的删掉；该登记而没登记的登记上。
- 因此设置流程重跑、应用升级都不会再把用户的时间改回去。
- 用户在聊天里说"把某某提醒改到几点""关掉某某任务"时，agent 运行 `cc-hub cron set`，再照它打印的步骤在 cc-connect 里重新登记。这条写进 `hub-apps` skill（应用任务）和总站自带任务的说明（`cron/README.md`、`hub-adapt`）。
- 应用的 `SETUP.md` 可以在设置时询问用户的时间并调用 `cc-hub cron set`（例如 `plans`）。

## 6. 其他

- `doctor` 新增检查：`hub.toml` 里覆盖的任务是否还存在（应用卸载后残留的覆盖给出提示，修复方法是 `cc-hub cron reset`），表达式是否合法。
- 卸载应用时，`app remove` 顺带删掉该应用在 `hub.toml` 里的覆盖并一起提交（Claude 定）。
- 框架文件（`hub-adapt`、`hub-apps` skill、`cron/README.md`）的改动通过 `cc-hub update` 送到已有总站。
- 设计规格（`2026-09-22-cc-hub-design.md`）§4.4、§4.5、§5、§7、§8.5 相应更新，README 的命令表和现有用户文档相应更新，CHANGELOG 记在 0.5.0 下。官网如果在这之前已经上线，命令参考同步加上 `cc-hub cron`；如果还没建，由官网的实现把它包含进去（Claude 定）。
- 这项工作以发布 0.5.0 收尾，发布前先问用户；`hub-apps` 的 `plans` 应用要等它发布后才能合并（Claude 定）。

## 7. 测试

- `cron list`：总站任务和应用任务、覆盖与未覆盖、关掉的、`default: false` 被打开的。
- `cron set`/`reset`：写入和删除 `hub.toml` 的对应段落而不改动文件的其他内容、提交、打印的重新登记步骤、错误输入不写任何东西。
- `doctor`：残留覆盖、非法表达式。
- `app remove` 清理覆盖。

## 8. 留给实现者

`cron list --json` 的字段名；重新登记步骤的打印格式；`hub.toml` 写入时保留注释和格式的方式。
