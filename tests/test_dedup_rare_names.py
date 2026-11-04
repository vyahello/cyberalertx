"""RULE E (rare shared name), Ukrainian normalization, and the false-merge traps.

Every fixture is hand-built, but each one is modelled on a real pair from the
2026-11 store snapshot: the Chainalysis breach, the hack of the «Повітряна
тривога» air-alert app, the Ivanti Connect Secure follow-ups, the Russian
MNS app hack, the DOU News digest, the Cisco SD-WAN / ASA day, the two-vendor
KEV write-up and the "Claude Code" vs "Claude apps" collision that the
incremental replay surfaced.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.dedup import (
    StoryFeatures,
    _entities,
    _headline_names,
    _is_labelled_digest,
    _norm_token,
    _title_tokens,
    assign_incremental,
    assign_story_keys,
    cluster_items,
    name_statistics,
    same_story,
)

BASE = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
_SEQ = itertools.count()


def story(
    title: str,
    source: str = "BleepingComputer",
    *,
    body: str = "",
    hours: float = 0.0,
    category: str = "other",
) -> NewsItem:
    return NewsItem(
        title=title,
        source=source,
        url=f"https://example.test/rare/{next(_SEQ)}",
        published_at=BASE + timedelta(hours=hours),
        raw_content=body,
        category=category,
        source_credibility_score=0.8,
    )


def decide(a: NewsItem, b: NewsItem, *corpus: NewsItem) -> bool:
    """`same_story` with corpus statistics over the pair plus `corpus`."""
    feats = [StoryFeatures.from_item(i) for i in (a, b, *corpus)]
    stats = name_statistics(feats)
    fa, fb = feats[0], feats[1]
    forward = same_story(fa, fb, name_stats=stats)
    assert forward == same_story(fb, fa, name_stats=stats), "same_story must be symmetric"
    return forward


def stories_of(items: list[NewsItem]) -> list[set[str]]:
    return [{m.fingerprint for m in c.members} for c in cluster_items(items)]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def chainalysis_pair() -> tuple[NewsItem, NewsItem]:
    bc = story('Chainalysis discloses data breach from "offensive agentic techniques"',
               body="Blockchain analytics firm Chainalysis disclosed a data breach after "
                    "attackers accessed internal systems and tools.",
               category="breach", hours=0.8)
    thn = story("Chainalysis Confirms Intrusion Into Internal Tools and Exposure of "
                "Customer Identity Data", "The Hacker News",
                body="American blockchain analysis firm Chainalysis said it was the "
                     "target of a cybersecurity incident in which an external actor "
                     "accessed non-sensitive customer data.",
                category="breach")
    return bc, thn


def air_alert_coverage() -> list[NewsItem]:
    """Five outlets, one incident, four spellings of the app's name."""
    return [
        story("Хакери зламали застосунок «Повітряна тривога», яку розробили в Ajax "
              "та Stfalcon", "dou.ua", category="breach"),
        story("«Ядерна тривога» та вуличні бої в Києві: застосунок «Повітряна тривога» "
              "зазнав імовірної кібератаки. Що відомо", "dev.ua", hours=0.2),
        story('Злам застосунку "Повітряна тривога": робота поступово відновлюється '
              "після відключення", "itc.ua", hours=9.3, category="breach"),
        story("Розробники застосунку «Повітряна тривога» частково відновили роботу "
              "сервісу після хакерської атаки і фейкових сповіщень", "dev.ua", hours=10.0),
        story("«Не докрутили кіберзахист». Чи могли російські хакери через злам "
              "«Повітряної тривоги» проникнути в інфраструктуру її розробника Ajax "
              "Systems", "ain.ua", hours=19.0, category="breach"),
    ]


def russian_mns_hack(hours: float = 11.0) -> NewsItem:
    return story("На росії зламали мобільний застосунок сповіщень: з'явилося "
                 "повідомлення про ядерну загрозу", "dev.ua",
                 body="На росії хакери зламали офіційний застосунок МНС (МЧС).",
                 hours=hours, category="breach")


# --------------------------------------------------------------------------
# Ukrainian normalization
# --------------------------------------------------------------------------

def test_ukrainian_inflections_share_one_stem():
    assert _norm_token("Повітряна") == _norm_token("Повітряної") == _norm_token("повітряну")
    assert _norm_token("тривога") == _norm_token("тривоги") == _norm_token("тривогу")
    assert _norm_token("застосунок") == _norm_token("застосунку") == _norm_token("застосунком")
    assert (_norm_token("вразливість") == _norm_token("вразливості")
            == _norm_token("вразливостей"))


def test_ukrainian_stems_keep_at_least_four_letters():
    # Stripping "ам" from "злам" or "і" from "дані" would leave a stem that
    # collides with everything; short words are left alone.
    assert _norm_token("злам") == "злам"
    assert _norm_token("дані") == "дані"
    for word in ("Повітряна", "тривоги", "застосунку", "Києві", "кібербезпеки"):
        assert len(_norm_token(word)) >= 4, word


