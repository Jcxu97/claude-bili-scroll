import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run  # noqa: E402


def cfg(**over):
    c = {k: dict(v) for k, v in run.DEFAULTS.items()}
    for section, values in over.items():
        c[section].update(values)
    return c


def notice(rpid, mid, t=2000, bv="BV1xx411c7mD"):
    return {"user": {"mid": mid, "nickname": f"u{mid}"}, "at_time": t,
            "item": {"business_id": 1, "source_id": rpid, "root_id": 0, "uri": f"https://www.bilibili.com/video/{bv}",
                     "title": "t", "source_content": "@bot 问个问题", "target_reply_content": ""}}


class PromptTest(unittest.TestCase):
    def test_comment_tool_only_when_enabled_and_not_dry_run(self):
        on = cfg(comment={"enabled": True, "at": "主号"}, persona={"file": "personas/ojousama.md"})
        prompt, tools = run.build_prompt(on, "scroll", dry_run=False)
        self.assertIn("bili_reply", tools)
        self.assertIn("主号 sama", prompt)
        self.assertIn("评论写法", prompt)
        _, tools = run.build_prompt(on, "scroll", dry_run=True)
        self.assertNotIn("bili_reply", tools)
        _, tools = run.build_prompt(cfg(), "scroll", dry_run=False)
        self.assertNotIn("bili_reply", tools)


class AgentCommandTest(unittest.TestCase):
    def test_claude_and_codex_get_model_effort_and_mcp(self):
        c = cfg(agent={"name": "claude", "model": "opus", "effort": "medium"})
        cmd = run.agent_command(c, Path("ws"), Path("ws/.mcp.json"), Path("p.md"), ["bili_search"])
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertIn("mcp__bili__bili_search", cmd[cmd.index("--allowedTools") + 1])
        self.assertEqual(cmd[cmd.index("--effort") + 1], "medium")
        c = cfg(agent={"name": "codex", "model": "gpt-5.5", "effort": "medium"})
        cmd = run.agent_command(c, Path("ws"), Path("ws/.mcp.json"), Path("p.md"), ["bili_search"])
        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertIn('mcp_servers.bili.default_tools_approval_mode="approve"', cmd)
        self.assertIn('model_reasoning_effort="medium"', cmd)
        self.assertEqual(cmd[-1], "-")


class InboxTest(unittest.TestCase):
    def test_parse_notice(self):
        m = run.parse_notice(notice(123, 7))
        self.assertEqual((m["id"], m["channel"], m["rpid"], m["root"], m["bvid"], m["mid"]),
                         (123, "comment", 123, 123, "BV1xx411c7mD", 7))
        self.assertIsNone(run.parse_notice({"item": {"business_id": 11, "source_id": 1}}))

    def test_parse_dm_skips_own_auto_and_system_messages(self):
        me, owner = 1, 100

        def dm(sender, body, t=2000, mtype=1, source=2):
            return {"sender_uid": sender, "msg_type": mtype, "msg_source": source, "timestamp": t, "msg_key": 9,
                    "content": json.dumps(body, ensure_ascii=False)}
        m = run.parse_dm(dm(owner, {"content": "这个怎么样 https://www.bilibili.com/video/BV1xx411c7mD?p=1"}), me)
        self.assertEqual((m["id"], m["channel"], m["bvid"], m["mid"]), ("dm9", "dm", "BV1xx411c7mD", owner))
        shared = run.parse_dm(dm(owner, {"author": "up", "id": 170001, "source": 5, "title": "视频"}, mtype=7), me)
        self.assertEqual((shared["bvid"], shared["title"]), ("BV17x411w7KC", "视频"))
        self.assertEqual(run.parse_dm(dm(owner, {"content": "看看av170001"}), me)["bvid"], "BV17x411w7KC")
        # A 50-digit av number once crashed aid2bvid on every round. An article card is not a video.
        self.assertEqual(run.parse_dm(dm(5, {"content": "av" + "9" * 50}), me)["bvid"], "")
        self.assertEqual(run.parse_dm(dm(owner, {"id": 170001, "source": 6, "title": "专栏"}, mtype=7), me)["bvid"], "")
        self.assertIsNone(run.parse_dm(dm(me, {"content": "d"}), me))
        self.assertIsNone(run.parse_dm(dm(owner, {"content": "加群"}, source=9), me))
        self.assertIsNone(run.parse_dm(dm(owner, {"content": "加群"}, t=2002), me, bot_times=[2000]))
        self.assertIsNone(run.parse_dm(dm(844424930131964, {"content": "通知"}, source=6), me))

    def test_owner_always_strangers_limited(self):
        owner, me = 100, 1
        msgs = [run.parse_notice(n) for n in
                [notice(1, owner), notice(2, owner), notice(3, 5), notice(4, 5), notice(5, 6), notice(6, me), notice(7, 8, t=10)]]
        state = {}
        todo = run.select_messages(msgs, state, me, owner, stranger_limit=1, today="2026-01-01", since=1000)
        self.assertEqual([(m["rpid"], m["kind"]) for m in todo], [(1, "owner"), (2, "owner"), (3, "stranger")])
        again = run.select_messages(msgs, state, me, owner, stranger_limit=1, today="2026-01-01", since=1000)
        self.assertEqual(again, [])


class ServeTest(unittest.TestCase):
    def test_single_instance(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / "serve.lock"
            first = run.single_instance(lock)
            self.assertIsNotNone(first)
            self.assertIsNone(run.single_instance(lock))
            first.close()
            again = run.single_instance(lock)
            self.assertIsNotNone(again)
            again.close()


class VerifyTest(unittest.TestCase):
    def test_comment_rows(self):
        seen = "- 看过 2026-01-01 BV1xx411c7mD 标题\n- 评论 2026-01-01 BV1xx411c7mD rpid=317681254737 正文\n" \
               "- 评论 2026-01-01 BV1yy411c7mD rpid=未取到 正文\n"
        self.assertEqual(run.comment_rows(seen, "2026-01-01"), [("BV1xx411c7mD", "317681254737")])


if __name__ == "__main__":
    unittest.main()
