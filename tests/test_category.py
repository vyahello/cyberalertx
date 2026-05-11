from cyberalertx.pipeline.category import classify


def test_classify_phishing():
    cat, conf = classify("Massive phishing campaign targets Microsoft 365 users")
    assert cat == "phishing"
    assert conf > 0


def test_classify_ransomware_specific_over_malware_generic():
    # Mentions both 'ransomware' and 'malware' — ransomware is more specific
    # and is ordered before malware in the priority list.
    cat, _ = classify("New ransomware family discovered, classified as malware")
    assert cat == "ransomware"


def test_classify_zero_day_wins_over_vulnerability():
    cat, _ = classify("Zero-day vulnerability in Chrome under active exploitation")
    assert cat == "zero-day"


def test_classify_data_leak():
    cat, _ = classify("Hacker leaked database of 10M user credentials")
    assert cat in ("data leak", "breach")  # both legit; depends on phrasing


def test_classify_unrelated_returns_other():
    cat, conf = classify("New cafe opens in downtown San Francisco")
    assert cat == "other"
    assert conf == 0.0


def test_classify_ukrainian_phishing():
    cat, _ = classify("Виявлено нову фішингову кампанію проти українських банків")
    assert cat == "phishing"


def test_classify_ukrainian_ransomware():
    cat, _ = classify("Програма-вимагач атакувала лікарні")
    assert cat == "ransomware"


def test_confidence_between_zero_and_one():
    _, conf = classify("Critical RCE vulnerability exploited in the wild zero-day")
    assert 0.0 <= conf <= 1.0
