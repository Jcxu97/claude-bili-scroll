---
name: bili-scroll
description: 操作 claude-bili-scroll（替用户每天刷 B 站的工具）。用户说"刷一轮 B 站""看看今天 B 站有什么""有没有人 @ 我""有没有人私信""回一下评论""换个人设""加个关键词""B 站小号重新登录""部署到服务器"时用。
---

# 操作 claude-bili-scroll

这个 skill 假设仓库已经装好（装法见仓库里的 `AGENTS.md`）。下面的命令都在仓库目录里，用 `.venv` 里的 python 跑。

## 用户说了什么，就跑什么

1. 用户说"刷一轮 B 站"或"看看今天有什么"，先读数据目录里的 `journal/今天日期.md`（作息模式下的刷站日记），挑一两条说给用户听，带链接。今天还没刷，就跑 `python run.py browse`。没开作息模式时跑 `python run.py once`，读 `out/今天日期.md`。
2. 用户说"先试试"或"别发评论"，就跑 `python run.py --data data-trial once --dry-run`。
3. 用户说"有没有人 @ 我""有没有人私信"或"回一下评论"，先读数据目录里的 `inbox/今天日期.md`，后台每次收到消息、回了什么都记在那里，挑要紧的说给用户听。后台没在跑时，再跑 `python run.py inbox`，没有新消息它会直接说没有。
4. 用户说"小号掉线了"或"重新登录"，就跑 `python run.py login`，让用户扫码。
5. 用户说"看看配置对不对"，就跑 `python run.py doctor`。它会真的调用一次 agent。
6. 用户说"每天自动跑"或"一直开着"，就跑 `python run.py schedule`。它让 `serve` 在后台常驻。作息模式下按作息刷站、查消息。没开作息模式时每天 12:00 以后刷一轮，开了收件箱就每 5 分钟查一次消息。改时间加 `--at 08:30`，改间隔加 `--every 10`，停掉加 `--remove`。Windows 上要在管理员终端里跑，后台才能开机就启动。
7. 用户说"部署到服务器"或"换台机器跑"，先在旧机器上跑 `python run.py schedule --remove`，再让用户把 `config.toml` 和整个数据目录拷到新机器，数据目录换了位置就改 `[paths] data`，最后在新机器上跑 `python run.py install`。

## 用户想改设置

都在 `config.toml` 里，改完不用重启，下一轮自动生效。
1. 题材改 `[scroll] keywords`
2. 门槛改 `[scroll] min_play`（播放量）、`days`（近几天）、`max_picks`（每天几条）
3. 人设改 `[persona] file`，自带 `personas/neutral.md` 和 `personas/ojousama.md`。用户想要新的人设，就照着这两个文件的结构在 `personas/` 下新建一个，保留"对陌生人"那一节
4. 评论和回复改 `[comment]` 和 `[inbox]`。打开之前先跟用户确认，这是用用户自己的号公开说话
5. 作息、主动私信的次数和间隔改 `[life]`。后台网页改 `[web]`，`password` 留空就不开

## 写评论或回复

要手写 B 站评论时，先读同目录的 `bili-comment-voice` skill，按它的规则写。
