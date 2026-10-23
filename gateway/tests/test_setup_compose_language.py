"""New setup's builder writes in the person's language (setup_compose.detect_language, speaks,
off_language): read on the server from the text itself and named in the prompt, never left to the
model. The rule it replaced on the hosted service named no language, and gpt-6-luna wrote English jobs
in Spanish ("Revisión de contratos", a Spanish first test) 8 times in 90 (2026-10-19). Imports the
builder's modules alone: no gateway."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup_builder as sb  # noqa: E402
import setup_compose as sx  # noqa: E402

CAT = {"bases": {"hermes": {"name": "Hermes", "default": "gpt-5.4", "models": ["gpt-5.4"], "skills": True, "auto": True}},
       "default_base": "hermes", "skills": {}, "plugins": {}, "connect": {}}


@pytest.mark.parametrize("text, code", [
    # the jobs that came back in Spanish, and the console's own demos
    ("Help with contracts", "en"),
    ("Generate cat images", "en"),
    ("Review this SaaS contract clause from the customer side. List each risk with a severity, then say Sign, "
     "Negotiate or Reject.", "en"),
    ("Answer support emails in our tone.", "en"),
    # other languages
    ("根据用户描述的场景，为每位用户生成一张猫咪图片。", "zh-Hans"),
    ("請幫我們的客戶審核合約，找出風險條款。", "zh-Hant"),
    ("お客様から届いた問い合わせメールを読んで、丁寧な日本語で返信の下書きを作成してください。", "ja"),
    ("고객 문의 이메일에 답장을 작성해 주세요", "ko"),
    ("Responde los correos de soporte de nuestros clientes con el tono de nuestra marca.", "es"),
    ("Responda os e-mails de suporte dos nossos clientes com o tom da nossa marca.", "pt"),
    ("Répondez aux e-mails du support de nos clients avec le ton de notre marque.", "fr"),
    ("Beantworte Support-E-Mails unserer Kunden im Ton unserer Marke.", "de"),
    ("Rispondi alle email di supporto dei nostri clienti con il tono del nostro marchio.", "it"),
    # Chinese with English terms is Chinese; English with a Chinese name in it is English
    ("帮用户 review 他们的 SaaS contract，找出 risky clauses，并给出 negotiation suggestions。", "zh-Hans"),
    ("Answer questions about our 小红书 posts", "en"),
])
def test_the_language_is_read_from_the_text(text, code):
    got = sx.detect_language(text)
    assert got.code == code and got.name == sx._NAMES[code]


@pytest.mark.parametrize("text, script", [
    ("Revisar contratos", "latn"),          # no word that says which language: named by its letters only
    ("Отвечай на письма клиентов", "cyrl"),   # Cyrillic is more than one language
    ("", ""), ("12345 !!!", ""),
])
def test_a_text_that_does_not_say_is_named_by_its_letters_only(text, script):
    assert sx.detect_language(text) == sx.Lang("", "", script)


def test_the_two_chinese_standards_share_no_character():
    assert not (sx._HANT & sx._HANS)


def test_the_prompt_names_the_language_and_says_nothing_when_it_cannot():
    def system(text):
        return sb.system(CAT, "auto", "auto", sx.detect_language(text))
    assert system("Generate cat images").endswith(
        "The team wrote in English. Write the name, the instructions and the example in English.")
    assert "The team wrote in Simplified Chinese." in system("根据用户描述的场景生成猫咪图片")
    assert "The team wrote in Japanese." in system("お客様のメールに返信してください")
    unnamed = system("Revisar contratos")
    assert "The team wrote in" not in unnamed and "{language}" not in unnamed
    assert "the language the team wrote in" not in unnamed            # the rule that named none is gone


def test_the_check_catches_the_answers_measured_in_spanish():
    en = sx.detect_language("Help with contracts")
    assert not sx.speaks("Revisión de contratos", en, short=True)
    assert not sx.speaks("Imágenes de gatos", en, short=True)
    assert not sx.speaks("Genera una imagen de un gato naranja dormido en una ventana soleada, con estilo de "
                         "ilustración de cuento.", en)
    assert sx.speaks("Contract reviews", en, short=True)
    assert sx.speaks("Create a cozy watercolor illustration of an orange cat asleep on a sunny windowsill.", en)
    assert sx.speaks("Message screening", en, short=True)              # no word says otherwise


def test_the_check_holds_each_language_to_itself():
    es = sx.detect_language("Responde los correos de soporte de nuestros clientes")
    zh = sx.detect_language("根据用户描述的场景生成猫咪图片")
    ja = sx.detect_language("お客様のメールに返信してください")
    assert sx.speaks("Respuestas de soporte", es, short=True) and sx.speaks("Hola, ¿dónde está mi pedido?", es)
    assert not sx.speaks("Hi, where is my order?", es)
    assert sx.speaks("猫咪场景图", zh, short=True) and sx.speaks("SaaS 合同审阅", zh, short=True)
    assert not sx.speaks("Cat images", zh, short=True) and not sx.speaks("Please make a picture of a cat", zh)
    assert not sx.speaks("請幫我們的客戶審核合約，找出風險條款。", zh)   # Traditional for a Simplified text
    assert sx.speaks("返信下書き", ja, short=True) and sx.speaks("契約審査", ja, short=True)   # a name all in kanji
    assert not sx.speaks("请帮我审阅这份合同并给出修改建议。", ja)          # but not a Chinese request


def test_the_example_may_be_in_a_language_the_person_names():
    job = "Reply to our customers' emails in Spanish."
    assert sx.named_languages(job) == {"es"}
    assert sx.named_languages("把客户的中文邮件翻译成英文") == {"zh", "en"}
    assert sx.named_languages("Help with contracts") == frozenset()
    en = sx.detect_language(job)
    cfg = {"name": "Support replies", "instructions": "You draft replies to customer emails. Write each reply in Spanish.",
           "exampleTask": "Hola, mi pedido no ha llegado. ¿Pueden ayudarme?"}
    assert sx.off_language(cfg, en, sx.named_languages(job)) == ""
    assert sx.off_language(cfg, en) == "example"
    assert sx.off_language({**cfg, "name": "Respuestas de soporte"}, en, sx.named_languages(job)) == "name"


def test_a_text_without_letters_is_never_off():
    en = sx.detect_language("Help with contracts")
    assert sx.speaks("", en) and sx.speaks("#4821", en)
    assert sx.speaks("anything", sx.Lang("", "", ""))
