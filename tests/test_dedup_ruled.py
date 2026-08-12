"""RULE D and generic-vocabulary tests, all pinned to real corpus pairs."""
from __future__ import annotations

from tests.test_dedup import item, matches

from cyberalertx.pipeline.dedup import (
    StoryFeatures,
    _entities,
    cluster_items,
    extract_quantities,
)

KREBS_BODY = (
    "Microsoft today released updates to remedy at least 398 security "
    "vulnerabilities in its Windows operating systems and supported software, "
    "including one weakness that is already being actively exploited."
)
THN_BODY = (
    "Microsoft released its monthly security updates on Tuesday, and one of the "
    "flaws it closed is already being used in attacks."
)
BC_BODY = (
    "Microsoft has released the August 2026 Patch Tuesday updates, fixing a "
    "massive 400 flaws, one actively exploited and two publicly disclosed."
)


# --------------------------------------------------------------------------
# MUST MERGE — the reported bug
# --------------------------------------------------------------------------

def test_patch_tuesday_merges_on_the_rollup_count_krebs_x_thn():
    # The reported pair: 215b91448d4dcac6 x 36069f37dfa6017d. Title Jaccard
    # 0.091, no shared CVE, and their only shared word is "microsoft", which
    # `_ENTITY_BLOCKLIST` refuses. Both count 398 vulnerabilities — Krebs in
    # its body, The Hacker News in its headline.
    krebs = item("Microsoft Plugs Nearly 400 Security Holes",
                 "Krebs on Security", body=KREBS_BODY)
    thn = item("Microsoft Patches 398 Flaws Including a Windows Driver "
               "Zero-Day Under Active Attack",
               "The Hacker News", body=THN_BODY, days=-0.05)
    assert matches(krebs, thn)


def test_patch_tuesday_merges_the_third_outlet_on_the_round_count():
    # 215b91448d4dcac6 x 5a84ed3ef08a97e7. Krebs says 400 in its headline,
    # BleepingComputer says 400 in both; a rollup count needs only one shared
    # subject word, and "microsoft" is it.
    krebs = item("Microsoft Plugs Nearly 400 Security Holes",
                 "Krebs on Security", body=KREBS_BODY)
    bc = item("Microsoft August 2026 Patch Tuesday fixes 400 flaws, 3 zero-days",
              "BleepingComputer", body=BC_BODY, days=-0.14)
    assert matches(krebs, bc)


def test_all_three_patch_tuesday_articles_land_in_one_cluster():
    krebs = item("Microsoft Plugs Nearly 400 Security Holes",
                 "Krebs on Security", body=KREBS_BODY)
    thn = item("Microsoft Patches 398 Flaws Including a Windows Driver "
               "Zero-Day Under Active Attack",
               "The Hacker News", body=THN_BODY, days=-0.05)
    bc = item("Microsoft August 2026 Patch Tuesday fixes 400 flaws, 3 zero-days",
              "BleepingComputer", body=BC_BODY, days=-0.14)
    clusters = cluster_items([krebs, thn, bc])
    assert len(clusters) == 1


def test_victim_count_merges_two_reports_of_one_guilty_plea():
    # 58eb3ce5569a189e x b41d695ada7747c6. Neither headline says 165; both
    # bodies do, and the headlines share "snowflake", "pleads", "guilty".
    krebs = item("Canadian Man Pleads Guilty in Snowflake Extortions",
                 "Krebs on Security",
                 body="Moucka pleaded guilty to intrusions at 165 organizations.")
    thn = item("Snowflake Hacker Pleads Guilty Over Breaches Affecting at "
               "Least 100 Million People", "The Hacker News",
               body="The intrusions hit 165 organizations and at least "
                    "100 million people.", days=0.5)
    assert matches(krebs, thn)


def test_a_count_found_only_in_the_bodies_still_merges():
    # d319044c80010cfd x 21ad1a2bf2fd1f2a. "50,000" appears in neither
    # headline, which is why a title-only signal can never reach this pair.
    a = item("Hackers breached a small Polish energy plant via private APN "
             "last year", "BleepingComputer",
             body="The plant supplies heat to about 50,000 residents.")
    b = item("Hackers Breach Polish Power Plant Controls via Private Cellular "
             "Network and Shut Turbine", "The Hacker News",
             body="The facility serves roughly 50,000 residents with heat.",
             days=0.3)
    assert matches(a, b)


# --------------------------------------------------------------------------
# MUST NOT MERGE — every shape that made a false merge during design
# --------------------------------------------------------------------------

def test_same_count_of_different_things_stays_apart():
    # A bare shared number is not evidence. Krebs counts patched flaws;
    # this counts targeted organizations.
    krebs = item("Microsoft Plugs Nearly 400 Security Holes",
                 "Krebs on Security", body=KREBS_BODY)
    spray = item("Microsoft warns 400 organizations targeted in Entra ID "
                 "password spray wave", "BleepingComputer",
                 body="Microsoft notified 400 organizations targeted in a "
                      "password spray campaign against Entra ID tenants.",
                 days=0.4)
    assert not matches(krebs, spray)


def test_same_rollup_count_from_two_vendors_stays_apart():
    # Same number, same unit, same week — and no shared subject, because
    # "patches" and "flaws" are generic. Two vendors' rollups are two stories.
    adobe = item("Adobe patches 254 flaws across Acrobat and Experience Manager",
                 "BleepingComputer",
                 body="Adobe released updates fixing 254 flaws.")
    microsoft = item("Microsoft patches 254 flaws in October Patch Tuesday",
                     "The Hacker News",
                     body="Microsoft shipped fixes for 254 flaws.", days=0.8)
    assert not matches(adobe, microsoft)


