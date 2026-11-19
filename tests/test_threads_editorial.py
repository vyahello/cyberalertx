"""The Threads editorial writer (threads/editorial.py): an evidence-checked,
bilingual post per story. The language model drafts; deterministic gates decide.
A draft that fails factual accuracy, evidence integrity or EN/UA equivalence is
never published."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.threads import editorial as E
from cyberalertx.threads.format import TEXT_LIMIT, threads_length
from tests.test_threads import FakeThreads, go, source_for, tj, world
from tests.test_publication import item

HEAD = "Attackers Used Optimizely to Test Malware on Top Websites"
TEXT = ("At least 178 top websites, including the BBC, CNN and Zoom, served malware through a security "
        "vulnerability involving Optimizely, a testing platform. Equifax and Ledger were among the affected sites. "
        "Experts say few popular sites strictly limit which sources can supply third-party content.")

GOOD: dict[str, Any] = {
    "status": "confirmed_incident",
    "en": {"hook": "178 top websites served malware through one third-party testing platform.",
           "what": "The BBC, CNN, Zoom, Equifax and Ledger were among them; the code arrived through a security "
                   "vulnerability involving Optimizely.",
           "why": "Few popular sites strictly limit which sources can supply third-party content, so one supplier "
                  "reaches every page that loads it.",
           "advice": ""},
    "ua": {"hook": "178 популярних сайтів поширювали шкідливий код через одну сторонню платформу.",
           "what": "Серед них BBC, CNN, Zoom, Equifax і Ledger; код потрапив через вразливість, пов'язану з "
                   "Optimizely.",
           "why": "Мало популярних сайтів суворо обмежують, хто може постачати сторонній контент, тож один "
                  "постачальник досягає кожної сторінки, що його завантажує.",
           "advice": ""},
    "facts": [{"claim_en": "178 sites served malware", "claim_ua": "178 сайтів",
               "quote": "At least 178 top websites, including the BBC, CNN and Zoom, served malware"}],
    "names": [{"en": "Optimizely", "ua": "Optimizely"}],
}


def ev(**kw: Any) -> E.Evidence:
    base: dict[str, Any] = dict(article_id="a1", outlet="Krebs on Security", headline=HEAD, text=TEXT,
                                url="https://krebsonsecurity.com/x", published_at="2026-11-18T12:00:00+00:00",
                                edition_titles=("Optimizely flaw let attackers serve malware on 178 sites",
                                                "Через Optimizely 178 сайтів поширювали шкідливий код"),
                                image_alt={"en": "Illustration: a browser window served malicious code.",
                                           "ua": "Ілюстрація: вікно браузера зі шкідливим кодом."})
    base.update(kw)
    return E.Evidence(**base)


def draft(**changes: Any) -> E.DraftResponse:
    d = copy.deepcopy(GOOD)
    for path, value in changes.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return E.DraftResponse.model_validate(d)


def problems(review: E.Review, gate: str) -> str:
    return " | ".join(review.problems[gate])


def test_a_good_draft_passes_every_hard_gate() -> None:
    r = E.check(draft(), ev())
    assert r.flat() == [] and r.publishable, r.flat()
    for gate, floor in E.GATES.items():
        assert r.scores[gate] >= floor, gate
    assert all(n <= TEXT_LIMIT for n in r.lengths.values())


def test_composed_post_is_native_threads_with_concise_attribution() -> None:
    text = E.compose(draft(), "en", outlet="Krebs on Security", url="https://cyberalertx.com/en/news/a1")
    paras = text.split("\n\n")
    assert paras[0] == GOOD["en"]["hook"] and paras[0] != HEAD                       # hook, not the headline
    assert paras[-1] == "Reporting: Krebs on Security\nhttps://cyberalertx.com/en/news/a1"
    assert "#" not in text and len(paras) == len(set(paras))                           # no hashtags, no repeats
    ua = E.compose(draft(), "ua", outlet="Krebs on Security", url="https://cyberalertx.com/ua/news/a1")
    assert ua.split("\n\n")[-1].startswith("Джерело: Krebs on Security")


# ---------------------------------------------------------------- factual accuracy

def test_a_number_the_source_does_not_give_fails_accuracy() -> None:
    r = E.check(draft(en__hook="187 top websites served malware through one third-party testing platform.",
                      ua__hook="187 популярних сайтів поширювали шкідливий код через одну сторонню платформу."), ev())
    assert "number '187'" in problems(r, "accuracy") and r.scores["factual_accuracy"] < 5 and not r.publishable


def test_an_organisation_the_source_does_not_name_fails_accuracy() -> None:
    r = E.check(draft(en__what="The BBC, CNN and Netflix were among them; the code arrived through Optimizely.",
                      ua__what="Серед них BBC, CNN і Netflix; код потрапив через Optimizely."), ev())
    assert "'Netflix' is not in the source" in problems(r, "accuracy") and not r.publishable


def test_a_cve_the_source_does_not_give_fails_accuracy() -> None:
    r = E.check(draft(en__what="CVE-2026-1111 in Optimizely let the BBC, CNN and Zoom serve malware.",
                      ua__what="CVE-2026-1111 в Optimizely змусила BBC, CNN і Zoom поширювати шкідливий код."), ev())
    assert "CVE-2026-1111" in problems(r, "accuracy")


def test_a_fact_must_be_quoted_verbatim_from_the_source() -> None:
    r = E.check(draft(facts=[{"claim_en": "x", "claim_ua": "x", "quote": "Optimizely confirmed the hack"}]), ev())
    assert "not quoted from the source" in problems(r, "integrity") and r.scores["evidence_integrity"] < 5


# ---------------------------------------------------------------- EN/UA equivalence

def test_en_and_ua_listing_different_organisations_fail_equivalence() -> None:
    """The baseline test posts named different sites in EN and UA."""
    r = E.check(draft(ua__what="Серед них BBC, CNN і Zoom; код потрапив через вразливість, пов'язану з Optimizely."),
                ev())
    assert "'Equifax' is in EN but not in UA" in problems(r, "equivalence")
    assert r.scores["en_ua_equivalence"] < 5 and not r.publishable


def test_en_and_ua_with_different_numbers_fail_equivalence() -> None:
    r = E.check(draft(ua__hook="Понад 170 популярних сайтів поширювали шкідливий код."), ev(text=TEXT + " 170."))
    assert "numbers differ" in problems(r, "equivalence") and not r.publishable


def test_advice_in_one_language_only_fails_equivalence() -> None:
    src = TEXT + " Site administrators should review which third-party scripts their pages load."
    r = E.check(draft(en__advice="Site administrators: review which third-party scripts your pages load.",
                      advice_quote="Site administrators should review which third-party scripts their pages load."),
                ev(text=src))
    assert "advice present in one language only" in problems(r, "equivalence")


def test_established_ukrainian_names_count_as_the_same_organisation() -> None:
    src = "The FBI and Ukrainian police arrested 4 suspects tied to $40.5 million in ransom payments."
    d = draft(en__hook="Four suspects arrested over ransomware payments worth more than $40.5 million.",
              en__what="The FBI and Ukrainian police made the 4 arrests.",
              en__why="Arrests disrupt the people behind the payments, not only the servers.",
              ua__hook="Чотирьох підозрюваних затримали через викупи на понад $40.5 млн.",
              ua__what="4 затримання провели ФБР і українська поліція.",
              ua__why="Арешти б'ють по людях, які стоять за платежами, а не лише по серверах.",
              facts=[{"claim_en": "4 arrests", "claim_ua": "4", "quote": "arrested 4 suspects"}],
              names=[{"en": "FBI", "ua": "ФБР"}], status="law_enforcement_action")
    r = E.check(d, ev(headline="FBI, Ukraine arrest ransomware suspects", text=src, image_alt={},
                      edition_titles=()))
    assert problems(r, "equivalence") == "", r.flat()


# ---------------------------------------------------------------- status integrity

CLAIM_HEAD = "NVIDIA investigating Gentlemen ransomware breach claims"
CLAIM_TEXT = ("NVIDIA is investigating claims by the Gentlemen ransomware gang that it breached the company and "
              "stole data. The gang listed NVIDIA on its data leak site.")


def claim_ev() -> E.Evidence:
    return ev(headline=CLAIM_HEAD, text=CLAIM_TEXT, outlet="BleepingComputer", edition_titles=(),
              image_alt={"en": "Illustration: a dossier marked 'NVIDIA'.", "ua": "Ілюстрація: досьє «NVIDIA»."})


def claim_draft(**kw: Any) -> E.DraftResponse:
    base: dict[str, Any] = dict(
        status="alleged_claim",
        en__hook="A ransomware gang says it breached NVIDIA; the company has not confirmed it.",
        en__what="NVIDIA is investigating claims by the Gentlemen gang, which listed it on its data leak site.",
        en__why="A leak-site listing is the gang's assertion, not evidence that data was taken.",
        ua__hook="Банда вимагачів заявляє про злам NVIDIA; компанія цього не підтвердила.",
        ua__what="NVIDIA розслідує заяви банди Gentlemen, яка додала компанію на свій сайт витоків.",
        ua__why="Запис на сайті витоків - це твердження банди, а не доказ, що дані викрали.",
        facts=[{"claim_en": "investigating", "claim_ua": "розслідує", "quote": "NVIDIA is investigating claims"}],
        names=[{"en": "NVIDIA", "ua": "NVIDIA"}, {"en": "Gentlemen", "ua": "Gentlemen"}])
    base.update(kw)
    return draft(**base)


def test_an_alleged_breach_stays_alleged() -> None:
    r = E.check(claim_draft(), claim_ev())
    assert r.publishable, r.flat()


def test_an_investigation_into_claims_is_not_a_confirmed_breach() -> None:
    r = E.check(claim_draft(status="confirmed_incident"), claim_ev())
    assert "reports as a claim/investigation" in problems(r, "integrity") and not r.publishable
    r = E.check(claim_draft(en__hook="NVIDIA confirmed a breach by the Gentlemen ransomware gang.",
                            en__what="The Gentlemen gang stole data from NVIDIA.",
                            ua__what="Банда Gentlemen викрала дані NVIDIA."), claim_ev())
    assert "says 'confirmed'" in problems(r, "integrity") and not r.publishable


def test_a_vulnerability_disclosure_is_not_exploitation() -> None:
    src = "PHP warns of critical security flaws affecting all supported versions. Fixes are due on 19 November."
    d = draft(status="fix_announced",
              en__hook="Critical PHP flaws affect all supported versions, with fixes due on 19 November.",
              en__what="The PHP project warned about the flaws and has scheduled fixes; they are actively exploited.",
              en__why="Until the fixes ship, every supported branch carries the same exposure.",
              ua__hook="Критичні вади PHP зачіпають усі підтримувані версії; виправлення - 19 листопада.",
              ua__what="Проєкт PHP попередив про вади й запланував виправлення.",
              ua__why="Доки виправлення не вийдуть, кожна підтримувана гілка має той самий ризик.",
              facts=[{"claim_en": "all versions", "claim_ua": "усі", "quote": "affecting all supported versions"}],
              names=[{"en": "PHP", "ua": "PHP"}])
    r = E.check(d, ev(headline="PHP warns of critical flaws", text=src, edition_titles=(),
                      image_alt={"en": "Illustration: a security advisory for PHP, marked 'CRITICAL'.",
                                 "ua": "Ілюстрація: бюлетень безпеки для PHP з позначкою «CRITICAL»."}))
    assert "describes exploitation the source does not report" in problems(r, "integrity") and not r.publishable


def test_exploitation_reported_by_the_source_may_be_stated() -> None:
    src = "A critical Apache Roller RCE flaw is under active exploitation and needs no authentication."
    d = draft(status="exploited_in_the_wild",
              en__hook="An Apache Roller flaw needing no login is under active exploitation.",
              en__what="Attackers are exploiting the critical Apache Roller RCE flaw without authentication.",
              en__why="No credentials stand between an attacker and code execution on an exposed server.",
              ua__hook="Ваду Apache Roller, яка не потребує входу, активно експлуатують.",
              ua__what="Зловмисники активно експлуатують критичну RCE-ваду Apache Roller без автентифікації.",
              ua__why="Між нападником і виконанням коду на відкритому сервері немає жодних облікових даних.",
              facts=[{"claim_en": "exploited", "claim_ua": "експлуатують", "quote": "under active exploitation"}],
              names=[{"en": "Apache Roller", "ua": "Apache Roller"}])
    r = E.check(d, ev(headline="Apache Roller RCE under active exploitation", text=src, edition_titles=(),
                      image_alt={}))
    assert problems(r, "integrity") == "", r.flat()


# ---------------------------------------------------------------- time and advice

@pytest.mark.parametrize("en,ua", [
    ("in the past day", "за останню добу"), ("today", "сьогодні"), ("yesterday", "вчора"), ("this week", "цього тижня")])
def test_relative_time_is_rejected_in_both_languages(en: str, ua: str) -> None:
    r = E.check(draft(en__why=f"Sites were hit {en}.", ua__why=f"Сайти зазнали атаки {ua}."), ev())
    assert any(x.startswith("en:") for x in r.problems["time"]) and any(x.startswith("ua:") for x in r.problems["time"])
    assert r.scores["evidence_integrity"] < 5 and not r.publishable


@pytest.mark.parametrize("advice", [
    "Users: run an antivirus scan.", "Visitors: reset your passwords.", "Owners: factory reset the device.",
    "Admins: patch now.", "Developers: rotate your credentials.", "Admins: disable the plugin."])
def test_unsupported_remediation_is_rejected(advice: str) -> None:
    r = E.check(draft(en__advice=advice, ua__advice="Порада.", advice_quote="served malware"), ev())
    assert "unsupported advice" in problems(r, "integrity") and not r.publishable


def test_advice_needs_a_source_quote() -> None:
    src = TEXT + " Site administrators should review which third-party scripts their pages load."
    r = E.check(draft(en__advice="Site administrators: review which third-party scripts your pages load.",
                      ua__advice="Адміністраторам сайтів: перевірте, які сторонні скрипти завантажують сторінки."),
                ev(text=src))
    assert "advice without a source quote" in problems(r, "integrity")
    r = E.check(draft(en__advice="Site administrators: review which third-party scripts your pages load.",
                      ua__advice="Адміністраторам сайтів: перевірте, які сторонні скрипти завантажують сторінки.",
                      advice_quote="Site administrators should review which third-party scripts their pages load.",
                      audience="it_admins"), ev(text=src))
    assert r.problems["integrity"] == [] and r.problems["equivalence"] == [], r.flat()


# ---------------------------------------------------------------- form

def test_the_hook_must_not_be_the_headline() -> None:
    r = E.check(draft(en__hook="Attackers used Optimizely to test malware on top websites."), ev())
    assert "the hook repeats the headline" in problems(r, "form") and r.scores["hook_quality"] < 4


def test_the_hook_must_stand_alone() -> None:
    r = E.check(draft(en__hook="Equifax and Ledger were on the list too."), ev())
    assert "refers back" in problems(r, "form") and not r.publishable


def test_a_repeated_paragraph_is_rejected() -> None:
    r = E.check(draft(en__why=GOOD["en"]["what"]), ev())
    assert "'why it matters' repeats 'what happened'" in problems(r, "form") and not r.publishable


def test_over_the_character_limit_is_rejected_not_truncated() -> None:
    long = "The BBC, CNN, Zoom, Equifax and Ledger served malware through Optimizely. " * 6
    r = E.check(draft(en__what=long), ev())
    assert r.lengths["en"] > TEXT_LIMIT and "over the 500 limit" in problems(r, "form") and not r.publishable


def test_hashtags_and_links_stay_out_of_the_text() -> None:
    r = E.check(draft(en__why="Read more at https://example.com #infosec"), ev())
    assert "hashtag or link" in problems(r, "form")


# ---------------------------------------------------------------- image consistency

def test_alt_text_that_contradicts_the_source_blocks_the_post() -> None:
    r = E.check(draft(), ev(image_alt={"en": "Illustration: a breach notice from Netflix, marked '9 MILLION'.",
                                       "ua": "Ілюстрація: повідомлення про витік Netflix «9 MILLION»."}))
    flat = problems(r, "image")
    assert "names 'Netflix'" in flat and "'9'" in flat and r.scores["image_relevance"] < 5 and not r.publishable


def test_alt_text_status_labels_are_not_names() -> None:
    e = ev(image_alt={"en": "Illustration: a security advisory for Optimizely, marked 'EXPLOITED' and 'CRITICAL'.",
                      "ua": "Ілюстрація: бюлетень безпеки для Optimizely з позначкою «EXPLOITED»."})
    assert E.image_problems(e) == []


# ---------------------------------------------------------------- the writer

class FakeLLM:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses, self.prompts = list(responses), []   # type: list[dict[str, Any]], list[str]

    def generate_json(self, system: str, user: str, *, schema: Any) -> dict[str, Any]:
        self.prompts.append(user)
        return copy.deepcopy(self.responses.pop(0) if len(self.responses) > 1 else self.responses[0])


def test_the_writer_retries_once_with_the_failed_checks_as_feedback() -> None:
    bad = draft(en__hook="Equifax and Ledger were on the list too.").model_dump()
    llm = FakeLLM(bad, GOOD)
    d = E.write(ev(), llm)
    assert d.attempts == 2 and d.review.publishable and "refers back" in llm.prompts[1]
    assert d.history[0] and d.history[1] == []


def test_a_draft_failing_twice_is_kept_unpublishable() -> None:
    bad = draft(en__hook="187 top websites served malware.").model_dump()
    d = E.write(ev(), FakeLLM(bad))
    assert d.attempts == 2 and not d.review.publishable


def test_the_prompt_carries_the_evidence_and_forbids_relative_time() -> None:
    p = E.user_prompt(ev())
    assert HEAD in p and "178 top websites" in p and "18 November 2026" in p and "IMAGE ALT TEXT" in p
    assert "in the past day" in E.SYSTEM and "antivirus" in E.SYSTEM


# ---------------------------------------------------------------- publishing integration

def _editorial(tmp_path: Path, llm: FakeLLM, items_: list[Any]) -> E.Editorial:
    by_fp = {i.fingerprint: i for i in items_}
    return E.Editorial(E.DraftStore(tmp_path / "threads_editorial.json"), provider_factory=lambda: llm,
                       items=by_fp.get)


def _story(n: int = 1) -> Any:
    it = item(n)
    it.title, it.raw_content, it.source = HEAD, TEXT, "Krebs on Security"
    return it


def test_both_accounts_post_one_shared_bilingual_draft(tmp_path: Path) -> None:
    api, it, llm = FakeThreads(), _story(), FakeLLM(GOOD)
    store, src, d = world(tmp_path, api, it, editorial=_editorial(tmp_path, llm, [it]))
    rep = go(store, src, d)
    assert len(rep.published) == 2 and len(llm.prompts) == 1                     # one draft, both languages
    texts = {("/ua/" in p["text"]): p["text"] for p in api.posts}
    assert texts[False].startswith(GOOD["en"]["hook"]) and texts[True].startswith(GOOD["ua"]["hook"])
    assert "Reporting: Krebs on Security" in texts[False] and "Джерело: Krebs on Security" in texts[True]
    assert all(threads_length(t) <= TEXT_LIMIT for t in texts.values())
    go(store, src, d)                                                             # a second run posts nothing
    assert len(api.posts) == 2 and len(llm.prompts) == 1


def test_a_draft_failing_a_gate_is_never_published(tmp_path: Path) -> None:
    api, it = FakeThreads(), _story()
    llm = FakeLLM(draft(ua__what="Серед них BBC і CNN; код потрапив через Optimizely.").model_dump())
    store, src, d = world(tmp_path, api, it, editorial=_editorial(tmp_path, llm, [it]))
    go(store, src, d)
    assert api.created() == [] and api.posts == []
    assert {j.status for j in tj(store)} == {"failed"}                            # invalid content: not retried
    assert all("editorial gate" in j.last_error for j in tj(store))


def test_an_unavailable_writer_defers_and_never_falls_back_to_the_old_text(tmp_path: Path) -> None:
    api, it = FakeThreads(), _story()

    class Down:
        def generate_json(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("claude CLI timed out")

    ed = E.Editorial(E.DraftStore(tmp_path / "d.json"), provider_factory=Down, items={it.fingerprint: it}.get)
    store, src, d = world(tmp_path, api, it, editorial=ed)
    go(store, src, d)
    assert api.created() == [] and {j.status for j in tj(store)} == {"retrying"}


def test_a_retry_after_an_uncertain_send_reuses_the_same_text(tmp_path: Path) -> None:
    api, it, llm = FakeThreads(), _story(), FakeLLM(GOOD)
    ed = _editorial(tmp_path, llm, [it])
    store, src, d = world(tmp_path, api, it, editorial=ed)
    api.script["create"] = [RuntimeError("connection reset")]
    go(store, src, d)
    llm.responses = [draft(en__hook="A different hook about 178 top websites and one testing platform.").model_dump()]
    from datetime import timedelta
    from tests.test_threads import NOW
    for h in (1, 3, 6):
        go(store, src, d, now=NOW + timedelta(hours=h))
    assert len(llm.prompts) == 1                                                 # the cached draft is reused
    assert len(api.posts) <= 2 and len({p["text"] for p in api.posts}) == len(api.posts)
    assert all(p["text"].startswith((GOOD["en"]["hook"], GOOD["ua"]["hook"])) for p in api.posts)


def test_a_missing_source_article_is_rejected(tmp_path: Path) -> None:
    api, it, llm = FakeThreads(), _story(), FakeLLM(GOOD)
    ed = E.Editorial(E.DraftStore(tmp_path / "d.json"), provider_factory=lambda: llm, items=lambda fp: None)
    store, src, d = world(tmp_path, api, it, editorial=ed)
    go(store, src, d)
    assert api.posts == [] and llm.prompts == [] and {j.status for j in tj(store)} == {"failed"}


def test_the_review_tool_never_writes_into_the_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import argparse

    from cyberalertx import config
    from cyberalertx.tools import threads as T
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert T.cmd_editorial_review(argparse.Namespace(out=str(tmp_path), story=["x"]), provider=FakeLLM(GOOD)) == 2
    assert not (tmp_path / "threads_editorial.json").exists() and not (tmp_path / "drafts.json").exists()


def test_source_for_payload_shape_is_unchanged() -> None:
    # The editorial writer reads only these payload fields.
    p = next(iter(source_for(_story()).payloads.values()))
    assert {"id", "source", "translations", "published_at", "media"} <= set(p)


def test_a_stored_draft_is_rechecked_and_a_stale_failure_rewritten_once(tmp_path: Path) -> None:
    store = E.DraftStore(tmp_path / "d.json")
    bad = E.write(ev(), FakeLLM(draft(en__hook="Equifax and Ledger were on the list too.").model_dump()))
    store.put(bad)
    llm = FakeLLM(GOOD)
    ed = E.Editorial(store, provider_factory=lambda: llm, items=lambda fp: None)
    resp, review = ed.draft(ev())
    assert not review.publishable and llm.prompts == []        # same checks: the verdict stands, no LLM call
    data = store._read()
    data["a1"]["checks"] = "older"
    store.path.write_text(__import__("json").dumps(data))
    resp, review = ed.draft(ev())
    assert review.publishable and len(llm.prompts) == 1          # older checks: rewritten once
    resp2, _ = ed.draft(ev())
    assert resp2 == resp and len(llm.prompts) == 1               # then reused


# ---------------------------------------------------------------- the publish unit's time limit

class Clock:
    def __init__(self, left: float) -> None:
        self.left = left

    def __call__(self) -> float:
        return self.left


class SlowLLM(FakeLLM):
    def __init__(self, clock: Clock, cost: float, *responses: dict[str, Any]) -> None:
        super().__init__(*responses)
        self.clock, self.cost = clock, cost

    def generate_json(self, system: str, user: str, *, schema: Any) -> dict[str, Any]:
        self.clock.left -= self.cost
        return super().generate_json(system, user, schema=schema)


def test_no_writer_attempt_starts_without_time_and_an_unfinished_draft_resumes(tmp_path: Path) -> None:
    clock = Clock(200)
    bad = draft(en__hook="Equifax and Ledger were on the list too.").model_dump()
    llm = SlowLLM(clock, 100, bad, GOOD)
    ed = E.Editorial(E.DraftStore(tmp_path / "d.json"), provider_factory=lambda: llm, items=lambda fp: None)
    with pytest.raises(E.EditorialDeferred):
        ed.draft(ev(), remaining=clock)                     # attempt 1 (fails), then 100 s left < reserve
    assert len(llm.prompts) == 1 and ed.store._read()["a1"]["complete"] is False
    clock.left = 20
    with pytest.raises(E.EditorialDeferred):
        ed.draft(ev(), remaining=clock)                     # next run, no time: nothing starts
    assert len(llm.prompts) == 1
    clock.left = 240
    resp, review = ed.draft(ev(), remaining=clock)          # continues with attempt 2 and its feedback
    assert review.publishable and len(llm.prompts) == 2 and "refers back" in llm.prompts[1]
    assert ed.store._read()["a1"]["attempts"] == 2


def test_threads_never_starts_a_send_it_cannot_finish(tmp_path: Path) -> None:
    from datetime import timedelta

    from tests.test_threads import NOW
    api, it, llm = FakeThreads(), _story(), FakeLLM(GOOD)
    clock = Clock(60)                                        # enough for nothing but a cached draft
    store, src, d = world(tmp_path, api, it, editorial=_editorial(tmp_path, llm, [it]), remaining=clock)
    go(store, src, d)
    assert api.created() == [] and llm.prompts == []
    assert {j.status for j in tj(store)} == {"retrying"}     # waiting, no attempt spent, nothing sent
    clock.left = 240
    go(store, src, d, now=NOW + timedelta(hours=2))
    assert len(api.posts) == 2 and len(llm.prompts) == 1


def test_a_slow_container_is_left_for_the_next_run_when_time_runs_out(tmp_path: Path) -> None:
    api, it, llm = FakeThreads(), _story(), FakeLLM(GOOD)
    api.in_progress_polls = 5
    clock = Clock(240)
    store, src, d = world(tmp_path, api, it, editorial=_editorial(tmp_path, llm, [it]), remaining=clock,
                          sleep=lambda s: setattr(clock, "left", clock.left - s))
    go(store, src, d)
    assert api.posts == [] and clock.left >= 0                         # never sleeps past the budget
    assert all(j.external_state.get("container_id") for j in tj(store) if j.status == "retrying")


def test_telegram_is_sent_before_any_threads_step_in_a_run(tmp_path: Path) -> None:
    """Order within one run: a slow Threads writer can never delay Telegram."""
    from cyberalertx.publish.jobs import JobStore
    from cyberalertx.publish.orchestrator import PublishPolicy, plan, run
    from tests.test_publication import Bot, dests, settings, view
    from tests.test_threads import NOW, both, tdest

    api, bot, it = FakeThreads(), Bot(), _story()
    order: list[str] = []

    class Spy(FakeLLM):
        def generate_json(self, system: str, user: str, *, schema: Any) -> dict[str, Any]:
            order.append(f"writer (telegram calls so far: {len(bot.calls)})")
            return super().generate_json(system, user, schema=schema)

    llm = Spy(GOOD)
    accounts = both(tmp_path, api)
    ed = _editorial(tmp_path, llm, [it])
    d = {**dests(tmp_path, bot), "threads@en": tdest("en", accounts, api, editorial=ed),
         "threads@ua": tdest("ua", accounts, api, editorial=ed)}
    src = source_for(it)
    store = JobStore(tmp_path / "jobs.json")
    plan(src, store, now=NOW, settings=settings(), destinations=d, view=view(it), policy=PublishPolicy())
    run(src, store, d, now=NOW, clock=lambda: NOW, rng=lambda: 0.5)
    assert bot.sent() and order and order[0] != "writer (telegram calls so far: 0)"
    assert len(api.posts) == 2


# ---------------------------------------------------------------- false positives found in the 20-story review

def test_http2_is_a_protocol_not_a_link_or_a_name() -> None:
    src = TEXT + " The flaw affects HTTP/2 support."
    r = E.check(draft(en__why="The flaw is in HTTP/2-enabled servers, so exposure depends on configuration.",
                      ua__why="Вада в серверах з HTTP/2, тож ризик залежить від конфігурації."), ev(text=src))
    assert r.problems["form"] == [] and r.problems["accuracy"] == [], r.flat()


def test_police_taking_servers_down_is_narration_not_disable_advice() -> None:
    r = E.check(draft(ua__why="Поліція вимкнула сервери, тож один постачальник більше не досягає кожної сторінки."),
                ev())
    assert not any("unsupported advice" in x for x in r.problems["integrity"]), r.flat()
    r = E.check(draft(en__advice="Admins: disable the plugin.", ua__advice="Адміністраторам: вимкніть плагін.",
                      advice_quote="served malware"), ev())
    assert "unsupported advice" in problems(r, "integrity")


def test_countries_and_months_written_in_ukrainian_are_the_same_name() -> None:
    src = TEXT + " 40 of them are in Ireland; the attack was found in November."
    r = E.check(draft(en__why="40 of the sites are in Ireland, and the attack surfaced in November.",
                      ua__why="40 сайтів - в Ірландії, а атаку виявили в листопаді."), ev(text=src))
    assert r.problems["equivalence"] == [], r.flat()


def test_an_fbi_finding_is_not_an_attackers_claim() -> None:
    src = ("The U.S. Federal Bureau of Investigation (FBI) has established that threat actors tied to North Korea "
           "have stolen more than $400 million worth of cryptocurrency.")
    d = draft(status="reported_incident",
              en__hook="Over $400 million in crypto stolen, the FBI says, by actors tied to North Korea.",
              en__what="The FBI has established that threat actors tied to North Korea stole the cryptocurrency.",
              en__why="Attribution by the FBI turns a theft into a state-level problem for every crypto firm.",
              ua__hook="Понад $400 млн у криптовалюті викрали, за даними ФБР, пов'язані з Північною Кореєю.",
              ua__what="ФБР встановило, що крипту викрали зловмисники, пов'язані з Північною Кореєю.",
              ua__why="Атрибуція ФБР робить крадіжку проблемою державного рівня для кожної криптофірми.",
              facts=[{"claim_en": "x", "claim_ua": "x", "quote": "have stolen more than $400 million"}],
              names=[{"en": "FBI", "ua": "ФБР"}])
    r = E.check(d, ev(headline="FBI Says North Korean Hackers Stole Over $400 Million", text=src,
                      edition_titles=(), image_alt={}))
    assert r.problems["integrity"] == [] and r.problems["equivalence"] == [], r.flat()


def test_an_overlong_draft_gets_a_concrete_cut_in_its_feedback() -> None:
    long_what = GOOD["en"]["what"] + " The BBC, CNN and Zoom served malware through Optimizely to visitors."
    r = E.check(draft(en__what=long_what), ev())
    assert r.lengths["en"] > E.EDITORIAL_TARGET
    assert any("cut hook+what+why by at least" in x for x in E._feedback(r))


def test_an_elided_quote_is_verbatim_piece_by_piece() -> None:
    ok = draft(facts=[{"claim_en": "x", "claim_ua": "x", "quote": "At least 178 top websites ... served malware"}])
    assert E.check(ok, ev()).problems["integrity"] == []
    bad = draft(facts=[{"claim_en": "x", "claim_ua": "x", "quote": "At least 178 top websites ... stole passwords"}])
    assert "not quoted from the source" in problems(E.check(bad, ev()), "integrity")


def test_the_writer_keeps_the_better_attempt() -> None:
    better = draft(en__hook="Equifax and Ledger were on the list too.").model_dump()           # one form problem
    worse = draft(en__hook="187 sites and the list too.", ua__hook="187 сайтів.").model_dump()  # several
    d = E.write(ev(), FakeLLM(better, worse))
    assert d.response.en.hook == "Equifax and Ledger were on the list too." and d.attempts == 2