def test_every_ukrainian_apostrophe_yields_one_token():
    spellings = ["з'явилося", "з’явилося", "зʼявилося"]
    tokens = [_title_tokens(f"Повідомлення {s} у застосунку") for s in spellings]
    assert tokens[0] == tokens[1] == tokens[2]
    assert not any("явил" in t and not t.startswith("з") for t in tokens[0])


def test_latin_normalization_is_unchanged():
    assert _norm_token("Flaws") == "flaw"
    assert _norm_token("escapes") == "escape"
    assert _norm_token("access") == "access"
    assert _norm_token("virus") == "virus"
    assert _norm_token("iOS") == "ios"
    # An English possessive still splits exactly as it always did.
    assert _title_tokens("Anthropic's Claude breached orgs") == {
        "anthropic", "claude", "breached", "orgs"}
    assert _entities("VMware fixes three critical flaws allowing auth bypass, VM escapes") == {
        "vmware", "three", "escape"}


def test_cyrillic_entities_are_names_not_every_word():
    # Before: nine of nine content words of this headline were "entities".
    assert _entities("На росії зламали мобільний застосунок сповіщень: з'явилося "
                     "повідомлення про ядерну загрозу") == set()
    assert _entities("Хакери зламали застосунок «Повітряна тривога», яку розробили в "
                     "Ajax та Stfalcon") == {"повітрян", "тривог", "ajax", "stfalcon"}
    # A capital that is merely sentence-initial is not a name; an acronym is.
    assert _entities("Хакери зламали офіційний застосунок МНС") == {"мнс"}


# --------------------------------------------------------------------------
# Name extraction
# --------------------------------------------------------------------------

def test_quoted_names_are_one_key_whatever_the_quote_marks():
    a, _ = _headline_names("Злам застосунку «Повітряна тривога»: що відомо")
    b, _ = _headline_names('Злам застосунку "Повітряна тривога": що відомо')
    c, _ = _headline_names("Чи могли хакери через злам «Повітряної тривоги» проникнути далі")
    assert "повітрян тривог" in a & b & c
    # The words of a different quoted name do not leak out on their own.
    d, _ = _headline_names("«Ядерна тривога» та вуличні бої")
    assert "тривог" not in d and "повітрян тривог" not in d


def test_a_name_is_the_whole_run_of_proper_nouns():
    code, _ = _headline_names("Malicious Claude Code extension on Cursor planted SSH backdoors")
    apps, joins = _headline_names(
        "Fake ChatGPT and Claude Apps Abuse Signed Executables to Deploy Crypto Miners",
        "Fake ChatGPT and Claude apps were seen.")
    assert "claude code" in code
    assert "claude" in apps and not (code & apps)
    assert joins, "names on both sides of 'and'"


def test_first_word_needs_the_body_to_confirm_it_is_a_name():
    bc, thn = chainalysis_pair()
    assert "chainalysis" in StoryFeatures.from_item(bc).names
    thn_names = StoryFeatures.from_item(thn).names
    assert "chainalysis" in thn_names
    # Title case capitalizes everything; the body says "incident", lower case.
    assert not thn_names & {"intrusion", "internal", "tool", "exposure", "identity"}
    no_body = story("Chainalysis discloses data breach")
    assert "chainalysis" not in StoryFeatures.from_item(no_body).names


# --------------------------------------------------------------------------
# RULE E — merges
# --------------------------------------------------------------------------

def test_chainalysis_pair_merges_on_its_one_rare_name():
    bc, thn = chainalysis_pair()
    assert decide(bc, thn)
    assert len(cluster_items([bc, thn])) == 1


def test_rule_e_is_off_without_corpus_statistics():
    # The default keeps today's behaviour: no statistics, no RULE E.
    bc, thn = chainalysis_pair()
    assert not same_story(StoryFeatures.from_item(bc), StoryFeatures.from_item(thn))


def test_five_outlets_on_one_incident_become_one_story():
    # The name is in five headlines, over DF 3, but every mention sits in
    # one 19-hour burst: one event, not a recurring topic.
    coverage = air_alert_coverage()
    assert stories_of(coverage) == [{i.fingerprint for i in coverage}]
    assign_story_keys(coverage)
    assert sum(1 for i in coverage if not i.duplicate_of) == 1


def test_incremental_ingest_joins_later_coverage():
    bc, thn = chainalysis_pair()
    assign_story_keys([thn])
    duplicates = assign_incremental([bc], [thn])
    assert duplicates == [bc]
    assert bc.story_key == thn.story_key


