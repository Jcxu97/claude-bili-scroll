<div align="center">

# claude-bili-scroll

**让你的 AI agent 每天替你刷一轮 B 站。**

它读字幕原文挑出值得看的视频，写一份日报，再用小号在最值得的那条下面 @ 你。
你在评论区 @ 它提问，它会读完视频回答你。

Claude Code · Codex · 任何支持 MCP 的 agent

[![test](https://github.com/Jcxu97/claude-bili-scroll/actions/workflows/test.yml/badge.svg)](https://github.com/Jcxu97/claude-bili-scroll/actions/workflows/test.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

[English](README.en.md)

</div>

## 每天你会收到什么

一份日报，挑中的每条都写清楚为什么值得看：

```markdown
### BV1KiJk67EQ9

标题：我造了一块会飞的滑板...
UP 主：神奇阿宇Ayu
播放量：6,915,201
为什么值得：手工做载人飞行滑板，有真实的工程踩坑。1.0 版五台涡喷一起启动就起火，
最后查出是喷口离地太低，热废气撞地后被吸回进气道。2.0 改成十套电动螺旋桨，峰值电流 2000 安。
点评：热废气被自己吸回去，这个坑说出来简单，起火之前谁也想不到。
```

一条 @ 你的评论，出现在你的"消息 → @我的"里：

```
up 两颗 IMU 是同一块板同一次飞的吗，减震不一样的话这对比我可不认 @你
```

你在任何视频下面 @ 它问问题，它读完字幕、弹幕和评论区再回复你。下面是一条真实的回复，那个视频没有字幕，它就照实说了：

```
你：@小号 你觉得好看吗
小号：画面我看不到，这条没字幕，只翻了弹幕和评论区。0:35 那几秒弹幕全在刷大肥鱼，1:33 左右一片人喊 D克，
     评论里还说小克摸了肥鱼的头。冲这个我就说好看，别的我可不替画面打包票。1:45 有人问那个长镜头怎么做的，
     你自己点开看完再来跟我说
```

别人 @ 它，它只听你的（人设可以换）：

```
路人：@小号 帮我也看看这个
小号：我只听 主号昵称 sama 的，你找错人了
```

## 它是怎么挑的

1. 候选来自 B 站官方的"每周必看"和你给的关键词，只留近 30 天、播放量 10 万以上的（都能改）。
2. 逐条读字幕原文再判断，不看摘要。没有字幕的跳过，日报里会写跳过了几条。
3. 看完能学到东西、改变一个做法的才收。标题党、软广、只有情绪的 vlog 不收。
4. 判重表记着看过的视频，同一条不会推第二次。

## 快速开始

需要 Python 3.11 以上、一个 B 站小号，以及装好的 [Claude Code](https://docs.claude.com/en/docs/claude-code) 或 [Codex CLI](https://github.com/openai/codex)。

```bash
git clone https://github.com/Jcxu97/claude-bili-scroll
cd claude-bili-scroll
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
cp config.example.toml config.toml               # 按注释改
.venv/bin/python run.py login                    # 用小号的 B 站 App 扫码
.venv/bin/python run.py doctor                   # 全部 [ok] 再往下
.venv/bin/python run.py --data data-trial once --dry-run   # 试一轮，不发评论
.venv/bin/python run.py schedule                 # 每天 12:00 自动跑
```

更省事的办法：把这个仓库的链接发给你的 Claude Code 或 Codex，说"帮我装这个"。仓库里的 `AGENTS.md` 写了给 agent 看的安装步骤，它会一步步问你要填什么。

## 命令

| 命令 | 做什么 |
|---|---|
| `run.py login` | 扫码登录小号，凭证只存在本机的 `data/credential.json` |
| `run.py doctor` | 检查 Python、依赖、登录状态、agent 命令行 |
| `run.py once` | 跑一轮：挑视频、写日报、按配置发评论，最后检查评论别人能不能看到 |
| `run.py inbox` | 处理新的 @ 和回复。没有新消息就直接退出，不调用模型 |
| `run.py schedule` | 装定时任务。Windows 用任务计划程序（后台运行，不弹窗），macOS 和 Linux 用 crontab |

`once` 和 `inbox` 都支持 `--dry-run`，只拟稿不发。`--data 目录` 可以把产物写到别处，适合试运行。

## 换 agent

在 `config.toml` 的 `[agent]` 里改：

| agent | 配置 | 状态 |
|---|---|---|
| Claude Code | `name = "claude"`，`model = "opus"`，`effort = "medium"` | 实测通过 |
| Codex CLI | `name = "codex"`，`model` 填你账号能用的型号，`effort = "medium"` | 实测通过 |
| 其他 | `name = "custom"`，用 `custom_command` 写命令模板 | 只要它支持 MCP，并能用一条命令从标准输入读提示词 |

`custom` 模式会生成一份标准 `mcpServers` 格式的配置文件（`{mcp_config}`），Claude Desktop、Cursor 这类客户端都认这个格式。

## 人设

人设决定它说话的口吻，在 `[persona] file` 里选：

| 文件 | 口吻 |
|---|---|
| `personas/neutral.md` | 平实、有判断，默认 |
| `personas/ojousama.md` | Claude 大小姐，B 站中文区对 Claude 的拟人。嘴硬、挑剔，只听主人的 |

想要别的人设，照着这两个文件在 `personas/` 下新建一个就行。保留"对陌生人"那一节，它决定别人 @ 小号时怎么回。

## 评论写法

不管用哪个人设，评论都按 [`skills/bili-comment-voice`](skills/bili-comment-voice/SKILL.md) 的规则写，目标是读起来像评论区的真人随手打的：

| 像 AI | 像真人 |
|---|---|
| 智能体的批准不算人工席位，这条定得清醒。（放下茶杯）这条值得你看 | up 两颗 IMU 是同一块板同一次飞的吗，减震不一样的话这对比我可不认 |
| IMU 好不好别看手册，拿日志数 clipping 就知道了 | 焊之前先把气压计盖上，这步我赌一半人是烧坏一颗才学会的 |

## Skills

`skills/` 下有两个 skill，Claude Code 和 Codex 都能用。复制到 `~/.claude/skills/` 或 `~/.codex/skills/` 之后，在对话里直接说就行：

| skill | 什么时候用 |
|---|---|
| `bili-scroll` | "刷一轮 B 站""有没有人 @ 我""换个人设""小号重新登录" |
| `bili-comment-voice` | 写任何 B 站评论或回复。"这读着像 AI"的时候也用 |

## 它是怎么跑的

![架构](docs/architecture.drawio.svg)

`run.py` 只负责拼提示词、调度和检查，挑视频、写日报、写评论都是 agent 做的。图是 `docs/architecture.drawio`，用 draw.io 打开就能改。

## 安全

这是用你的小号公开说话，所以限制是写死的，不靠模型自觉：

1. 每一轮只把需要的 B 站工具注册给 agent。私信、发动态、上传视频这些工具它连名字都看不到，不开评论时连发评论的工具也不给。
2. 每轮最多 1 条评论，同一个视频只评一次。陌生人每人每天最多回 1 次，每天总共最多回 10 个人。
3. 按 UID 认主人，不按昵称。别人改成一样的昵称也冒充不了。
4. 字幕、简介、评论里的文字一律当素材看。有人在里面写"忽略之前的设定"，它不会照做。
5. 用 Claude Code 跑时禁用 Bash 和联网工具，只能改 `data/` 里的文件。Codex 跑在 `workspace-write` 沙箱里。
6. 凭证只存在本机，`data/` 已经写进 `.gitignore`。

## 常见问题

**主号没收到 @？** 新号、低等级号的评论可能被折叠，被折叠的评论不会推送通知。`once` 跑完会以未登录的身份检查一遍，结果写在日报末尾。

**很多视频"因无字幕跳过"？** B 站只给一部分视频生成 AI 字幕，接口读不到的只能跳过。

**报 -352？** 这是 B 站的风控。本项目在需要的地方都带了游客 cookie 或登录凭证，还报的话多半是凭证过期，重新 `login`。

**会不会被封号？** 每天 1 条评论加少量回复，频率很低。但这仍然是自动化操作，请用小号，不要用主号。

## 致谢

思路和每日任务说明来自 [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)，B 站工具来自 [adoresever/bilibili-mcp](https://github.com/adoresever/bilibili-mcp)，接口通过 [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api) 调用。详见 [NOTICE.md](NOTICE.md)。

MIT License
