# 署名与第三方代码

本项目以 MIT 协议发布，正文见 `LICENSE`。

## 来源

1. 思路、每日任务说明和"评论后复核"的做法来自 [c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)（MIT）。那是一个 DeepSeek Harness（DSH）插件，本项目把它改写成不依赖任何宿主的版本，可以给 Claude Code、Codex 或别的 agent 用。
2. `bili_mcp/server.py` 来自 [adoresever/bilibili-mcp](https://github.com/adoresever/bilibili-mcp)（MIT，Copyright (c) 2026 AGI_Ananas），经 dsh-bili-scroll 修改后再由本项目修改。许可证原文在 `bili_mcp/LICENSE`，修改清单写在文件开头的注释里。
3. B 站接口通过 [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api) 调用。

## 评论写法

`skills/bili-comment-voice` 里的规则参考了维基百科的 [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)，内容是本项目按 B 站评论区重新写的，没有照搬原文。

## 人设

`personas/ojousama.md` 里的"Claude 大小姐"形象来自 B 站中文区的二创，不代表 Anthropic，也不是官方形象。