def test_incremental_ingest_keeps_growing_one_incident():
    coverage = air_alert_coverage()
    store: list[NewsItem] = []
    for arriving in coverage:
        assign_incremental([arriving], store)
        store.append(arriving)
    assert len({i.story_key for i in store}) == 1


# --------------------------------------------------------------------------
# RULE E — guards
# --------------------------------------------------------------------------

def test_shared_rare_name_outside_48_hours_is_not_enough():
    bc, thn = chainalysis_pair()
    later = story(bc.title, body=bc.raw_content, category="breach", hours=60)
    assert not decide(thn, later)


def test_a_name_in_the_news_all_week_is_a_topic_not_a_story():
    hack = story("Binance probes potential $5.8 billion crypto-theft hack",
                 body="Cryptocurrency exchange Binance is investigating a breach.",
                 category="breach")
    explainer = story("Чому злам Binance — очікуване продовження історії", "ain.ua",
                      hours=20, category="breach")
    topic = [
        story("Binance reopens withdrawals after the hack", body="Exchange Binance said.",
              hours=70, category="breach"),
        story("Binance users pull billions after the exchange reopens",
              body="Users of Binance withdrew.", hours=75, category="breach"),
    ]
    assert not decide(hack, explainer, *topic)


def test_incompatible_categories_do_not_merge_on_a_name():
    breach = story("Northflank security breach leads to abuse of customers' AI API keys",
                   body="Cloud platform Northflank disclosed a breach.", category="breach")
    vuln = story("Northflank patches flaw in build pipeline", "The Hacker News",
                 body="Cloud platform Northflank fixed a flaw.", hours=5,
                 category="vulnerability")
    both_names = StoryFeatures.from_item(breach).names & StoryFeatures.from_item(vuln).names
    assert both_names == {"northflank"}, "the name must be shared for this to test anything"
    assert not decide(breach, vuln)
    # The same pair with compatible categories is a merge: only the
    # category check stands between them.
    vuln.category = "breach"
    assert decide(breach, vuln)


def test_an_uncategorized_item_needs_more_than_the_name():
    # A business story about the same company is not its hack.
    hack = story("Хакери атакували «Київстар»: абоненти залишилися без зв'язку",
                 "dev.ua", category="breach")
    business = story("«Київстар» інвестує у хмарну інфраструктуру: компанія купила "
                     "GigaCloud", "ain.ua", hours=6, category="other")
    assert not decide(hack, business)


def test_rule_e_is_symmetric_over_every_fixture_pair():
    items = [*air_alert_coverage(), *chainalysis_pair(), russian_mns_hack()]
    feats = [StoryFeatures.from_item(i) for i in items]
    stats = name_statistics(feats)
    for a, b in itertools.combinations(feats, 2):
        assert same_story(a, b, name_stats=stats) == same_story(b, a, name_stats=stats)


# --------------------------------------------------------------------------
# Traps — each of these is a different story and must stay apart
# --------------------------------------------------------------------------

def test_ivanti_follow_up_zero_days_stay_apart_from_the_earlier_chain():
    # 31 Oct: CISA adds two Ivanti Connect Secure flaws to KEV, attackers
    # chain three. 2 Nov: Ivanti patches TWO MORE zero-days. A new,
    # actionable development; folding it into the first story would stop it
    # being rendered and published. Held a day apart here on purpose — the
    # real pair is 49 hours apart, and the window alone should not be what
    # keeps them separate.
    chain = story("Attackers Chain Three Ivanti Connect Secure Flaws to Gain "
                  "Unauthenticated Root Access", "The Hacker News",
                  body="CISA added two security flaws impacting Ivanti Connect Secure "
                       "(ICS) to its KEV catalog. CVE-2026-111357 is one.",
                  category="vulnerability")
    more = story("Ivanti patches two more Connect Secure zero-days chained in attacks",
                 body="Ivanti released security updates to patch two more Connect "
                      "Secure (ICS) remote access gateway flaws.",
                 hours=24, category="zero-day")
    assert not decide(chain, more)


def test_a_follow_up_headline_is_not_folded_into_the_earlier_story():
    # Same product run in both headlines, same family, a day apart, wording
    # too different for RULE C: only "two more" says it is a new development.
    first = story("Ivanti Connect Secure flaw exploited to breach VPN gateways",
                  body="Attackers exploited a flaw in Ivanti Connect Secure gateways.",
                  category="zero-day")
    more = story("Ivanti Connect Secure admins told to apply two more emergency "
                 "hotfixes this week", "The Hacker News",
                 body="Patches for Ivanti Connect Secure address two more flaws.",
                 hours=24, category="zero-day")
    assert not decide(first, more)
    plain = story("Ivanti Connect Secure admins told to apply emergency hotfixes "
                  "this week", "The Hacker News",
                  body="Patches for Ivanti Connect Secure address the flaw.",
                  hours=24, category="zero-day")
    assert decide(first, plain), "without the follow-up marker this pair is one story"


