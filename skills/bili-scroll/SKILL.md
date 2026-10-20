---
name: bili-scroll
description: 操作 claude-bili-scroll（替用户每天刷 B 站的工具）。用户说"刷一轮 B 站""看看今天 B 站有什么""有没有人 @ 我""回一下评论""换个人设""加个关键词""B 站小号重新登录"时用。
---

# 操作 claude-bili-scroll

这个 skill 假设仓库已经装好（装法见仓库里的 `AGENTS.md`）。下面的命令都在仓库目录里，用 `.venv` 里的 python 跑。

## 用户说了什么，就跑什么

1. "刷一轮 B 站""看看今天有什么"：`python run.py once`。跑完把 `data/out/今天日期.md` 的挑中条目念给用户听，每条一句话，带链接。
2. "先试试""别发评论"：`python run.py --data data-trial once --dry-run`。
3. "有没有人 @ 我""回一下评论"：`python run.py inbox`。没有新消息它会直接说没有。
4. "小号掉线了""重新登录"：`python run.py login`，让用户扫码。
5. "看看配置对不对"：`python run.py doctor`。
6. "每天自动跑"：`python run.py schedule`。改时间加 `--at 08:30`，停掉加 `--remove`。

## 用户想改设置

都在 `config.toml` 里，改完不用重启，下一轮自动生效：
1. 题材：`[scroll] keywords`
2. 门槛：`[scroll] min_play`（播放量）、`days`（近几天）、`max_picks`（每天几条）
3. 人设：`[persona] file`，自带 `personas/neutral.md` 和 `personas/ojousama.md`。用户想要新的人设，就照着这两个文件的结构在 `personas/` 下新建一个，保留"对陌生人"那一节
4. 评论和回复：`[comment]` 和 `[inbox]`。打开之前先跟用户确认，这是用他的号公开说话

## 写评论或回复

要手写 B 站评论时，先读同目录的 `bili-comment-voice` skill，按它的规则写。