def test_a_victim_count_needs_more_than_a_vendor_name():
    # Two unrelated Microsoft incidents that happen to quote 500. A count of
    # organizations is not a release fingerprint, so one shared word — and a
    # blocklisted vendor at that — must not carry it. Also pins the fix that
    # stops the unit noun ("organizations") corroborating its own number.
    exchange = item("Microsoft says 500 organizations breached in Exchange attacks",
                    "BleepingComputer",
                    body="Microsoft confirmed 500 organizations were breached "
                         "in attacks on on-premises Exchange servers.")
    teams = item("Microsoft warns 500 organizations hit by Teams phishing",
                 "The Hacker News",
                 body="Microsoft is warning that 500 organizations have been "
                      "hit by a Teams-based phishing operation.", days=0.1)
    assert not matches(exchange, teams)


def test_a_roundup_never_merges_on_a_count_it_is_only_summing():
    # The roundup's 340 belongs to three projects at once. Merging it with
    # any one of them deletes that article from the feed.
    roundup = item("Veeam, Terraform MCP and Django Patch 340 Flaws This Week",
                   "The Hacker News",
                   body="Veeam, Terraform MCP and Django patched 340 flaws "
                        "between them this week.")
    django = item("Django team corrects QuerySet filtering flaw in the ORM "
                  "annotation pipeline", "BleepingComputer",
                  body="The Django team corrected a QuerySet filtering flaw, "
                       "one of 340 flaws the project has patched this year.",
                  days=0.7)
    assert not matches(roundup, django)


def test_kev_catalog_entry_never_merges_on_a_count():
    kev = item("CISA Adds One Known Exploited Vulnerability to Catalog",
               "CISA Alerts",
               body="Agencies must remediate. The vendor fixed 398 flaws.")
    krebs = item("Microsoft Plugs Nearly 400 Security Holes",
                 "Krebs on Security", body=KREBS_BODY, days=0.2)
    assert not matches(kev, krebs)


def test_two_npm_campaigns_with_the_same_boilerplate_stay_apart():
    # 5e41b682e284fc8e x 7f2f0040ed3dddf4 — a false merge that was live in
    # the production store, written into it as `duplicate_of`. Title Jaccard
    # 0.5 on five shared words, every one of which is supply-chain
    # boilerplate: "cross-platform", "deliver", "npm", "package", "rat".
    a = item("18 Malicious npm Packages Deliver Cross-Platform RAT to Alibaba "
             "Tool Users", "The Hacker News")
    b = item("Nearly 800 Malicious npm Packages Deliver Cross-Platform RAT and "
             "Infostealer", "The Hacker News", days=4)
    assert not matches(a, b)


def test_two_unrelated_npm_sweeps_quoting_one_number_stay_apart():
    # Same ecosystem, same unit, same number — the residual risk RULE D
    # inherits. What holds them apart is that "npm" and "package" are
    # generic, leaving no subject at all.
    a = item("Malicious npm Packages Steal Tokens From 1,200 Projects",
             "The Hacker News",
             body="The packages were pulled into 1,200 projects.")
    b = item("npm Worm Spreads Through 1,200 Packages in a Day",
             "BleepingComputer",
             body="The worm spread through 1,200 packages in a single day.",
             days=1)
    assert not matches(a, b)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def test_quantities_pair_a_number_with_what_it_counts():
    assert extract_quantities("remedy at least 398 security vulnerabilities") == {
        (398, "vuln")}
    assert extract_quantities("Patches 398 Flaws Including a Driver Zero-Day") == {
        (398, "vuln")}


def test_quantities_reject_product_numbers_ports_and_versions():
    for text in (
        "breach Microsoft 365 accounts",
        "INC Ransomware Exploiting SonicWall SMA 1000 Flaws",
        "Johnson Controls C-CURE 9000 and Victor",
        "listening on port 8999",
        "MZ Automation IEC 61850 library",
    ):
        assert extract_quantities(text) == frozenset(), text


def test_quantities_reject_scores_dates_and_small_counts():
    assert extract_quantities("rated CVSS 10.0, disclosed 2026-08-11") == frozenset()
    assert extract_quantities("fixes 3 zero-days and 42 bugs") == frozenset()
    assert extract_quantities("CVE-2026-68820 under active attack") == frozenset()


def test_quantities_need_a_readable_unit():
    # Nothing to compare safely against, so the number is dropped.
    assert extract_quantities("the total reached 4,500.") == frozenset()


def test_a_bare_number_is_not_a_named_entity():
    # RULE C required a shared entity; a shared count used to satisfy it.
    assert "500" not in _entities("Microsoft says 500 organizations breached")
    assert "log4j" in _entities("Attackers still scan for log4j")


def test_generic_vocabulary_covers_normalised_plurals():
    # `_norm_token` folds "Patches" to "patche" and "vulnerabilities" to
    # "vulnerabilitie"; both used to survive as distinctive tokens.
    feats = StoryFeatures.from_item(
        item("Oracle Patches Vulnerabilities in Quarterly Update"))
    assert "patche" not in feats.distinctive
    assert "vulnerabilitie" not in feats.distinctive
    assert "oracle" in feats.distinctive


def test_malware_category_words_are_not_distinctive():
    feats = StoryFeatures.from_item(
        item("New ChainDrop ransomware backdoor delivers an infostealer"))
    assert feats.distinctive == {"chaindrop"}
