"""The structured visual brief: what a story's image must show, and why.

Built only from verified story information: the headline (its main clause
first), the source excerpt, the story's own published EN brief, the category
and the evidence assessment (`pipeline.evidence.assess`). A scene is chosen by
scoring every catalogue entry against those texts — the headline's main clause
counts three times as much as the excerpt — so an incidental word ("crypto
miners" in an N-central story) cannot outvote the subject. When nothing in the
catalogue is supported strongly enough, the brief says so (confidence "low")
and the restrained fallback scene is used instead of an invented one.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from . import library

RENDERER_VERSION = "cax-editorial-4"

_CLAUSE_BREAK = re.compile(r"\s(?:as|after|while|amid|following|despite|before|once|to deploy|to steal|to spread|"
                           r"for|via|using|with)\s|\s[—–]\s|\s-\s|:\s|;\s|,\s(?:and|but)\s|\s(?:через|після|"
                           r"щоб|для|на тлі|поки)\s", re.I)


@dataclass(frozen=True)
class SceneSpec:
    id: str
    #: (pattern, weight). Matched case-insensitively against the brief texts.
    patterns: tuple[tuple[str, float], ...]
    palette: str
    subject: str
    action: str
    environment: str
    mechanism: str = ""
    supporting: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    alt_en: str = ""
    alt_ua: str = ""
    #: The scene needs this pattern somewhere in the texts to qualify at all.
    requires: str = ""


def _s(id: str, pats: list[tuple[str, float]], palette: str, subject: str, action: str, environment: str,
       mechanism: str, alt_en: str, alt_ua: str, *, supporting: tuple[str, ...] = (),
       exclude: tuple[str, ...] = (), requires: str = "") -> SceneSpec:
    return SceneSpec(id, tuple(pats), palette, subject, action, environment, mechanism, supporting,
                     ("generic cubes", "glowing orbs", "hooded hackers", "brand logos") + exclude, alt_en, alt_ua,
                     requires)


# Order matters only for ties: more specific scenes first.
CATALOGUE: tuple[SceneSpec, ...] = (
    _s("weekly_recap", [(r"weekly recap|week in review|тижнев\w* (огляд|дайджест)|дайджест", 9)], "midnight",
       "several unrelated products, each with its own new flaw", "a roundup of the week's vulnerabilities",
       "a board of product tiles", "one marker per product named in the roundup",
       "Illustration: a board of product tiles (a remote-management console, an operating-system window, a "
       "browser and a smart fridge), each flagged with a new vulnerability.",
       "Ілюстрація: дошка з плитками продуктів (консоль віддаленого керування, вікно ОС, браузер і розумний "
       "холодильник), на кожній позначено нову вразливість."),
    _s("hpc_hall", [(r"supercomput|суперкомп|супер-?ПК|\bHPC\b|Fugaku|Фугаку|top500", 6)], "midnight",
       "a national supercomputer installation", "unauthorised access and stolen user accounts",
       "a high-performance computing machine hall", "account compromise (no technical detail published)",
       "Illustration: rows of supercomputer racks in a machine hall, with a list of user accounts marked as "
       "compromised.",
       "Ілюстрація: ряди стійок суперкомп'ютера в машинному залі та перелік облікових записів, позначених як "
       "скомпрометовані.", supporting=("account list", "count from the headline")),
    _s("ci_pinning", [(r"SHA pinning|pinn(ed|ing) (to|actions)|GitHub Actions?|\.github/workflows|"
                       r"CI/CD|workflow file", 6), (r"GitHub", 2)], "paper",
       "a GitHub Actions workflow and its dependency references",
       "a malicious commit passed off as a trusted action", "a CI/CD workflow file and commit graph",
       "mutable tag vs immutable commit SHA; an impostor commit reachable by reference",
       "Illustration: a CI workflow file in which a version tag resolves to an impostor commit, beside the same "
       "dependency pinned to a full commit SHA.",
       "Ілюстрація: файл CI-процесу, де тег версії вказує на підроблений коміт, поруч та сама залежність, "
       "закріплена повним SHA коміту."),
    _s("session_theft", [(r"session|токен|token|cookie|AiTM|adversary-in-the-middle|\bM365\b|Microsoft 365|"
                          r"Office 365|\bOAuth\b", 5), (r"phishing kit|фішинг", 3)], "glacier",
       "a cloud office sign-in page cloned by a phishing kit",
       "the victim's session token is captured and replayed", "a browser sign-in flow",
       "adversary-in-the-middle proxy relays the login and keeps the session token",
       "Illustration: a look-alike sign-in page relays the victim's login to the real service while a proxy "
       "copies the session token, which is then replayed from another browser.",
       "Ілюстрація: підроблена сторінка входу передає логін жертви справжньому сервісу, а проксі копіює "
       "токен сесії, який потім використовують з іншого браузера.",
       exclude=("real Microsoft logos or interface",)),
    _s("rmm_console", [(r"N-central|N-able|\bRMM\b|remote monitoring|remote management|ScreenConnect|"
                        r"ConnectWise|Kaseya|SimpleHelp|віддален\w* (керуван|адміністр)|endpoint management|\bUEM\b", 7)], "midnight",
       "a remote monitoring and management console and its fleet of endpoints",
       "attackers abuse the management platform to push their own payload to managed machines",
       "an MSP's management console", "flaws in the management server; payload deployed through it",
       "Illustration: a remote-management console pushes a task to a fleet of managed computers, several of which "
       "now run an unwanted process at full load.",
       "Ілюстрація: консоль віддаленого керування розсилає завдання на парк комп'ютерів; на кількох уже працює "
       "небажаний процес із повним навантаженням."),
    _s("patch_to_exploit", [(r"fully[- ]automated|повністю автоматизован|autonomous|agentic|AI agents?|"
                             r"ШІ-агент|агентн", 6), (r"\bAI\b|ШІ|штучн", 2),
                            (r"exploit|patch|вразлив|кібератак|attack", 2)], "violet",
       "an automated AI pipeline that turns a published patch into a working exploit",
       "AI agents analyse a fix and generate an exploit without a human operator",
       "a code-review workspace", "patch diffing -> vulnerable function -> generated exploit",
       "Illustration: a security patch diff on one side, an automated agent pipeline in the middle and the "
       "generated exploit code on the other.",
       "Ілюстрація: різниця коду в патчі з одного боку, автоматизований конвеєр ШІ-агентів посередині та "
       "згенерований експлойт з іншого.", requires=r"\bAI\b|ШІ|штучн|agent"),
    _s("disclosure_deadline", [(r"disclosure (deadline|policy|window)|Project Zero|розкритт", 7)], "paper",
       "a vulnerability disclosure timeline", "the time vendors get to ship a fix is being shortened",
       "a bug-tracker timeline", "report -> fix deadline -> public disclosure",
       "Illustration: a vulnerability report on a timeline whose deadline marker moves earlier.",
       "Ілюстрація: звіт про вразливість на шкалі часу, де позначку крайнього терміну зсунуто раніше."),
    _s("ai_offensive_tool", [(r"ARTEX|Artex|AI-powered (cyber)?attack|ШІ-інструмент|AI tool", 7),
                             (r"cloud|хмар", 1)], "violet",
       "an AI-driven offensive tool", "a tool built for defence is run against real targets",
       "an operator console", "automated reconnaissance and intrusion steps",
       "Illustration: an AI-driven security tool's task list runs reconnaissance and intrusion steps against a "
       "company's cloud tenant.",
       "Ілюстрація: список завдань ШІ-інструмента безпеки виконує розвідку та проникнення в хмарне середовище "
       "компанії."),
    _s("refrigeration_controller", [(r"refrigerat|холодильн\w* (контролер|обладнан)|Danfoss|cold room|"
                                     r"temperature controller|холодильн\w* систем", 8)], "glacier",
       "a commercial refrigeration controller", "remote takeover of the controller without a login",
       "a refrigerated display case and its controller", "unauthenticated network access to the controller",
       "Illustration: a refrigeration controller on a cold-room panel, its network port reachable without a "
       "login and its set point open to change.",
       "Ілюстрація: контролер холодильної установки на панелі камери; мережевий порт доступний без входу, "
       "а задану температуру можна змінити."),
    _s("ics_controller", [(r"Siemens|SIMATIC|\bPLC\b|SCADA|\bICS\b|\bOT\b|industrial|промислов|Schneider|"
                           r"Rockwell|Mitsubishi Electric|ABB\b|HMI\b", 6)], "steel",
       "industrial control hardware and engineering software", "security advisory for industrial products",
       "a control cabinet", "advisory-level vulnerabilities in engineering software and controllers",
       "Illustration: an industrial control cabinet with PLC modules on a DIN rail, linked to an engineering "
       "workstation that is flagged by a security advisory.",
       "Ілюстрація: промислова шафа керування з модулями ПЛК на DIN-рейці, пов'язана з інженерною станцією, "
       "щодо якої оприлюднено попередження безпеки."),
    _s("court_case", [(r"\bcourt\b|charges?\b|pleads?|pleaded|guilty|sentenc\w*|extradit\w*|prison|convicted|"
                       r"indict\w*|acquit\w*|clears?\b|arrest\w*|\bсуд\w*|визнав провину|вирок|екстрадиц\w*|"
                       r"арешт\w*|ув'язнен", 8)], "court",
       "a criminal case against an alleged cybercriminal", "the case reaches a court decision",
       "a court docket", "legal proceedings (no technical detail)",
       "Illustration: a court case file and docket with the key figures of the case.",
       "Ілюстрація: матеріали судової справи з ключовими цифрами провадження."),
    _s("deepfake_call", [(r"deepfake|діпфейк|deep-fake|video calls?|відеодзвін", 8)], "violet",
       "a video call with a synthetic participant", "victims are deceived by deepfaked video calls",
       "a video-conferencing window", "real-time face synthesis on a call",
       "Illustration: a video call in which one participant's face is a synthetic mesh, while a transfer is "
       "being approved.",
       "Ілюстрація: відеодзвінок, у якому обличчя одного з учасників — синтетична сітка, а тим часом "
       "погоджується переказ."),
    _s("third_party_script", [(r"supply[- ]chain attack infects|Optimizely|third-party (script|tag)|"
                               r"(JavaScript|JS) (library|tag)|Magecart|skimmer|CDN", 8)], "midnight",
       "a shared third-party script loaded by many websites",
       "a tampered script is served to every site that includes it",
       "websites loading one third-party tag", "supply-chain compromise of a hosted script",
       "Illustration: one tampered third-party script file feeding several company websites at once.",
       "Ілюстрація: один змінений сторонній скрипт одночасно потрапляє на кілька сайтів компаній."),
    _s("compromised_sites", [(r"sites? .*(hacked|compromised)|сайти .*зламали|watering[- ]hole|"
                              r"websites? (hacked|compromised)", 8), (r"iPhone|iOS|crypto|криптовалют", 2)],
       "midnight", "legitimate company websites altered to attack their visitors",
       "visitors are served wallet-draining scripts and iPhone exploits", "several trusted websites",
       "injected scripts on compromised sites",
       "Illustration: familiar-looking company websites with an injected script, serving a wallet drainer to a "
       "desktop visitor and an exploit to an iPhone.",
       "Ілюстрація: сайти відомих компаній із вбудованим шкідливим скриптом, що атакує гаманець відвідувача "
       "комп'ютера та iPhone."),
    _s("usb_worm", [(r"\bUSB\b|worm|хробак|черв'?як|Retadup|removable", 7)], "forest",
       "a USB worm spreading between computers", "the worm copies itself through removable drives",
       "an office desk", "removable-media propagation, then a second-stage loader",
       "Illustration: an infected USB drive in a laptop, with the worm's copies travelling to other drives and "
       "machines.",
       "Ілюстрація: заражена USB-флешка в ноутбуці, копії хробака переходять на інші накопичувачі та "
       "комп'ютери."),
    _s("gpu_cryptominer", [(r"\bGPU\b|NVIDIA|graphics card|відеокарт", 7), (r"cryptomin|miner|майнер", 2)],
       "forest", "a GPU hijacked for cryptomining", "a modified driver library hides the GPU load",
       "a Linux server with a graphics card", "tampered monitoring library reports idle while the GPU is maxed",
       "Illustration: a graphics card running at full load while the monitoring terminal reports it idle.",
       "Ілюстрація: відеокарта працює на повну потужність, а термінал моніторингу показує, що вона "
       "простоює.", requires=r"\bGPU\b|NVIDIA|graphics card|відеокарт"),
    _s("kernel_dos", [(r"crash|denial[- ]of[- ]service|\bDoS\b|kernel panic|NoisyTCP|TCP", 6),
                      (r"Linux", 2)], "midnight",
       "Linux servers and their network stack", "crafted network traffic crashes the server",
       "a server console", "malformed TCP traffic triggering a kernel failure",
       "Illustration: a stream of crafted network packets reaching a Linux server whose console shows a "
       "kernel failure.",
       "Ілюстрація: потік спеціально сформованих мережевих пакетів досягає Linux-сервера, консоль якого "
       "показує збій ядра."),
    _s("irc_injection", [(r"\bIRC\b|UnrealIRCd", 8), (r"command injection", 3)], "midnight",
       "an IRC server", "a crafted message makes the server run attacker commands",
       "a chat server and its shell", "command injection through the IRC daemon",
       "Illustration: an IRC channel window where a crafted message becomes a command running in the server's "
       "shell.",
       "Ілюстрація: вікно IRC-каналу, де спеціально сформоване повідомлення перетворюється на команду в "
       "оболонці сервера."),
    _s("edge_wiper", [(r"gateways?|firewall|Check Point|FortiGate|Fortinet|Palo Alto|Ivanti|Citrix|"
                       r"VPN appliance|шлюз", 6), (r"wiper|ESXi|вайпер", 4)], "ember",
       "a network security gateway", "attackers break in through the gateway and wipe virtual machines",
       "a server room edge", "edge-device exploit -> hypervisor -> destructive wiper",
       "Illustration: a rack-mounted security gateway with an intrusion path leading to a virtualisation host "
       "whose virtual machines are being wiped.",
       "Ілюстрація: стійковий шлюз безпеки, від якого шлях атаки веде до хоста віртуалізації, де стираються "
       "віртуальні машини."),
    _s("code_signing", [(r"code[- ]signing|signing (server|certificate|key)|підпис\w* код", 7),
                        (r"Log4Shell|Log4j|vCenter", 3)], "ember",
       "a code-signing server and its certificate", "attackers reach the signing infrastructure",
       "a build and signing environment", "exploited server -> signing server -> trusted certificate exposed",
       "Illustration: an intrusion path from an exploited server to a code-signing server, whose certificate "
       "is lifted out.",
       "Ілюстрація: шлях вторгнення від зламаного сервера до сервера підпису коду, звідки забирають "
       "сертифікат."),
    _s("dev_supply_chain", [(r"API key|stolen key|extension|VS Code|marketplace|\bnpm\b|PyPI|package|"
                             r"розширенн|poisoned update|отруєн\w* оновленн|\b[\w]+-js\b|\bSDK\b", 6), (r"trojaniz|backdoor|троян", 3)],
       "midnight",
       "a developer tool supply chain", "a stolen key leads to a trojanised developer extension",
       "a code editor and extension marketplace", "leaked credential -> publishing access -> malicious update",
       "Illustration: a leaked API key leads to a code editor extension update that carries a trojan.",
       "Ілюстрація: викрадений API-ключ веде до оновлення розширення редактора коду з трояном."),
    _s("ransomware_impact", [(r"ransomware|програм\w*-?вимагач|вимагач|encrypt\w* (files|servers)|"
                              r"зашифрува", 7)], "ember",
       "systems encrypted by ransomware", "files and servers are made unavailable",
       "the affected organisation's systems", "encryption of files and servers",
       "Illustration: a file server whose folders have been encrypted, with a ransom note on screen.",
       "Ілюстрація: файловий сервер із зашифрованими теками та повідомленням про викуп на екрані."),
    _s("telecom", [(r"telecom|телеком|\b5G\b|mobile network|operator|оператор|base station|зв'язку", 6)],
       "midnight", "telecommunications infrastructure", "operators harden the network against disruption",
       "a mobile network site", "network resilience (analysis, no incident)",
       "Illustration: a mobile network mast and fibre backhaul, drawn as an engineering elevation.",
       "Ілюстрація: щогла мобільного зв'язку та оптична магістраль у вигляді інженерного креслення."),
    _s("espionage_backdoor", [(r"backdoors?|\bC2\b|command-and-control|espionage|шпигун|\bAPT\b|"
                               r"government networks|урядов|держустанов|Turla|steal emails from gov", 6),
                              (r"cloud|хмар", 2)], "midnight",
       "a backdoor that hides its command channel in a legitimate cloud service",
       "government networks are infiltrated and controlled through cloud storage",
       "a government network and a public cloud service", "C2 over a legitimate cloud API",
       "Illustration: a backdoored government workstation exchanging commands with a folder in an ordinary "
       "cloud storage service.",
       "Ілюстрація: урядовий комп'ютер із бекдором обмінюється командами через теку у звичайному хмарному "
       "сховищі."),
    _s("cloud_breach", [(r"cloud (provider|breach|tenant|storage|account)|хмарн\w* (провайдер|сервіс)|"
                         r"\bS3\b|bucket|Azure|\bAWS\b|Snowflake", 6)], "glacier",
       "data held by a third-party cloud provider", "records are taken from the provider's environment",
       "a cloud tenant", "third-party / cloud provider compromise",
       "Illustration: a cloud provider's storage holding a company's records, with a set of records leaving it.",
       "Ілюстрація: сховище хмарного провайдера з записами компанії, частина записів його залишає."),
    _s("breach_notice", [(r"data breach|breach (affect|notif)|notif(y|ies) .*breach|leak|exposed data|"
                          r"personal (data|information)|records|витік|персональн", 5),
                         (r"employees?|drivers?|customers?|patients?|users|людей|клієнт|співробітник", 2)],
       "paper", "personal records exposed in a breach", "the company notifies the affected people",
       "breach notification", "exposure of personal records (scope from the headline)",
       "Illustration: a breach notification and a stack of personal record cards, with the number of affected "
       "people.",
       "Ілюстрація: повідомлення про витік і стос карток із персональними даними та кількість постраждалих."),
    _s("credential_phish", [(r"phish|фішинг", 6), (r"credential|login|password|парол", 2)], "glacier",
       "a phishing page that imitates a sign-in", "victims are lured into handing over their credentials",
       "an email and a look-alike page", "lure -> fake sign-in -> captured credentials",
       "Illustration: a lure email leading to a look-alike sign-in page that captures the password.",
       "Ілюстрація: лист-приманка веде на підроблену сторінку входу, що перехоплює пароль."),
    _s("mfa_policy", [(r"\bMFA\b|multi-factor|2FA|two-factor|passwords?|passkey|парол|"
                       r"автентифікац|CJIS", 6)], "paper",
       "password and multi-factor authentication requirements", "organisations tighten sign-in requirements",
       "a sign-in with a second factor", "policy guidance (no incident)",
       "Illustration: a sign-in form with a password policy checklist and an approval request on a phone.",
       "Ілюстрація: форма входу з переліком вимог до пароля та запитом на підтвердження на телефоні."),
    _s("selfhosted_saas", [(r"self-hosted|SaaS|on-prem|власн\w* (сервер|інструмент)", 7)], "paper",
       "self-hosted infrastructure versus a SaaS subscription", "a business weighs control against convenience",
       "a server cabinet and a cloud service", "comparison (analysis, no incident)",
       "Illustration: a company's own server cabinet set against a SaaS subscription, with what each side "
       "controls.",
       "Ілюстрація: власна серверна шафа компанії поруч із SaaS-підпискою та переліком того, що контролює "
       "кожна сторона."),
    _s("ai_code_audit", [(r"\b(AI|LLM|model|agent)s?\W+(?:\w+\W+){0,3}(found|finds|discover\w*|spot\w*|"
                          r"audit\w*|hunt\w*|uncover\w*)|vulnerability (discovery|research)|bug[- ]hunting|"
                          r"(ШІ|модель)\W+(?:\w+\W+){0,3}(знайш|виявил|виявив)", 6),
                         (r"vulnerab|вразлив|bug|flaw|code|код", 2)],
       "violet", "AI-assisted analysis of source code", "a model inspects code and flags a weakness",
       "a code-review workspace", "static analysis assisted by a model",
       "Illustration: source code under automated review, with one function flagged as vulnerable.",
       "Ілюстрація: вихідний код під автоматизованим аналізом, одну функцію позначено як вразливу.",
       requires=r"\bAI\b|ШІ|LLM|machine learning"),
    _s("vuln_advisory", [(r"vulnerabilit|flaws?|вразлив|CVE-\d{4}-\d+|zero-day|0-day|patch|exploits?\b|"
                          r"cumulative updates?|security updates?|\bKB\d{7}\b", 4),
                         (r"reverse shells?", 2)], "midnight",
       "the affected product", "flaws are disclosed and patched", "a product advisory",
       "vulnerabilities as published (status from the evidence)",
       "Illustration: a security advisory for the affected product, listing its identifiers and patch status.",
       "Ілюстрація: бюлетень безпеки для вразливого продукту з ідентифікаторами та статусом виправлення."),
    _s("governance", [(r"не лише питання IT|board|CISO|strategy|стратег|compliance|regulation|NIS2|GDPR|"
                       r"budget|бюджет|у 20\d\d|in 20\d\d|що потрібно знати", 4)], "paper",
       "how an organisation governs cyber risk", "leaders plan security beyond the IT department",
       "a planning briefing", "analysis (no incident)",
       "Illustration: a planning document with a risk matrix and responsibilities across departments.",
       "Ілюстрація: плановий документ із матрицею ризиків і розподілом відповідальності між підрозділами."),
)
SPECS = {s.id: s for s in CATALOGUE}

FALLBACK = _s("dossier", [], "midnight", "the story's named subject", "reported without technical detail",
              "an editorial dossier", "insufficient detail for a scene",
              "Illustration: an editorial dossier card with the story's identifiers.",
              "Ілюстрація: редакційна картка справи з ідентифікаторами історії.")
SPECS[FALLBACK.id] = FALLBACK

_TEXT_WEIGHTS = {"main": 3.0, "title": 2.0, "post": 1.0, "excerpt": 1.0}


# ---------------------------------------------------------------- facts

_NUM = r"(?<![\w$-])(\d{1,3}(?:[ ,. ]\d{3})+|\d+(?:\.\d+)?)"
#: Scale words after a count ("37.6M records", "1.2 million people", "40 тис. клієнтів").
_UNIT = r"(?:\s*(M|million|mln|млн\.?|мільйон\w*|K|thousand|тис\.?|тисяч\w*|B|bn|billion|млрд\.?)(?![\w]))?"
_GAP = r"\s*(?:[^\W\d]+\s+){0,2}"           # up to two words: "customer records", "user accounts"
_FACT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("accounts", _NUM + _UNIT + r"\s*(?:\+\s*)?" + _GAP + r"(?:accounts|облікових записів|акаунт\w*)"),
    ("people", _NUM + _UNIT + _GAP + r"(?:people|individuals|persons|drivers|employees|customers|patients|users|"
                                    r"людей|осіб|клієнтів|водіїв)"),
    ("records", _NUM + _UNIT + _GAP + r"(?:records|(?<!облікових )записів)"),
    ("videos", _NUM + r"\s*(?:videos?|відео)"),
    ("flaws", _NUM + r"\s*(?:\w+\s){0,2}(?:flaws|vulnerabilities|bugs|вразливост\w*)"),
    ("years", _NUM + r"\s*(?:years|років|роки)"),
    ("days", _NUM + r"[- ]?(?:days?|днів|дні)"),
)
_MONEY = re.compile(r"\$\s?(\d+(?:[.,]\d+)?)\s*(million|billion|m|bn|мільйон\w*|млн|млрд)?", re.I)
_CVE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)


def _scale(unit: str) -> str:
    u = unit.lower().rstrip(".")
    if not u:
        return ""
    if u in ("m", "million", "mln", "млн") or u.startswith("мільйон"):
        return "M"
    if u in ("b", "bn", "billion", "млрд"):
        return "B"
    return "K"


def _clean_num(s: str) -> str:
    digits = re.sub(r"[ ,. ]", "", s) if re.fullmatch(r"\d{1,3}(?:[ ,. ]\d{3})+", s) else s
    try:
        n = float(digits)
    except ValueError:
        return s
    return f"{int(n):,}" if n == int(n) else s


def extract_facts(title: str, excerpt: str, post: str) -> dict[str, Any]:
    """Numbers and identifiers the headline (first) or the sources state. Only
    these may appear as figures in an image."""
    facts: dict[str, Any] = {}
    for text in (title, post, excerpt):
        for key, pat in _FACT_PATTERNS:
            if key in facts:
                continue
            m = re.search(pat, text, re.I)
            if m and m.group(1) != "0":
                unit = (m.group(2) or "") if m.re.groups >= 2 else ""
                facts[key] = _clean_num(m.group(1)) + _scale(unit)
                prefix = text[max(0, m.start() - 22):m.start()].lower()
                if re.search(r"(more than|over|понад|більше)\s*$", prefix):
                    facts[key + "_plus"] = True
                elif re.search(r"(nearly|almost|майже|близько)\s*$", prefix):
                    facts[key + "_approx"] = True
        if "money" not in facts:
            m = _MONEY.search(text)
            if m:
                unit = (m.group(2) or "").lower()
                unit = "M" if unit.startswith(("m", "мільйон", "млн")) else "B" if unit.startswith(("b", "млрд"))\
                    else ""
                facts["money"] = f"${m.group(1)}{unit}"
    cves = sorted({c.upper() for c in _CVE.findall(" ".join((title, post, excerpt)))})
    if cves:
        facts["cves"] = cves[:4]
    return facts


_NAME = re.compile(r"\b([A-Z][A-Za-z0-9$]*(?:[-.][A-Za-z0-9]+)*|[A-Z]{2,}[0-9]*)\b")
_NOT_ENTITY = {"The", "A", "An", "And", "Or", "Of", "In", "On", "To", "For", "With", "By", "As", "At", "From", "How",
               "Why", "What", "New", "Inside", "This", "That", "Over", "Hackers", "Attackers", "Court", "FBI", "AI",
               "Says", "Patches", "Exploit", "Exploits", "Linked", "Found", "Way", "Around", "Close", "Gap",
               "Webinar", "Explains", "Built", "Steal", "Sessions", "Modern", "Kits", "Phishing", "Data",
               "Breach", "Flaws", "Flaw", "Uses", "Using", "Weekly", "Recap", "More", "Bad", "Days", "Part",
               "Operation", "Six", "Unpatched", "Could", "Allow", "Remote", "Takeover", "Without", "Login",
               "Stolen", "Led", "Key", "Ransomware", "Industrial", "Software", "Products", "Tips", "Complying",
               "Requirements", "Password", "Self", "Suspect", "US", "Faces", "Years", "Prison", "Attack",
               "Attacks", "Malware", "Worm", "Resurfaces", "After", "Takedown", "Spread", "Lets", "Crash",
               "Servers", "Notifies", "Drivers", "People", "Affecting", "Nearly", "Clears", "Brothers",
               "Charges", "Crypto", "Heist", "Cuts", "Bug", "Disclosure", "Deadline", "Amid", "Threats",
               "Gateways", "Hacked", "Deploy", "Wiper", "Supply", "Chain", "Infects", "Major", "Brands", "Sites",
               "North", "Korean", "Stole", "Million", "Deepfake", "Video", "Calls", "Enables", "Server", "Level",
               "Command", "Injection", "Cloud", "Employee", "Provider", "Library", "Hide", "Activity", "Modified",
               "Linux", "Cryptomining", "Compromises", "Firm", "Russian", "Code", "Signing", "Trojanized",
               "Extension", "Fully", "Automated", "Warns", "Coming", "Soon", "Finds", "Agents", "Run",
               "Exploits", "Patch", "Second", "Life", "Spreading", "Vulnerability", "Zero"}


def _name_like(w: str) -> bool:
    return bool(re.search(r"\d|-|\$|[a-z][A-Z]|^[A-Z]{2,}", w))


def extract_entities(title: str, context: str = "") -> list[str]:
    """Product/organisation names in the headline. In a Title Case headline
    every word is capitalised, so a plain word counts only if the source text
    also capitalises it and never writes it in lower case ("Cursor" yes,
    "Earlier" no)."""
    words = [w for w in re.findall(r"[A-Za-z][\w$'-]*", title) if len(w) >= 4]
    title_case = bool(words) and sum(w[0].isupper() for w in words) / len(words) > 0.6
    out: list[str] = []
    for m in _NAME.finditer(title):
        w = m.group(1)
        if w in _NOT_ENTITY or len(w) < 2 or w in out:
            continue
        if title_case and not _name_like(w) and context and (
                re.search(r"\b" + re.escape(w.lower()) + r"\b", context)
                or not re.search(r"\b" + re.escape(w) + r"\b", context)):
            continue
        out.append(w)
    return out[:6]


# ---------------------------------------------------------------- brief

@dataclass(frozen=True)
class EditorialBrief:
    story_key: str
    scene: str
    palette: str
    subject: str
    action: str
    target: str
    environment: str
    mechanism: str
    entities: tuple[str, ...]
    impact: str
    supporting: tuple[str, ...]
    exclude: tuple[str, ...]
    confidence: str                    # high | medium | low
    evidence: tuple[str, ...]          # what in the sources selected the scene
    reason: str
    status: str                        # exploited | attacks_observed | suspected | not_reported | compromise
    facts: dict[str, Any] = field(default_factory=dict)
    library_id: str = ""               # Tier A photograph, when one is used
    category: str = ""
    seed: str = ""
    text: str = ""                     # lower-cased source text scenes may test for variants (not hashed)
    alternatives: tuple[tuple[str, float], ...] = ()

    def hashable(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("text", "evidence", "reason", "alternatives", "subject", "action", "target", "environment",
                  "mechanism", "impact", "supporting", "exclude"):
            d.pop(k, None)
        return {**d, "renderer": RENDERER_VERSION}

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("text", None)
        return d


def main_clause(title: str) -> str:
    return _CLAUSE_BREAK.split(title, maxsplit=1)[0]


def _post_text(story: Any) -> str:
    posts = getattr(story, "posts", None) or {}
    p = posts.get("en")
    if p is None:
        return ""
    return f"{getattr(p, 'title', '')}. {getattr(p, 'short_summary', '')}"


def score_scenes(texts: dict[str, str]) -> list[tuple[float, SceneSpec, list[str]]]:
    joined = " ".join(texts.values())
    out = []
    for spec in CATALOGUE:
        if spec.requires and not re.search(spec.requires, joined, re.I):
            continue
        # The first pattern names the scene's subject; the others only add
        # weight. "Linux" alone must not make a story a kernel crash.
        if spec.patterns and not re.search(spec.patterns[0][0], joined, re.I):
            continue
        total, why = 0.0, []
        for pat, w in spec.patterns:
            for where, text in texts.items():
                m = re.search(pat, text, re.I)
                if m:
                    total += w * _TEXT_WEIGHTS[where]
                    why.append(f"{where}: '{m.group(0)}'")
        if total:
            out.append((total, spec, why))
    out.sort(key=lambda t: -t[0])
    return out


def build(story: Any) -> EditorialBrief:
    from ...pipeline.evidence import assess

    anchor = story.anchor
    title = str(anchor.title or "")
    excerpt = str(getattr(anchor, "raw_content", "") or "")[:700]
    post = _post_text(story)
    texts = {"main": main_clause(title), "title": title, "post": post, "excerpt": excerpt}
    ranked = score_scenes(texts)
    ev = assess(anchor)
    category = str(anchor.category or "other").lower()
    status = ("compromise" if ev.compromise == "confirmed" else ev.exploitation or "not_reported")

    spec, why, conf = FALLBACK, ["no catalogue scene is supported by the sources"], "low"
    if ranked:
        top, spec0, why0 = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        main_hit = any(w.startswith("main:") or w.startswith("title:") for w in why0)
        if top >= 12 and main_hit:
            spec, why, conf = spec0, why0, ("high" if top - second >= 6 else "medium")
        elif top >= 6 and main_hit:
            spec, why, conf = spec0, why0, "medium"
        else:
            # Only the excerpt/post supports a scene: too weak to depict it.
            why = [f"weak support for '{spec0.id}' ({top:.0f}, not in the headline)", *why0]
    lib = library.find(" ".join((title, excerpt, post))) if spec.id == "hpc_hall" else None
    facts = extract_facts(title, excerpt, post)
    # Entities are drawn in the image, so they come from the headline and the
    # source text only: rewording our own post must not change the picture.
    entities = tuple(extract_entities(title, excerpt))
    reason = (f"'{spec.id}' scored highest ({ranked[0][0]:.0f}) on " + ", ".join(why[:4])
              if spec is not FALLBACK and ranked else "fallback: " + "; ".join(why[:3]))
    if lib is not None:
        reason += f"; verified photograph '{lib.id}' matches the named subject ({lib.license})"
    impact = ""
    for k, label in (("accounts", "accounts"), ("people", "people"), ("records", "records"), ("money", ""),
                     ("videos", "videos"), ("years", "years")):
        if k in facts:
            pre = "over " if facts.get(k + "_plus") else "nearly " if facts.get(k + "_approx") else ""
            impact = f"{pre}{facts[k]} {label}".strip()
            break
    return EditorialBrief(
        story_key=story.key, scene=spec.id, palette=spec.palette, subject=spec.subject, action=spec.action,
        target=", ".join(entities[:3]) or spec.subject, environment=spec.environment, mechanism=spec.mechanism,
        entities=entities, impact=impact, supporting=spec.supporting, exclude=spec.exclude, confidence=conf,
        evidence=tuple(why[:6]), reason=reason, status=status, facts=facts,
        library_id=lib.id if lib else "", category=category, seed=f"{story.key}:{RENDERER_VERSION}",
        text=" ".join(texts.values()).lower(),
        alternatives=tuple((s.id, round(sc, 1)) for sc, s, _ in ranked[1:4]))


def alt_text(brief: EditorialBrief) -> dict[str, str]:
    spec = SPECS.get(brief.scene, FALLBACK)
    en, ua = spec.alt_en, spec.alt_ua
    if brief.library_id:
        a = library.get(brief.library_id)
        if a is not None:
            # Mirrors the annotation scenes/hpc_hall.py draws.
            if brief.facts.get("accounts") or re.search(r"accounts|обліков", brief.text):
                what_en, what_ua = "the compromised accounts", "скомпрометованих облікових записів"
            elif re.search(r"offline|offlline|shut down|вимкн|відключ", brief.text):
                what_en, what_ua = "the machine taken offline", "вимкнення машини"
            else:
                what_en, what_ua = "the security breach", "інциденту безпеки"
            en = f"Photograph: {a.subject}, with an annotation of {what_en}. {a.credit}."
            ua = f"Фото: {a.subject_ua}, з позначкою {what_ua}. {a.credit_ua}."
    return {"en": en, "ua": ua}


def inputs_hash(brief: EditorialBrief) -> str:
    return hashlib.sha256(json.dumps(brief.hashable(), sort_keys=True, default=str).encode()).hexdigest()[:16]


SceneFn = Callable[[Any, EditorialBrief], None]