def test_two_ivanti_advisories_with_different_cves_stay_apart():
    a = story("Ivanti Connect Secure flaw exploited to gain root",
              body="Tracked as CVE-2026-111357.", category="exploit")
    b = story("Ivanti Connect Secure gateway flaw lets attackers bypass login",
              "The Hacker News", body="Tracked as CVE-2026-118527.",
              hours=10, category="vulnerability")
    assert not decide(a, b)


def test_same_vendor_same_day_different_products_stay_apart():
    sd_wan = story("Hackers Exploited Cisco SD-WAN Flaw to Plant Malware Built to Steal "
                   "Encryption Keys", "The Hacker News",
                   body="Threat actors exploited a Cisco SD-WAN flaw.", category="exploit")
    firewall = story("New Cisco firewall zero-day exploited to crash SSL VPN devices",
                     hours=2.8, category="zero-day")
    asa = story("Cisco Patches Actively Exploited ASA and FTD VPN Flaw That Can Crash "
                "Firewalls", "The Hacker News",
                body="Cisco has released updates for its ASA and FTD software.",
                hours=2.3, category="exploit")
    assert not decide(sd_wan, firewall, asa)
    assert not decide(sd_wan, asa, firewall)


def test_same_vendor_same_product_does_merge():
    # The positive control for the trap above: the product run agrees.
    thn = story("Hackers Exploited Cisco SD-WAN Flaw to Plant Malware Built to Steal "
                "Encryption Keys", "The Hacker News",
                body="Threat actors exploited a Cisco SD-WAN flaw.", category="exploit")
    bc = story("Hackers exploit Cisco SD-WAN flaw to deploy custom KeyDrift malware",
               hours=10, category="vulnerability")
    assert decide(thn, bc)


def test_a_two_vendor_kev_write_up_does_not_bridge_into_one_vendor():
    kev = story("CISA Flags Two Actively Exploited Critical Flaws in Collabora Online "
                "and Arista VeloCloud", "The Hacker News",
                body="CISA added flaws in Collabora Online and Arista VeloCloud "
                     "Orchestrator to KEV.", hours=35, category="exploit")
    arista = story("Arista Warns of Critical VeloCloud SQL Injection Zero-Day Exploited "
                   "in Attacks", "The Hacker News",
                   body="Attackers are exploiting a flaw in Arista's VeloCloud Orchestrator.",
                   category="vulnerability")
    assert not decide(kev, arista)
    # Even when the product run agrees exactly, the two-subject headline
    # must not be matched on one of its subjects.
    same_run = story("Arista VeloCloud zero-day exploited to hijack orchestrators",
                     body="Attackers exploited a flaw in Arista VeloCloud.",
                     category="zero-day")
    assert "arista velocloud" in StoryFeatures.from_item(same_run).names
    assert StoryFeatures.from_item(kev).joins_subjects
    assert not decide(kev, same_run)


def test_weekly_digest_never_merges_with_an_incident_it_mentions():
    digest = story("Україна виходить у космос | Червоний день для AI | Скорочення в IT "
                   "— DOU News #274", "dou.ua",
                   body="Говоримо про злам «Повітряна тривога», HIMERA та Binance.",
                   hours=14, category="breach")
    for incident in air_alert_coverage():
        assert not decide(digest, incident)
    # A digest whose segment copies a story's headline word for word.
    launch = story("Україна виходить у космос: HIMERA запустила супутник OBRIA NANO",
                   "itc.ua", hours=2, category="other")
    copied = story("Україна виходить у космос: HIMERA запустила супутник OBRIA NANO | "
                   "Червоний день для AI | Скорочення в IT", "dou.ua",
                   hours=3, category="other")
    assert _is_labelled_digest(copied.title)
    assert not decide(launch, copied)


def test_russian_mns_app_hack_is_not_the_ukrainian_air_alert_hack():
    # Same day, same shape — an alert app hacked to push a fake nuclear
    # warning — and a different country, app and incident.
    coverage = air_alert_coverage()
    mns = russian_mns_hack()
    for incident in coverage:
        assert not decide(mns, incident, *coverage)
    clusters = stories_of([*coverage, mns])
    assert {mns.fingerprint} in clusters


def test_two_products_that_share_a_brand_word_stay_apart():
    # Surfaced by replaying the snapshot through `assign_incremental`: early
    # in the window "claude" looked rare, and the Claude Code extension
    # compromise merged into an unrelated fake-apps campaign.
    apps = story("Fake ChatGPT and Claude Apps Abuse Signed Executables to Deploy Crypto "
                 "Miners", "The Hacker News",
                 body="Fake ChatGPT and Claude apps were seen.", category="malware")
    extension = story("Malicious Claude Code extension on Cursor planted SSH backdoors",
                      hours=23, category="malware")
    assert not decide(apps, extension)
