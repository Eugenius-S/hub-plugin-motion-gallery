"""Hub Motion Gallery in Telegram: the question of the first start (firstrun.py) goes to Telegram as a post with three buttons; a press comes
back to the plugin and settles it, an answer on the page erases the post (linkctl.py asks for telegram.unpost).

It works only on a hub whose Telegram bot knows the telegram.post fact (modules/telegram/design_posts.py is where this hub keeps its rules for
posts of extensions); no such module - nothing is sent, and the question lives on the page only. It reads the journal with its own offset and
does not touch the core. Texts are in the hub language (core.i18n.current()), read when sent."""
import json
import os
import sys
import time

import firstrun

EXT = "motion-gallery"   # the facts are signed ext:motion-gallery - the bot passes presses back by this name
TICK = 2                 # s between journal reads


def _lang():
    try:
        from core import i18n
        return i18n.current()
    except Exception:
        return (os.environ.get("HUB_LANG") or "en").split("-")[0].lower()


def rules():
    """The bot's rule for posts of extensions (modules/telegram/design_posts.py); None - this hub's bot does not have it."""
    try:
        from modules.telegram import design_posts
        return design_posts
    except Exception:
        return None


class Poster:
    """ask() -> linkctl.Ctl; state() -> the hub state (sessions); emit(type, data) - a fact."""

    def __init__(self, state_dir, ask, state=None, emit=None):
        from core import journal
        self.journal = journal
        self.dir, self.path = state_dir, os.path.join(state_dir, "journal.jsonl")
        self.mine = os.path.join(state_dir, EXT, "telegram.json")
        self.ask = ask
        self.state = state or (lambda: journal.load_state(state_dir))
        self.emit = emit or self.spool
        try:
            with open(self.mine, encoding="utf-8") as f:
                self.st = json.load(f)
        except (OSError, ValueError):
            self.st = None
        self.ino, self.offset = journal.identity(self.path), self.size()
        if self.st is None:   # first start - from the end of the journal: old presses do not come again
            last = journal.read_tail(self.path)
            self.st = {"seq": last[-1]["seq"] if last else 0}
            self.save()
        else:   # while it was down - catch up from the journal tail
            self.handle(journal.read_tail(self.path))

    def size(self):
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def save(self):
        os.makedirs(os.path.dirname(self.mine), exist_ok=True)
        tmp = self.mine + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.st, f)
        os.replace(tmp, self.mine)

    def spool(self, type, data):
        from core import spool
        spool.put(os.path.join(self.dir, "spool"), type, None, data, src=f"ext:{EXT}")

    def handle(self, events):
        changed = False
        for ev in events:
            if not isinstance(ev, dict) or not isinstance(ev.get("seq"), int) or ev["seq"] <= self.st["seq"]:
                continue
            self.st["seq"] = ev["seq"]
            changed = True
            try:
                self.react(ev)
            except Exception as e:   # one bad event does not stop the rest
                sys.stderr.write(f"motion-gallery: telegram: {ev.get('type')} {ev['seq']}: {e}\n")
        if changed:
            self.save()

    def react(self, ev):
        data = ev.get("data") or {}
        if ev.get("type") != "telegram.pressed" or data.get("ext") != EXT or ev.get("src") != "telegram" or str(data.get("ref") or "") != firstrun.REF:
            return
        choice, ctl = firstrun.choice_of(data.get("button")), self.ask()
        if choice and ctl:
            ctl.answer(choice, via="tg")

    def first_question(self):
        """The question goes to Telegram once (and again when the settings tab asks it again): only where the bot knows the post."""
        ctl = self.ask()
        facts = ctl.to_post() if ctl else None
        if not facts or not rules():
            return
        lang = _lang()
        lack = firstrun.missing((self.state() or {}).get("sessions"), facts["agents"])
        self.emit("telegram.post", {"text": firstrun.text(lang, facts["sources"], facts["ready"], lack, facts["agents"]), "ref": firstrun.REF, "settle": firstrun.tr(lang, "settle"),
                                    "buttons": [firstrun.tr(lang, c) for c in firstrun.CHOICES], "bump": True})
        ctl.mark_posted()

    def poll(self):
        ino = self.journal.identity(self.path)
        if ino != self.ino or self.size() < self.offset:   # the journal was started anew - read the new one from the start
            self.ino, self.offset = ino, 0
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return
        end = chunk.rfind(b"\n")
        events = []
        if end >= 0:
            self.offset += end + 1
            for line in chunk[:end].split(b"\n"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        self.handle(events)
        self.first_question()


def run(state_dir, ask):
    """The process loop (a thread of server.py). No core nearby (not under a hub) - returns at once."""
    try:
        p = Poster(state_dir, ask)
    except Exception as e:
        sys.stderr.write(f"motion-gallery: telegram posts are off ({e})\n")
        return
    while True:
        try:
            p.poll()
        except Exception as e:
            sys.stderr.write(f"motion-gallery: telegram: {e}\n")
        time.sleep(TICK)
