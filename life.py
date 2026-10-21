"""The bot's day: when it sleeps, when it is busy, when it browses, and when it may message the owner first.

serve owns the state and saves it to data/life.json. Everything here takes `now` as epoch seconds,
so the rules can be tested without waiting for a real day.
"""
import json
import random
from datetime import date, datetime, timedelta

BUSY_REASONS = ["在看书", "在写东西", "出门了", "在发呆", "在整理收藏夹", "在打游戏", "在听歌"]
BINGE_CHANCE = 0.3


def minutes(text):
    h, m = (int(x) for x in str(text).split(":"))
    return h * 60 + m


def plan_day(day, cfg, rng):
    """Draw the wake time, the sleep time and a few busy blocks for one day. Sleep can be after midnight."""
    shift = int(cfg["weekend_shift"]) if day.weekday() >= 5 else 0
    midnight = datetime.combine(day, datetime.min.time())
    wake_m, sleep_m = minutes(cfg["wake"]), minutes(cfg["sleep"])
    if sleep_m <= wake_m:
        sleep_m += 24 * 60

    def drift():
        return max(-60.0, min(60.0, rng.gauss(0, 25)))
    wake = midnight + timedelta(minutes=wake_m + shift + drift())
    sleep = midnight + timedelta(minutes=sleep_m + shift + drift())
    busy = []
    for _ in range(rng.randint(1, 3)):
        start = wake + timedelta(minutes=rng.uniform(60, max(61, (sleep - wake).total_seconds() / 60 - 120)))
        end = start + timedelta(minutes=rng.uniform(30, 120))
        if end < sleep and not any(s <= end.timestamp() and start.timestamp() <= e for s, e, _ in busy):
            busy.append([start.timestamp(), end.timestamp(), rng.choice(BUSY_REASONS)])
    return {"date": day.isoformat(), "wake": wake.timestamp(), "sleep": sleep.timestamp(), "busy": sorted(busy)}


def current_plan(life, cfg, now, rng):
    """Return the plan that covers `now`, making new ones as days pass. 00:30 still belongs to yesterday."""
    plan = life.get("plan")
    if not plan:
        t = datetime.fromtimestamp(now)
        day = t.date() if t.hour >= 5 else t.date() - timedelta(days=1)
        plan = plan_day(day, cfg, rng)
    while now >= plan["sleep"]:
        plan = plan_day(date.fromisoformat(plan["date"]) + timedelta(days=1), cfg, rng)
    if plan is not life.get("plan"):
        life.update(plan=plan, next_session=plan["wake"] + rng.uniform(20, 60) * 60, next_inbox=plan["wake"])
    return plan


def state(plan, now):
    """asleep, busy (with a reason) or awake. serve reports browsing itself, because it knows the job runs."""
    if now < plan["wake"] or now >= plan["sleep"]:
        return "asleep", ""
    for start, end, why in plan["busy"]:
        if start <= now < end:
            return "busy", why
    return "awake", ""


def after_session(life, now, rng):
    life["next_session"] = now + rng.uniform(60, 200) * 60


def session_style(rng):
    return "long" if rng.random() < BINGE_CHANCE else "short"


def inbox_delay(st, every, rng):
    """Seconds until the next message check. She does not always answer at once."""
    if st == "browsing":
        return rng.uniform(8, 20) * 60
    if st == "busy":
        return rng.uniform(15, 40) * 60
    return every * 60


def in_quiet(now, quiet):
    """True inside the owner's sleep hours, for example ["01:00", "09:00"]."""
    t = datetime.fromtimestamp(now)
    m, start, end = t.hour * 60 + t.minute, minutes(quiet[0]), minutes(quiet[1])
    return start <= m < end if start <= end else (m >= start or m < end)


def proactive(chat, cfg, now):
    """May the bot message the owner first? Return (mode, reason). mode is "share", "nudge" or None.

    A contact is one session that sent at least one message. After 2 contacts without an answer the bot
    may send one gentle nudge, then it waits until the owner writes again.
    """
    if in_quiet(now, cfg["owner_quiet"]):
        return None, "主号在睡觉"
    first = {}
    for e in chat:
        if e.get("who") == "bot" and e.get("kind") in ("proactive", "nudge"):
            first.setdefault(e.get("session"), e["t"])
    starts = sorted(first.values())
    day_start = datetime.combine(datetime.fromtimestamp(now).date(), datetime.min.time()).timestamp()
    if sum(t >= day_start for t in starts) >= int(cfg["max_contacts_per_day"]):
        return None, "今天已经找过主号很多次了"
    if starts and now - starts[-1] < int(cfg["min_gap_minutes"]) * 60:
        return None, "刚找过主号"
    last_owner = max((e["t"] for e in chat if e.get("who") == "owner"), default=0)
    after = [e for e in chat if e.get("who") == "bot" and e.get("kind") in ("proactive", "nudge") and e["t"] > last_owner]
    if any(e["kind"] == "nudge" for e in after):
        return None, "已经催过一次了，等主号回"
    if len({e.get("session") for e in after}) >= 2:
        return "nudge", "主号连着两次没回"
    return "share", ""


def share_feedback(chat, limit=8, window=6 * 3600):
    """The last few contacts and whether the owner answered within a few hours."""
    owner_times = [e["t"] for e in chat if e.get("who") == "owner"]
    out, seen = [], set()
    for e in reversed(chat):
        if e.get("who") == "bot" and e.get("kind") in ("proactive", "nudge") and e.get("session") not in seen:
            seen.add(e.get("session"))
            answered = any(e["t"] < t <= e["t"] + window for t in owner_times)
            out.append({"t": e["t"], "text": e.get("text", "")[:60], "answered": answered})
            if len(out) >= limit:
                break
    return list(reversed(out))


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_chat(path, days=14):
    cutoff = datetime.now().timestamp() - days * 86400
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("t", 0) >= cutoff:
            out.append(e)
    return sorted(out, key=lambda e: e["t"])


def append_chat(path, entry):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def new_rng():
    return random.Random()
