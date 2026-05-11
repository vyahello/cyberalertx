from cyberalertx.pipeline.platforms import extract_platforms


def test_extract_single_platform():
    assert extract_platforms("Windows kernel zero-day exploited") == ["Windows"]


def test_extract_normalizes_iphone_to_ios():
    assert "iOS" in extract_platforms("iPhone users hit by spyware campaign")


def test_extract_multi_platform_sorted():
    out = extract_platforms("Chrome and Firefox patch critical bugs on Linux")
    assert out == sorted(out)
    assert {"Chrome", "Firefox", "Linux"} <= set(out)


def test_extract_word_boundary_no_false_positive():
    # "linux" is a substring of "salinux" but shouldn't match.
    assert "Linux" not in extract_platforms("Salinux Corp announces partnership")


def test_extract_multiword_alias():
    # Multi-word aliases match as substrings.
    assert "Cloud (AWS)" in extract_platforms("Bucket leak in amazon web services")


def test_extract_kubernetes_alias():
    assert "Kubernetes" in extract_platforms("k8s cluster compromised in supply chain attack")


def test_extract_empty_returns_empty_list():
    assert extract_platforms("") == []
    assert extract_platforms("Generic news with no platform mention") == []


def test_extract_dedupes_when_multiple_aliases_hit():
    # "ipad" and "iphone" both → iOS, should appear only once.
    out = extract_platforms("iPad and iPhone hit by zero-click iOS exploit")
    assert out.count("iOS") == 1
