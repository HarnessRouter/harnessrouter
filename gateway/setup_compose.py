"""New setup's shared rules (docs/uxuidesign/console-87: buildAgent, buildSeq, backendShow): the
parts of the hosted service's composer that its builder (setup_builder) reuses, kept here under the
same names so the two stay one design.

What a person writes a setup should do for their users becomes a harness CONFIGURATION, never a
task: its name, its standing instructions (written for serving each end user's request, never for
building software), the agent harness and the model when the person left them on Auto, what it
attaches, and one example request exactly as an end user would send it. setup_builder writes it;
this module holds what every answer is held to:

  - the person's language, read from the text on this server (detect_language) and named in the
    prompt, never left to the model to work out; an answer in another is asked for again
    (off_language);
  - what Auto may pick (_auto_bases, default_base): an agent harness that takes skills, and with the
    model chosen only one that runs it;
  - each text field cleaned and capped (_line, _block, clean_name), each list held to what was
    offered (_pick).

The hosted service also has a one-call composer route and a request check before the build; both
answer on the platform's own models, which this server does not have, so neither is here: the
builder runs on the instance's own keys (setup_builder), and the console's own words cover a job
that reads like a change to the person's code.
"""
from __future__ import annotations

import re
from typing import NamedTuple

AUTO = "auto"
TOOL = "configure_harness"
# The longest job a build reads (the hosted request check's own cap, which the builder shares).
JOB_MAX = 2000

NAME_MAX = 40
NAME_WORDS = 4
INSTR_MIN = 40
INSTR_MAX = 4000
EXAMPLE_MAX = 500
MAX_SKILLS = 4
MAX_PLUGINS = 4
MAX_NEEDS = 3
# Plugins a person can connect for a workspace themselves, named when a job cannot work without
# one. Not here: Microsoft 365, which comes with the workspace's own Entra application.
CONNECTABLE = ("github", "vercel", "insforge", "browser")
# The media server a harness attaches as one of its servers (_hosted_media_attach), offered as a
# plugin under this id, in the console's own words for it.
MEDIA_ID = "media"
MEDIA = {"name": "Media tools", "about": "Image, video, speech and music generation, plus film assembly."}
_NAME_FILLER = frozenset({"agent", "agents", "bot", "bots", "assistant", "assistants", "harness", "ai"})


class JobEmpty(ValueError):
    pass


class JobTooLong(ValueError):
    pass


class NotOffered(ValueError):
    """The base or model the person chose is not one this server offers them now."""

    def __init__(self, what: str):
        super().__init__(what)
        self.what = what



# The language, named. The rule this replaced named none ("in the language the team wrote in"), and
# with it gpt-6-luna (reasoning off) wrote English jobs in Spanish, all three fields at once: 8 of 90
# runs on three English jobs on the platform's model, 2026-10-19 ("Generate cat images" became
# "Imágenes de gatos" with a Spanish first test 5 times in 30). Named: 0 of 90; no rule at all: 0 of
# 90, which is what a text whose language cannot be named gets.
LANGUAGE_LINE = "\n\nThe team wrote in {name}. Write the name, the instructions and the example in {name}."


# ── the person's language ────────────────────────────────────────────────────────────────────────
class Lang(NamedTuple):
    """A text's language: `code` ("en", "zh-Hans", "ja" ...) and its English `name` when the text says
    which, "" for both when only its writing system is known; `script` ("latn", "cjk", "hang" ...),
    "" for a text with no letters."""
    code: str
    name: str
    script: str


_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "de": "German", "it": "Italian",
          "nl": "Dutch", "vi": "Vietnamese", "pl": "Polish", "tr": "Turkish", "cs": "Czech", "zh": "Chinese",
          "zh-Hans": "Simplified Chinese", "zh-Hant": "Traditional Chinese", "ja": "Japanese", "ko": "Korean",
          "el": "Greek", "he": "Hebrew", "th": "Thai"}
