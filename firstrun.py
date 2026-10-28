"""Hub Motion Gallery: the question of the first start. The plugin comes with the links to its reference sources; downloading them takes
time and disk, so nothing is downloaded until the owner answers: Download / Don't / I'll change it in the settings.

The same question goes to the page (a card over the plugin, firstrun.js) and to Telegram (a post with the three buttons, tgpost.py reads the
press); the first answer from either place settles it, the other one disappears. The answer is remembered (links.py, "first"): it is not
asked twice; the settings tab can ask it again. The page draws its own text (it has the language table); this file holds the numbers and
the Telegram text.

The links and the agents are the owner's settings (server.py: sources, agents); the plugin brings none, and with none there is no question.
The size and time are estimated per source the downloader reads: about 23 examples (at most 30 a link), 22 MB (a video and its poster, about
0.9 MB) and a minute (2 s per example) each."""

REF = "mg:first"                          # the ref of the Telegram post: a press comes back signed ext:motion-gallery with this ref
CHOICES = ("yes", "no", "settings")
PER_SOURCE = {"items": 23, "mb": 22, "minutes": 1}


def facts(sources, ready):
    """The estimate of a download: sources - the links, ready - how many of them the downloader reads (none: all are counted)."""
    n = ready or sources
    return {k: v * n for k, v in PER_SOURCE.items()}

STR = {
    "en": {
        "title": "Motion Gallery: download the reference videos?",
        "body": "Configured: {sources} sources of motion references - sites and repositories with prompts and videos ({ready} of them are read by the downloader now). Download: about {items} examples, "
                "{mb} MB of disk and {minutes} minutes in the background. Nothing is downloaded until you answer.",
        "agents": "For Motion Gallery to work well, the agents {names} are needed. Not in the hub yet: {missing}. "
                  "Ask the hub to install them, or press Install on the Motion Gallery page.",
        "agents_ok": "The agents {names} are already in the hub.",
        "yes": "Download",
        "no": "Don't download",
        "settings": "I'll change it in the settings",
        "settle": "Motion Gallery references: {}",
    },
    "ru": {
        "title": "Motion Gallery: скачать референсы?",
        "body": "Настроено: {sources} источников референсов моушна: сайты и репозитории с промтами и видео (скачивалка пока читает {ready} из них). Скачка: около {items} примеров, "
                "{mb} МБ на диске и {minutes} минут в фоне. Пока вы не ответите, ничего не скачивается.",
        "agents": "Для нормальной работы Motion Gallery нужны агенты: {names}. В хабе пока нет: {missing}. "
                  "Попросите хаб поставить их или нажмите «Поставить» на странице Motion Gallery.",
        "agents_ok": "Агенты {names} уже в хабе.",
        "yes": "Качаем",
        "no": "Не качаем",
        "settings": "Поменяю в настройках",
        "settle": "Референсы Motion Gallery: {}",
    },
}


def tr(lang, key, **params):
    base = (lang or "en").split("-")[0].lower()
    text = (STR.get(base) or STR["en"]).get(key) or STR["en"][key]
    return text.format(**params) if params else text


def choice_of(button):
    """The answer a pressed button stands for, in any language of the table (the language may have changed since); None - not our button."""
    for c in CHOICES:
        if any(t.get(c) == button for t in STR.values()):
            return c
    return None


def missing(sessions, agents):
    """The agents asked for (settings) that are not in the hub: sessions - the hub state's {name: session}; the hub's own session is not an agent."""
    sessions = sessions if isinstance(sessions, dict) else {}
    return [n for n in agents if n not in sessions or (sessions[n] or {}).get("kind") == "hub"]


def text(lang, sources, ready, lack, agents=()):
    """The Telegram text of the question (the page draws its own from the same facts); the agents part only when the owner named agents."""
    out = f"**{tr(lang, 'title')}**\n{tr(lang, 'body', sources=sources, ready=ready, **facts(sources, ready))}"
    if agents:
        names = ", ".join(agents)
        out += "\n\n" + (tr(lang, "agents", names=names, missing=", ".join(lack)) if lack else tr(lang, "agents_ok", names=names))
    return out
