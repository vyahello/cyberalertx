from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.audience import classify_audience


def _item(
    title: str,
    body: str = "",
    *,
    category: str = "other",
    platforms: list[str] | None = None,
) -> NewsItem:
    return NewsItem(
        title=title,
        source="t",
        url=f"https://e.test/{abs(hash(title))}",
        published_at=datetime.now(timezone.utc),
        raw_content=body,
        category=category,
        affected_platforms=platforms or [],
    )


# ---------- spec examples ----------

def test_windows_phishing_targets_normal_users():
    item = _item(
        "Windows phishing attack uses fake Microsoft login pages",
        body="Threat actors are running a phishing campaign that lures Windows users.",
        category="phishing",
        platforms=["Windows"],
    )
    targets, score = classify_audience(item)
    assert "normal_users" in targets
    assert score > 0


def test_kubernetes_rce_targets_developers_and_sysadmins():
    item = _item(
        "Critical Kubernetes RCE allows cluster takeover",
        body="A remote code execution flaw in Kubernetes can let attackers take over clusters.",
        category="exploit",
        platforms=["Kubernetes"],
    )
    targets, _ = classify_audience(item)
    assert "developers" in targets
    assert "sysadmins" in targets


def test_oracle_enterprise_breach_targets_enterprise():
    item = _item(
        "Oracle enterprise breach exposes Fortune 500 customer data",
        body="Oracle disclosed a breach affecting enterprise customer records.",
        category="breach",
    )
    targets, score = classify_audience(item)
    assert "enterprise" in targets
    # Should NOT be flagged as normal_users only — the story is enterprise-centric.
    assert "normal_users" not in targets
    assert score > 0


# ---------- additional audiences ----------

def test_iphone_zero_click_targets_mobile_users():
    item = _item(
        "iPhone zero-click exploit deployed in spyware campaign",
        body="A new zero-click exploit chain has been observed on iPhone.",
        category="spyware",
        platforms=["iOS"],
    )
    targets, _ = classify_audience(item)
    assert "mobile_users" in targets


def test_wallet_drainer_targets_crypto_users():
    item = _item(
        "Wallet drainer kit steals millions from MetaMask users",
        body="A new wallet drainer kit is being marketed on dark web forums to crypto thieves.",
        category="scam",
    )
    targets, _ = classify_audience(item)
    assert "crypto_users" in targets


def test_npm_supply_chain_targets_developers():
    item = _item(
        "Malicious npm package steals developer credentials",
        body="A typosquatted npm package was found exfiltrating environment variables.",
        category="malware",
    )
    targets, _ = classify_audience(item)
    assert "developers" in targets


def test_cisco_advisory_targets_sysadmins():
    item = _item(
        "Cisco issues advisory for actively exploited ASA flaw",
        body="Cisco published an out-of-band advisory; admins should patch ASA appliances.",
        category="vulnerability",
        platforms=["Cisco"],
    )
    targets, _ = classify_audience(item)
    assert "sysadmins" in targets


# ---------- generic & edge cases ----------

def test_no_signal_returns_empty_targets():
    item = _item(
        "Researchers publish abstract paper on theoretical lattice cryptography",
        body="A new paper covers post-quantum lattice constructions.",
        category="other",
    )
    targets, score = classify_audience(item)
    assert targets == []
    assert score == 0.0


def test_score_is_between_zero_and_one():
    item = _item(
        "Critical Kubernetes RCE in cloud deployments — github advisory issued",
        body="Kubernetes RCE in docker container images; supply chain risk for ci/cd.",
        category="exploit",
        platforms=["Kubernetes", "Docker"],
    )
    _, score = classify_audience(item)
    assert 0.0 <= score <= 1.0


def test_targets_are_sorted_and_deduped():
    item = _item(
        "iOS zero-click and Android stalkerware in same campaign",
        body="The campaign uses smishing and mobile spyware on both iOS and Android.",
        category="spyware",
        platforms=["iOS", "Android"],
    )
    targets, _ = classify_audience(item)
    assert targets == sorted(set(targets))
    assert "mobile_users" in targets
