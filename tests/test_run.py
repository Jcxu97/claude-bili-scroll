import http.client
import json
import random
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import life  # noqa: E402
import run  # noqa: E402
import web  # noqa: E402

# Match main(). The commands print Chinese, which a non-UTF-8 console cannot encode.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(errors="replace")


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

    def test_niche_keywords_get_their_own_play_threshold(self):
        c = cfg(scroll={"niche_keywords": ["酒店评测", "凯悦酒店"], "niche_min_play": 1000})
        prompt, _ = run.build_prompt(c, "scroll", dry_run=True)
        self.assertIn("播放量门槛：100000", prompt)
        self.assertIn("冷门题材的播放量门槛：1000（酒店评测、凯悦酒店）", prompt)
        prompt, _ = run.build_prompt(cfg(), "scroll", dry_run=True)
        self.assertNotIn("冷门题材的播放量门槛", prompt)

    def test_memory_keeps_the_top_of_owner_md(self):
        with tempfile.TemporaryDirectory() as d:
            mem = Path(d) / "memory"
            mem.mkdir()
            (mem / "owner.md").write_text("## 喜欢\n- 酒店评测\n" + "- 别的事\n" * 1100, encoding="utf-8")
            (mem / "topics.md").write_text("- 旧话题\n" * 900 + "- 新话题", encoding="utf-8")
            part = run.memory_part(Path(d))
            self.assertIn("酒店评测", part)
            self.assertIn("新话题", part)


class AgentCommandTest(unittest.TestCase):
    def test_claude_and_codex_get_model_effort_and_mcp(self):
        c = cfg(agent={"name": "claude", "model": "opus", "effort": "medium"})
        cmd = run.agent_command(c, Path("ws"), Path("ws/.mcp.json"), Path("p.md"), ["bili_search"])
        self.assertEqual(cmd[:2], ["claude", "-p"])
        self.assertIn("mcp__bili__bili_search", cmd[cmd.index("--allowedTools") + 1])
        self.assertEqual(cmd[cmd.index("--effort") + 1], "medium")
        # A bare Edit or Write, here or in the user's own settings, would allow every path on the machine.
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertFalse({"Read", "Write", "Edit", "Glob", "Grep"} & set(cmd[cmd.index("--allowedTools") + 1].split()))
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

    def test_qr_login_refuses_the_owner_account(self):
        with tempfile.TemporaryDirectory() as d:
            c = cfg(inbox={"owner_uid": 42}, paths={"data": d})
            cookies = ["SESSDATA=s; Path=/", "bili_jct=j; Path=/", "DedeUserID=42; Path=/"]
            with mock.patch.object(run, "http_json", return_value=({"data": {"code": 0}}, cookies)):
                self.assertEqual(run.login_poll(c, "key"), "owner")
            self.assertFalse(run.cred_file(c).exists())


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


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm).timestamp()


class LifeTest(unittest.TestCase):
    def test_plan_and_state(self):
        plan = life.plan_day(date(2026, 10, 21), cfg()["life"], random.Random(1))  # a Wednesday
        self.assertTrue(at(21, 8, 30) <= plan["wake"] <= at(21, 10, 30))
        self.assertTrue(at(22, 0) <= plan["sleep"] <= at(22, 2))
        for start, end, _ in plan["busy"]:
            self.assertTrue(plan["wake"] < start < end < plan["sleep"])
        self.assertEqual(life.state(plan, at(22, 4)), ("asleep", ""))
        state = {}
        self.assertEqual(life.current_plan(state, cfg()["life"], at(22, 0, 30), random.Random(1))["date"], "2026-10-21")
        self.assertEqual(state["next_inbox"], state["plan"]["wake"])

    def test_proactive_caps_nudge_once_and_quiet_hours(self):
        c = cfg()["life"]

        def bot(t, s, kind="proactive"):
            return {"t": t, "who": "bot", "kind": kind, "session": s}
        owner = {"t": at(21, 12), "who": "owner"}
        self.assertEqual(life.proactive([owner], c, at(21, 14))[0], "share")
        self.assertIsNone(life.proactive([owner], c, at(21, 3))[0])
        chat = [owner, bot(at(21, 12, 30), "a"), bot(at(21, 13), "b")]
        self.assertIsNone(life.proactive(chat, c, at(21, 13, 20))[0])  # 45 minutes apart
        self.assertEqual(life.proactive(chat, c, at(21, 14))[0], "nudge")
        chat.append(bot(at(21, 14), "c", "nudge"))
        self.assertIsNone(life.proactive(chat, c, at(21, 16))[0])
        chat.append({"t": at(21, 16, 10), "who": "owner"})
        self.assertEqual(life.proactive(chat, c, at(21, 17))[0], "share")
        full = [bot(at(21, 10) + i * 60, str(i)) for i in range(10)] + [{"t": at(21, 11), "who": "owner"}]
        self.assertIsNone(life.proactive(full, c, at(21, 20))[0])


class WebTest(unittest.TestCase):
    def test_login_header_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            conf = Path(d) / "config.toml"
            conf.write_text('[web]\npassword = "pw"\n', encoding="utf-8")
            srv = SimpleNamespace(ws=Path(d), config=str(conf), snapshot=lambda: {"state": "awake"})
            httpd = web.start(srv, run, {"host": "127.0.0.1", "port": 0})
            port = httpd.server_address[1]

            def call(method, path, body=None, headers=None):
                h = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                h.request(method, path, json.dumps(body) if body is not None else None, headers or {})
                r = h.getresponse()
                return r.status, r.getheader("Set-Cookie") or "", r.read()
            try:
                self.assertEqual(call("GET", "/api/status")[0], 401)
                self.assertEqual(call("POST", "/api/login", {"password": "pw"})[0], 403)
                self.assertEqual(call("POST", "/api/login", {"password": "no"}, {"X-CBS": "1"})[0], 403)
                code, cookie, _ = call("POST", "/api/login", {"password": "pw"}, {"X-CBS": "1"})
                self.assertEqual(code, 200)
                auth = {"Cookie": cookie.split(";")[0]}
                self.assertEqual(call("GET", "/api/status", headers=auth)[0], 200)
                self.assertEqual(call("GET", "/api/files/journal/..%2Fconfig.toml", headers=auth)[0], 404)
                self.assertEqual(call("GET", "/../config.toml")[0], 404)
                self.assertEqual(call("GET", "/api/status", headers=dict(auth, Host="evil.example"))[0], 403)
                bad = call("PUT", "/api/config", {"text": '[life]\nwake = "9"\n'}, dict(auth, **{"X-CBS": "1"}))
                self.assertEqual(bad[0], 400)
                self.assertIn("password", conf.read_text(encoding="utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