_HAN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA = re.compile("[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL = re.compile("[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
_THAI = re.compile("[\u0e00-\u0e7f]")
_UNSPACED = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f"
                       "\uac00-\ud7af\u1100-\u11ff\u3130-\u318f\u0e00-\u0e7f]")
_LETTERS = re.compile(r"[^\W\d_]+")
# Characters only one of the two Chinese writing standards uses.
_HANT = frozenset("們這說對會時個來為與從種開關問題單據價圖貓處應檔讀書寫語點員號碼傳統體嗎後還進過電話網頁產業務戶發報幫請")
_HANS = frozenset("们这说对会时个来为与从种开关问题单据价图猫处应档读书写语点员号码传统体吗后还进过电话网页产业务户发报帮请")
# A few dozen common words per language written in Latin letters: what tells them apart. A word in
# two lists counts for both.
_WORDS = {
    "en": frozenset("the a an and of to in is are for with that this these our your their my we you they it its on by "
                    "from as at or be each every when then what which who please into about any all can will should".split()),
    "es": frozenset("el la los las de del que y en para con por una un unos su sus es son se al como nuestro nuestra "
                    "nuestros nuestras cada cuando también pero más este esta estos estas sobre desde sin lo le les mi tu".split()),
    "pt": frozenset("o os as do da dos das de que e em para com por uma um seu sua seus suas não você é são nosso nossa "
                    "nossos nossas cada quando também mas mais este esta sobre na nos nas pelo pela".split()),
    "fr": frozenset("le la les des du de que et en pour avec une un est sont vous dans sur au aux nos notre votre chaque "
                    "quand aussi mais plus ce cette ces il elle nous ils pas ne".split()),
    "de": frozenset("der die das und ist sind mit für ein eine einen einem nicht sie zu den dem des von im unsere unser "
                    "unserer unseren jede jeden jedes wenn auch aber mehr auf aus bei nach wir ich sich oder".split()),
    "it": frozenset("il lo gli le di del della dei degli delle che e per con una un è sono nostro nostra nostri nostre "
                    "ogni quando anche ma più questo questa al alla alle non".split()),
    "nl": frozenset("de het een en van voor met op is zijn dat die niet onze ons elke wanneer ook maar meer naar bij uit "
                    "wij ik".split()),
}
# English job words, for the short imperative a job often is ("Generate cat images"): spelled this way
# in no other language listed here.
_EN_JOB = frozenset("generate create make write review reviews answer answers reply replies summarize summarise translate "
                    "draft turn help find check analyze analyse screen flag extract classify convert recommend research "
                    "search read edit fix picture pictures email emails contract contracts clause clauses customer customers "
                    "user users product products report reports order orders invoice invoices meeting meetings cat cats "
                    "dog dogs".split())
# Letters only one language listed here writes.
_MARKS = (("es", "ñ¿¡"), ("pt", "ãõ"), ("de", "ßäö"), ("fr", "ëîïûœ"), ("pl", "ąęłńśźż"), ("tr", "ğı"), ("cs", "ěřů"),
          ("vi", "ơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"))
# How a person names a language in their text ("reply in Spanish", "翻译成英文"): the example may be in it.
_NAMED = {
    "en": ("english", "inglés", "anglais", "englisch", "英文", "英语", "英語"),
    "es": ("spanish", "español", "espanol", "espagnol", "spanisch", "西班牙语", "西班牙語", "スペイン語"),
    "zh": ("chinese", "mandarin", "chino", "chinois", "chinesisch", "中文", "汉语", "漢語", "华语", "華語", "中国語"),
    "ja": ("japanese", "japonés", "japonais", "japanisch", "日本語", "日语", "日文"),
    "ko": ("korean", "coreano", "coréen", "koreanisch", "한국어", "韩语", "韓語", "韓国語"),
    "fr": ("french", "francés", "français", "francais", "französisch", "法语", "法語", "フランス語"),
    "de": ("german", "alemán", "allemand", "deutsch", "德语", "德語", "ドイツ語"),
    "pt": ("portuguese", "portugués", "português", "portugues", "portugais", "葡萄牙语", "葡萄牙語", "ポルトガル語"),
    "it": ("italian", "italiano", "italien", "italienisch", "意大利语", "義大利語", "イタリア語"),
}


def _script_of(ch: str) -> str:
    o = ord(ch)
    if o < 0x250 or 0x1E00 <= o <= 0x1EFF:
        return "latn"
    if 0x370 <= o <= 0x3FF or 0x1F00 <= o <= 0x1FFF:
        return "grek"
    if 0x400 <= o <= 0x52F:
        return "cyrl"
    if 0x590 <= o <= 0x5FF:
        return "hebr"
    if 0x600 <= o <= 0x6FF or 0x750 <= o <= 0x77F or 0x8A0 <= o <= 0x8FF:
        return "arab"
    if 0x900 <= o <= 0x97F:
        return "deva"
    return "other"


def detect_language(text) -> Lang:
    """The language a text is written in, from its letters alone: the writing system most of it uses
    (each Chinese, Japanese or Korean character counts as a word, and a few words in Latin letters
    inside such a text never make it Latin), then, for Latin letters, which language's common words
    and letters it has most of. A text that does not say clearly is named by its writing system only."""
    t = str(text or "")
    han, kana = len(_HAN.findall(t)), len(_KANA.findall(t))
    units = {"cjk": float(han + kana), "hang": float(len(_HANGUL.findall(t))), "thai": len(_THAI.findall(t)) / 3}
    words = [w.lower() for w in _LETTERS.findall(_UNSPACED.sub(" ", t))]
    for w in words:
        s = _script_of(w[0])
        units[s] = units.get(s, 0.0) + 1
    other = max((k for k in units if k != "latn"), key=lambda k: units[k])
    if units.get("latn", 0) > units[other]:
        script = "latn"
    elif units[other] > 0:
        script = other
    else:
        return Lang("", "", "")
    if script == "cjk":
        if kana and kana * 20 >= han + kana:
            return Lang("ja", _NAMES["ja"], "cjk")
        trad, simp = sum(c in _HANT for c in t), sum(c in _HANS for c in t)
        code = "zh-Hant" if trad > simp else "zh-Hans" if simp > trad else "zh"
        return Lang(code, _NAMES[code], "cjk")
    single = {"hang": "ko", "thai": "th", "grek": "el", "hebr": "he"}
    if script in single:
        return Lang(single[script], _NAMES[single[script]], script)
    if script != "latn":
        return Lang("", "", script)          # Cyrillic, Arabic letters, Devanagari: more than one language each
    (best, top), (_, second) = sorted(_latin_scores(t).items(), key=lambda kv: -kv[1])[:2]
    if top > second:
        return Lang(best, _NAMES[best], "latn")
    return Lang("", "", "latn")


def _latin_scores(text: str) -> dict:
    """How much of each language's common words and letters a text in Latin letters has."""
    low = str(text or "").lower()
    latin = [w for w in _LETTERS.findall(_UNSPACED.sub(" ", low)) if _script_of(w[0]) == "latn"]
    score = {k: sum(w in v for w in latin) for k, v in _WORDS.items()}
    score["en"] += sum(w in _EN_JOB for w in latin)
    for k, marks in _MARKS:
        score[k] = score.get(k, 0) + sum(low.count(m) for m in marks)
    return score


def named_languages(text) -> frozenset:
    """The languages a text names ("reply in Spanish", "翻译成英文")."""
    low = str(text or "").lower()
    out = set()
    for code, names in _NAMED.items():
        for n in names:
            if (re.search(rf"(?<![^\W\d_]){re.escape(n)}(?![^\W\d_])", low) if n.isascii() else n in low):
                out.add(code)
                break
    return frozenset(out)


def _same(a: str, b: str) -> bool:
    """The same language: "zh" is either Chinese standard, "zh-Hans" never "zh-Hant"."""
    pa, pb = a.split("-"), b.split("-")
    return pa[0] == pb[0] and (len(pa) == 1 or len(pb) == 1 or pa[1] == pb[1])


def speaks(text, want: Lang, *, short: bool = False, also: frozenset = frozenset()) -> bool:
    """Whether a text is in `want`'s language (or one of `also`): False only when the text shows another.
    A short text may be a Japanese one written all in kanji."""
    got = detect_language(text)
    if not want.script or not got.script:
        return True
    if got.code and any(_same(got.code, a) for a in also):
        return True
    if got.script != want.script:
        return False
    if want.script == "latn" and want.code in _WORDS:
        # more of another language's words than of the person's, even where the words alone cannot
        # say which ("Revisión de contratos": de is Spanish, Portuguese, French and Dutch)
        score = _latin_scores(text)
        mine = score.get(want.code, 0)
        return not any(v > mine for k, v in score.items() if k != want.code and not any(_same(k, a) for a in also))
    if not want.code or not got.code or _same(got.code, want.code):
        return True
    return short and want.code == "ja" and got.code.startswith("zh")


def off_language(cfg: dict, want: Lang, also: frozenset = frozenset()) -> str:
    """The first of a configuration's texts in another language than the person's, or ""."""
    if not speaks(cfg.get("name"), want, short=True):
        return "name"
    if not speaks(cfg.get("instructions"), want):
        return "instructions"
    if not speaks(cfg.get("exampleTask"), want, also=also):
        return "example"
    return ""


# ── the catalog, as the model is shown it ────────────────────────────────────────────────────────
def _auto_bases(cat: dict, model_req: str) -> list[str]:
    """The bases Auto may pick: general agent harnesses (the ones that take skills), and, when the
    person chose the model, only those that run it."""
    out = [b for b, x in cat["bases"].items() if x.get("auto")]
    if model_req != AUTO:
        out = [b for b in out if model_req in cat["bases"][b]["models"]]
    return out


def default_base(cat: dict, among: list[str]) -> str:
    want = str(cat.get("default_base") or "")
    return want if want in among else (among[0] if among else "")



# ── the answer, checked ──────────────────────────────────────────────────────────────────────────
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _line(v, cap: int) -> str:
    return " ".join(_CTRL.sub(" ", str(v or "")).split())[:cap].strip()


def _block(v, cap: int) -> str:
    """Multi-line text kept as written, control characters out, at most `cap` characters, cut at the
    last sentence or line end before the cap when there is one."""
    s = _CTRL.sub(" ", str(v or "")).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(x.rstrip() for x in s.split("\n"))).strip()
    if len(s) <= cap:
        return s
    cut = s[:cap]
    at = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("\n"))
    return (cut[:at + 1] if at > cap // 2 else cut).strip()


def clean_name(v) -> str:
    """2 to 4 words, no quotes or trailing punctuation, none of the filler words a model reaches for."""
    s = _line(v, 120).replace("—", " ").replace("–", " ")
    words = [w.strip("\"'“”‘’.,:;!?()[]") for w in s.split()]
    words = [w for w in words if w and w != "-"]
    kept = [w for w in words if w.lower() not in _NAME_FILLER] or words
    n = " ".join(kept[:NAME_WORDS])[:NAME_MAX].strip()
    return n[:1].upper() + n[1:] if n else ""


def _pick(vals, allowed: dict, cap: int, skip: set | None = None) -> list[str]:
    out: list[str] = []
    for v in vals if isinstance(vals, list) else []:
        k = str(v or "").strip()
        if k in allowed and k not in out and k not in (skip or set()):
            out.append(k)
    return out[:cap]


class BadAnswer(ValueError):
    pass


class Refused(Exception):
    """The provider answered with something other than 200: its status is all that is kept."""

    def __init__(self, status: int):
        super().__init__(f"status {status}")
        self.status = status


class OffLanguage(BadAnswer):
    """An answer with a text in another language than the person's: which one is all that is kept."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field

