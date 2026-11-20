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
    #: The scene never applies when this matches: another scene owns that subject.
    excludes: str = ""
    #: The headline must name this actor (e.g. a law-enforcement body); keeps
    #: an action word like "exposed" from routing a vulnerability story here.
    actor: str = ""
    #: The headline must state what the picture asserts (a court action, a
    #: wiper, mining, a cloud service, an extension). A keyword elsewhere in
    #: the headline ("fake court notices", "forget GPU thefts") is not enough.
    head_requires: str = ""


def _s(id: str, pats: list[tuple[str, float]], palette: str, subject: str, action: str, environment: str,
       mechanism: str, alt_en: str, alt_ua: str, *, supporting: tuple[str, ...] = (),
       exclude: tuple[str, ...] = (), requires: str = "", excludes: str = "", actor: str = "",
       head_requires: str = "") -> SceneSpec:
    return SceneSpec(id, tuple(pats), palette, subject, action, environment, mechanism, supporting,
                     ("generic cubes", "glowing orbs", "hooded hackers", "brand logos") + exclude, alt_en, alt_ua,
                     requires, excludes, actor, head_requires)


# Order matters only for ties: more specific scenes first.
CATALOGUE: tuple[SceneSpec, ...] = (
    _s("weekly_recap", [(r"weekly recap|week in review|тижнев\w* (огляд|дайджест)|дайджест|ThreatsDay|"
                         r"\+\s*\d+ more stories", 9)], "midnight",
       "several unrelated products, each with its own new flaw", "a roundup of the week's vulnerabilities",
       "a board of product tiles", "one marker per product named in the roundup",
       "Illustration: a lightning bolt splitting four product tiles, each flagged with a new vulnerability.",
       "Ілюстрація: блискавка між чотирма плитками продуктів, на кожній позначено нову вразливість."),
    _s("hpc_hall", [(r"supercomput|суперкомп|супер-?ПК|\bHPC\b|Fugaku|Фугаку|top500", 6)], "midnight",
       "a national supercomputer installation", "unauthorised access and stolen user accounts",
       "a high-performance computing machine hall", "account compromise (no technical detail published)",
       "Illustration: a supercomputer machine hall, with the figure the story reports set beside it.",
       "Ілюстрація: машинний зал суперкомп'ютера з цифрою, яку наводить новина.", supporting=("account list", "count from the headline")),
    _s("ci_pinning", [(r"SHA pinning|pinn(ed|ing) (to|actions)|GitHub Actions?|\.github/workflows|"
                       r"CI/CD|workflow file", 6), (r"GitHub", 2)], "paper",
       "a GitHub Actions workflow and its dependency references",
       "a malicious commit passed off as a trusted action", "a CI/CD workflow file and commit graph",
       "mutable tag vs immutable commit SHA; an impostor commit reachable by reference",
       "Illustration: a version tag that can be moved, and a pinned commit that still points at look-alike "
       "code instead of the official action.",
       "Ілюстрація: тег версії, який можна перемістити, і закріплений коміт, що все одно вказує на код-"
       "підробку замість офіційної дії."),
    _s("session_theft", [(r"session|токен|token|cookie|AiTM|adversary-in-the-middle|\bM365\b|Microsoft 365|"
                          r"Office 365|\bOAuth\b", 5), (r"phishing kit|фішинг", 3)], "glacier",
       "a cloud office sign-in page cloned by a phishing kit",
       "the victim's session token is captured and replayed", "a browser sign-in flow",
       "adversary-in-the-middle proxy relays the login and keeps the session token",
       "Illustration: a sign-in passes through a phishing kit's relay to the real service, while a copy of "
       "the session token is replayed by the attacker.",
       "Ілюстрація: вхід проходить через ретранслятор фішингового набору до справжнього сервісу, а копію "
       "токена сесії зловмисник використовує повторно.",
       exclude=("real Microsoft logos or interface",)),
    _s("rmm_console", [(r"N-central|N-able|\bRMM\b|remote monitoring|remote management|ScreenConnect|"
                        r"ConnectWise|Kaseya|SimpleHelp|віддален\w* (керуван|адміністр)|endpoint management|\bUEM\b", 7)], "midnight",
       "a remote monitoring and management console and its fleet of endpoints",
       "attackers abuse the management platform to push their own payload to managed machines",
       "an MSP's management console", "flaws in the management server; payload deployed through it",
       "Illustration: a remote-management control bar with strings to a fleet of managed computers.",
       "Ілюстрація: панель віддаленого керування, від якої тягнуться нитки до парку керованих комп'ютерів.",
       # the vendor's name alone is not its RMM product (N-able also runs an email-security cloud)
       head_requires=r"N-central|\bRMM\b|remote monitoring|remote management|ScreenConnect|ConnectWise|Kaseya|"
                     r"SimpleHelp|віддален\w* (?:керуван|адміністр)|endpoint management|\bUEM\b|MSPs?\b"),
    _s("patch_to_exploit", [(r"fully[- ]automated|повністю автоматизован|autonomous|agentic|AI agents?|"
                             r"ШІ-агент|агентн", 6), (r"\bAI\b|ШІ|штучн", 2),
                            (r"exploit|patch|вразлив|кібератак|attack", 2)], "violet",
       "an automated AI pipeline that turns a published patch into a working exploit",
       "AI agents analyse a fix and generate an exploit without a human operator",
       "a code-review workspace", "patch diffing -> vulnerable function -> generated exploit",
       "Illustration: a software fix projected into the teeth of a key: automated agents turning a patch "
       "into an exploit.",
       "Ілюстрація: виправлення коду проєктується на зубці ключа: автоматизовані агенти перетворюють патч на"
       " експлойт.",
       # The picture asserts a patch turned into an exploit: the sources must say both.
       requires=r"(?=[\s\S]*(?:\bAI\b|ШІ|штучн|agent))(?=[\s\S]*(?:patch|патч|виправлен|\bfix))"),
    _s("disclosure_deadline", [(r"disclosure (deadline|policy|window)|Project Zero|розкритт", 7)], "paper",
       "a vulnerability disclosure timeline", "the time vendors get to ship a fix is being shortened",
       "a bug-tracker timeline", "report -> fix deadline -> public disclosure",
       "Illustration: a tape measure starting at a bug, cut short by scissors: the disclosure deadline gets "
       "shorter.",
       "Ілюстрація: рулетка, що починається від «жука», укорочена ножицями: строк розкриття скорочується."),
    _s("ai_offensive_tool", [(r"ARTEX|Artex|AI-powered (cyber)?attack|ШІ-інструмент|AI tool", 7),
                             (r"cloud|хмар", 1)], "violet",
       "an AI-driven offensive tool", "a tool built for defence is run against real targets",
       "an operator console", "automated reconnaissance and intrusion steps",
       "Illustration: a security-testing tool's sights swung from a practice target onto a real target.",
       "Ілюстрація: приціл інструмента для тестування безпеки, переведений з навчальної мішені на справжню "
       "ціль."),
    _s("refrigeration_controller", [(r"refrigerat|холодильн\w* (контролер|обладнан)|Danfoss|cold room|"
                                     r"temperature controller|холодильн\w* систем", 8)], "glacier",
       "a commercial refrigeration controller", "remote takeover of the controller without a login",
       "a refrigerated display case and its controller", "unauthenticated network access to the controller",
       "Illustration: a refrigeration controller on a cold-room wall, its cable fitted with an open padlock.",
       "Ілюстрація: контролер холодильної камери на стіні, на його кабелі — відкритий замок."),
    _s("ics_controller", [(r"Siemens|SIMATIC|\bPLC\b|SCADA|\bICS\b|\bOT\b|industrial|промислов|Schneider|"
                           r"Rockwell|Mitsubishi Electric|ABB\b|HMI\b", 6)], "steel",
       "industrial control hardware and engineering software", "security advisory for industrial products",
       "a control cabinet", "advisory-level vulnerabilities in engineering software and controllers",
       "Illustration: industrial controller hardware on a DIN rail, with the advisory's identifier.",
       "Ілюстрація: промисловий контролер на DIN-рейці з ідентифікатором бюлетеня безпеки."),
    _s("court_case", [(r"\bcourt\b|charges?\b|pleads?|pleaded|guilty|sentenc\w*|extradit\w*|prison|convicted|"
                       r"indict\w*|acquit\w*|clears?\b|arrest\w*|\bсуд\w*|визнав провину|вирок|екстрадиц\w*|"
                       r"арешт\w*|ув'язнен", 8)], "court",
       "a criminal case against an alleged cybercriminal", "the case reaches a court decision",
       "a court docket", "legal proceedings (no technical detail)",
       "Illustration: the court case's outcome with its key figure, as reported.",
       "Ілюстрація: рішення в судовій справі з ключовою цифрою, як повідомляється.",
       head_requires=r"sentenc|convict|plead|guilty|\bplea\b|indict|charged (?:with|over|for)|charges? (?:against|filed|dropped)|"
                     r"extradit|acquit|\bclears?\b|cleared|court (?:rules|ruled|orders|ordered|clears|dismiss|approv|"
                     r"blocks|finds)|\btrial\b|\bjudge|prison|\bjail|lawsuit|\bsues?\b|\bsued\b|засуд|вирок|"
                     r"визна\w* провину|екстрадиц|виправда|суд\w* (?:ухвал|визна|постанов|відмов)|позов"),
    _s("police_takedown", [(r"\btake[sn]? down\b|takedown of|dismantl\w*|\bseiz\w*|\bbust(?:ed|s)?\b|\barrest\w*|"
                            r"\bdetain\w*|\bcharg(?:ed|es)\b|\braid\w*|\bexpos(?:ed|es)\b|\buncover\w*|"
                            r"викри\w*|затрима\w*|заарешту\w*|ліквідува\w*|вилучи\w*|повідомили про підозру|обшук\w*", 10),
                           (r"servers?|infrastructure|domains?|group|gang|network|інфраструктур|угрупован", 2)],
       "steel", "a law-enforcement action against a criminal group or its infrastructure",
       "police expose, arrest or take down the group, as the headline states",
       "the group's seized or exposed operation", "law-enforcement action (only what the sources state)",
       "Illustration: a law-enforcement action, with evidence tags naming what the story reports.",
       "Ілюстрація: дія правоохоронців з бирками-доказами того, про що повідомляє новина.",
       actor=r"\bpolice\b|\bFBI\b|Europol|Interpol|law enforcement|\bDOJ\b|Justice Department|prosecutors?|"
             r"\bNCA\b|Operation \w+|поліці\w*|Нацполіц\w*|кіберполіц\w*|ФБР|правоохорон\w*|СБУ|прокурату\w*|"
             r"Європол"),
    _s("crypto_theft", [(r"stole .{0,40}crypto|crypto(currency)? (heist|theft)|stolen from (Binance|Bybit|Coinbase|"
                         r"an? (crypto )?exchange)|вкрадені з|викрав .{0,40}крипто|drain(ed|er)", 7),
                        (r"\$\s?\d|\d+[,.]?\d* ?(million|млн)", 2)], "midnight",
       "cryptocurrency taken from its owner", "funds move out of a wallet or exchange",
       "a wallet or exchange balance", "theft of cryptocurrency (amount only as reported)",
       "Illustration: the reported stolen amount set in large hollow figures that are draining empty.",
       "Ілюстрація: заявлена викрадена сума великими порожнистими цифрами, з яких витікає вміст.",
       requires=r"crypto|bitcoin|ethereum|binance|bybit|wallet|крипто|гаманц|блокчейн",
       # a court decision or a deepfake method is the story's subject, not the theft
       excludes=r"\bcourt\b|charges|acquit\w*|plead\w*|sentenc\w*|convicted|\bсуд\w*|deepfake|діпфейк"),
    _s("payment_skimmer", [(r"skimm\w*|checkout pages?|payment card (details|data)|card details|Magecart|"
                            r"платіжн\w* карт", 8)], "glacier",
       "a website checkout page with a card skimmer", "card details are copied as customers pay",
       "an online checkout", "script on the checkout page copies card data (only as reported)",
       "Illustration: an online checkout form peeled back to reveal a hidden copy of its card fields.",
       "Ілюстрація: форма оплати на сайті, під загнутим кутом якої — прихована копія полів картки."),
    _s("deepfake_call", [(r"deepfake|діпфейк|deep-fake|video calls?|відеодзвін", 20)], "violet",
       "a video call with a synthetic participant", "victims are deceived by deepfaked video calls",
       "a video-conferencing window", "real-time face synthesis on a call",
       "Illustration: a video call whose participant wears a mask over a synthetic face.",
       "Ілюстрація: відеодзвінок, учасник якого носить маску поверх синтетичного обличчя."),
    _s("third_party_script", [(r"supply[- ]chain attack infects|Optimizely|third-party (script|tag)|"
                               r"(JavaScript|JS) (library|tag)|Magecart|skimmer|CDN", 8)], "midnight",
       "a shared third-party script loaded by many websites",
       "a tampered script is served to every site that includes it",
       "websites loading one third-party tag", "supply-chain compromise of a hosted script",
       "Illustration: one tampered script file threaded to many websites at once.",
       "Ілюстрація: один змінений файл скрипту, пов'язаний одночасно з багатьма сайтами."),
    _s("compromised_sites", [(r"sites? .*(hacked|compromised)|сайти .*зламали|watering[- ]hole|"
                              r"websites? (hacked|compromised)", 8), (r"iPhone|iOS|crypto|криптовалют", 2)],
       "midnight", "legitimate company websites altered to attack their visitors",
       "visitors are served wallet-draining scripts and iPhone exploits", "several trusted websites",
       "injected scripts on compromised sites",
       "Illustration: a row of company websites carrying the same injected element, and a phone showing a "
       "warning.",
       "Ілюстрація: ряд сайтів компаній з однаковим вбудованим елементом і телефон із попередженням."),
    _s("usb_worm", [(r"\bUSB\b|worm|хробак|черв'?як|Retadup|removable", 7)], "forest",
       "a USB worm spreading between computers", "the worm copies itself through removable drives",
       "an office desk", "removable-media propagation, then a second-stage loader",
       "Illustration: a USB flash drive with a trail of copies of itself.",
       "Ілюстрація: USB-флешка зі слідом власних копій."),
    _s("gpu_cryptominer", [(r"\bGPU\b|NVIDIA|graphics card|відеокарт", 7), (r"cryptomin|miner|майнер", 2)],
       "forest", "a GPU hijacked for cryptomining", "a modified driver library hides the GPU load",
       "a Linux server with a graphics card", "tampered monitoring library reports idle while the GPU is maxed",
       "Illustration: a hot graphics card beside a gauge whose reported reading is low while the real load "
       "is pinned high.",
       "Ілюстрація: гаряча відеокарта поруч зі шкалою: показане навантаження низьке, а справжнє — "
       "максимальне.", requires=r"\bGPU\b|NVIDIA|graphics card|відеокарт",
       head_requires=r"cryptomin|crypto[- ]?jack|\bminer|mining|майн"),
    _s("kernel_dos", [(r"crash|denial[- ]of[- ]service|\bDoS\b|kernel panic|NoisyTCP|TCP", 6),
                      (r"Linux", 2)], "midnight",
       "Linux servers and their network stack", "crafted network traffic crashes the server",
       "a server console", "malformed TCP traffic triggering a kernel failure",
       "Illustration: a server knocked over by a noisy stream of network traffic.",
       "Ілюстрація: сервер, перекинутий шумним потоком мережевого трафіку."),
    _s("irc_injection", [(r"\bIRC\b|UnrealIRCd", 8), (r"command injection", 3)], "midnight",
       "an IRC server", "a crafted message makes the server run attacker commands",
       "a chat server and its shell", "command injection through the IRC daemon",
       "Illustration: a chat message broken at a delimiter that is not neutralised, the broken-off command "
       "falling into a server.",
       "Ілюстрація: повідомлення в чаті, розірване на неекранованому роздільнику; відламана команда падає в "
       "сервер."),
    _s("edge_wiper", [(r"gateways?|firewall|Check Point|FortiGate|Fortinet|Palo Alto|Ivanti|Citrix|"
                       r"VPN appliance|шлюз", 6), (r"wiper|ESXi|вайпер", 4)], "ember",
       "a network security gateway", "attackers break in through the gateway and wipe virtual machines",
       "a server room edge", "edge-device exploit -> hypervisor -> destructive wiper",
       "Illustration: a security gateway with a lit crack, leading to a virtualisation host whose layers "
       "break apart.",
       "Ілюстрація: шлюз безпеки з тріщиною, від якої шлях веде до хоста віртуалізації, що розпадається.",
       head_requires=r"wiper|\bwipe[sd]?\b|destroy|erase|знищ|стира|ESXi"),
    _s("code_signing", [(r"code[- ]signing|signing (server|certificate|key)|підпис\w* код", 7),
                        (r"Log4Shell|Log4j|vCenter", 3)], "ember",
       "a code-signing server and its certificate", "attackers reach the signing infrastructure",
       "a build and signing environment", "exploited server -> signing server -> trusted certificate exposed",
       "Illustration: a cracked code-signing seal at the end of an intrusion path.",
       "Ілюстрація: тріснута печатка підпису коду в кінці шляху вторгнення."),
    _s("dev_supply_chain", [(r"API key|stolen key|extension|VS Code|marketplace|\bnpm\b|PyPI|package|"
                             r"розширенн|poisoned update|отруєн\w* оновленн|\b[\w]+-js\b|\bSDK\b", 6), (r"trojaniz|backdoor|троян", 3)],
       "midnight",
       "a developer tool supply chain", "a stolen key leads to a trojanised developer extension",
       "a code editor and extension marketplace", "leaked credential -> publishing access -> malicious update",
       "Illustration: a stolen key turned in the lock of a code-editor extension listing marked trojanized; "
       "its contents are not described.",
       "Ілюстрація: викрадений ключ у замку сторінки розширення редактора коду з позначкою «троян»; його "
       "вміст не описано.",
       head_requires=r"extension|marketplace|VS Code|plugin|add-?on|розширен"),
    _s("ransomware_impact", [(r"ransomware|програм\w*-?вимагач|вимагач|encrypt\w* (files|servers)|"
                              r"зашифрува", 7)], "ember",
       "systems encrypted by ransomware", "files and servers are made unavailable",
       "the affected organisation's systems", "encryption of files and servers",
       "Illustration: the affected systems bound in chains and locked with a large padlock.",
       "Ілюстрація: уражені системи, скуті ланцюгами й замкнені великим замком."),
    _s("telecom", [(r"telecom|телеком|\b5G\b|mobile network|operator|оператор|base station|зв'язку", 6)],
       "midnight", "telecommunications infrastructure", "operators harden the network against disruption",
       "a mobile network site", "network resilience (analysis, no incident)",
       "Illustration: a mobile network mast against a dusk skyline, with radio waves.",
       "Ілюстрація: щогла мобільного зв'язку на тлі вечірнього міста з радіохвилями."),
    _s("espionage_backdoor", [(r"backdoors?|\bC2\b|command-and-control|espionage|шпигун|\bAPT\b|"
                               r"government networks|урядов|держустанов|Turla|steal emails from gov", 6),
                              (r"cloud|хмар", 2)], "midnight",
       "a backdoor that hides its command channel in a legitimate cloud service",
       "government networks are infiltrated and controlled through cloud storage",
       "a government network and a public cloud service", "C2 over a legitimate cloud API",
       "Illustration: a government building with a side door open to an ordinary cloud service.",
       "Ілюстрація: урядова будівля з відчиненими бічними дверима до звичайного хмарного сервісу.",
       head_requires=r"cloud|хмар|Google Drive|OneDrive|Dropbox|Graph API|\bSaaS\b"),
    _s("cloud_breach", [(r"cloud (provider|breach|tenant|storage|account|credentials|keys)|хмарн\w* (провайдер|сервіс)|"
                         r"\bS3\b|bucket|Azure|\bAWS\b|Snowflake", 6)], "glacier",
       "data held by a third-party cloud provider", "records are taken from the provider's environment",
       "a cloud tenant", "third-party / cloud provider compromise",
       "Illustration: a key turned in the keyhole of a cloud service.",
       "Ілюстрація: ключ у замковій щілині хмарного сервісу."),
    _s("breach_notice", [(r"data breach|breach (affect|notif)|notif(y|ies) .*breach|leak|exposed data|"
                          r"personal (data|information)|records|витік|персональн", 5),
                         (r"employees?|drivers?|customers?|patients?|users|людей|клієнт|співробітник", 2)],
       "paper", "personal records exposed in a breach", "the company notifies the affected people",
       "breach notification", "exposure of personal records (scope from the headline)",
       "Illustration: an envelope of breach notifications with redacted record cards and the number of "
       "people affected.",
       "Ілюстрація: конверт із повідомленнями про витік, приховані картки записів і кількість постраждалих."),
    _s("credential_phish", [(r"phish|фішинг", 6), (r"credential|login|password|парол", 2)], "glacier",
       "a phishing page that imitates a sign-in", "victims are lured into handing over their credentials",
       "an email and a look-alike page", "lure -> fake sign-in -> captured credentials",
       "Illustration: a sign-in card hanging from a fishing hook, its password highlighted.",
       "Ілюстрація: картка входу на рибальському гачку з виділеним паролем."),
    _s("mfa_policy", [(r"\bMFA\b|multi-factor|2FA|two-factor|passwords?|passkey|парол|"
                       r"автентифікац|CJIS", 6)], "paper",
       "password and multi-factor authentication requirements", "organisations tighten sign-in requirements",
       "a sign-in with a second factor", "policy guidance (no incident)",
       "Illustration: a key ring holding a password key and a hardware security key.",
       "Ілюстрація: зв'язка з ключем-паролем і апаратним ключем безпеки.",
       excludes=r"phish|фішинг"),
    _s("selfhosted_saas", [(r"self-hosted|SaaS|on-prem|власн\w* (сервер|інструмент)", 7)], "paper",
       "self-hosted infrastructure versus a SaaS subscription", "a business weighs control against convenience",
       "a server cabinet and a cloud service", "comparison (analysis, no incident)",
       "Illustration: a balance weighing a self-hosted server cabinet against a SaaS cloud.",
       "Ілюстрація: терези, на яких власна серверна шафа зважується проти SaaS-хмари."),
    _s("ai_code_audit", [(r"\b(AI|LLM|model|agent)s?\W+(?:\w+\W+){0,3}(found|finds|discover\w*|spot\w*|"
                          r"audit\w*|hunt\w*|uncover\w*)|vulnerability (discovery|research)|bug[- ]hunting|"
                          r"(ШІ|модель)\W+(?:\w+\W+){0,3}(знайш|виявил|виявив)", 6),
                         (r"vulnerab|вразлив|bug|flaw|code|код", 2)],
       "violet", "AI-assisted analysis of source code", "a model inspects code and flags a weakness",
       "a code-review workspace", "static analysis assisted by a model",
       "Illustration: abstract source code under a scan line, with a magnifying lens over one flagged line.",
       "Ілюстрація: абстрактний вихідний код під лінією сканування, лупа над однією позначеною рядком.",
       requires=r"\bAI\b|ШІ|LLM|machine learning"),
    _s("malware_campaign", [(r"\bRAT\b|remote access trojan|info-?stealer|\bstealers?\b|\bloaders?\b|"
                             r"backdoors?|trojan|malware|шкідлив\w* ПЗ|троян|стилер|бекдор", 5),
                            (r"campaign|кампані|variant|варіант", 2),
                            (r"ClickFix|phishing|lures?|fake|impersonat|фішинг|підробн", 2)], "forest",
       "a malware family named by the sources", "the malware is delivered to and runs on a victim's computer",
       "a delivery channel and a victim's laptop", "delivery as stated by the sources (else none drawn)",
       "Illustration: a malicious payload travelling to a laptop.",
       "Ілюстрація: шкідливе навантаження на шляху до ноутбука.",
       head_requires=r"\bRAT\b|trojan|stealer|loader|backdoor|malware|шкідлив|троян|стилер|бекдор",
       excludes=r"ransomware|\bUSB\b|worm|cryptomin|\bminer|PyPI|\bnpm\b|extension|розширен|"
                r"cloud service|хмарн\w* сервіс|Google Drive|OneDrive|Dropbox|"
                r"ThreatsDay|weekly recap|week in review|roundup|\+\s*\d+ more stories|дайджест"),
    _s("vuln_advisory", [(r"vulnerabilit|flaws?|вразлив|CVE-\d{4}-\d+|zero-day|0-day|patch|exploits?\b|"
                          r"cumulative updates?|security updates?|\bKB\d{7}\b", 4),
                         (r"reverse shells?", 2)], "midnight",
       "the affected product", "flaws are disclosed and patched", "a product advisory",
       "vulnerabilities as published (status from the evidence)",
       "Illustration: a security advisory for the affected product, listing its identifiers and patch status.",
       "Ілюстрація: бюлетень безпеки для вразливого продукту з ідентифікаторами та статусом виправлення."),
    _s("governance", [(r"не лише питання IT|board|CISO|strategy|стратег|compliance|regulation|NIS2|GDPR|"
                       r"budget|бюджет|у 20\d\d році|що потрібно знати", 4)], "paper",
       "how an organisation governs cyber risk", "leaders plan security beyond the IT department",
       "a planning briefing", "analysis (no incident)",
       "Illustration: three cards on a boardroom table, each with a question about data, detection and "
       "recovery.",
       "Ілюстрація: три картки на столі для нарад із запитаннями про дані, виявлення та відновлення."),
)
SPECS = {s.id: s for s in CATALOGUE}

FALLBACK = _s("dossier", [], "midnight", "the story's named subject", "reported without technical detail",
              "an editorial dossier", "insufficient detail for a scene",
              "Illustration: an editorial dossier card with the story's identifiers.",
              "Ілюстрація: редакційна картка справи з ідентифікаторами історії.")
SPECS[FALLBACK.id] = FALLBACK

_TEXT_WEIGHTS = {"main": 3.0, "title": 2.0, "post": 1.0, "excerpt": 1.0}


# ---------------------------------------------------------------- facts

_NUM = r"(?<![\w$.,-])(\d{1,3}(?:[ ,. ]\d{3})+|\d+(?:\.\d+)?)"
#: Scale words after a count ("37.6M records", "1.2 million people", "40 тис. клієнтів").
_UNIT = r"(?:\s*(M|million|mln|млн\.?|мільйон\w*|K|thousand|тис\.?|тисяч\w*|B|bn|billion|млрд\.?)(?![\w]))?"
_GAP = r"\s*(?:[^\W\d]+\s+){0,2}"           # up to two words: "customer records", "user accounts"
_FACT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("accounts", _NUM + _UNIT + r"\s*(?:\+\s*)?" + _GAP + r"(?:accounts|облікових записів|акаунт\w*)"),
    ("people", _NUM + _UNIT + _GAP + r"(?:people|individuals|persons|drivers|employees|customers|patients|users|"
                                    r"людей|осіб|клієнтів|водіїв)"),
    ("records", _NUM + _UNIT + _GAP + r"(?:records|(?<!облікових )записів)"),
    ("videos", _NUM + r"\s*(?:[^\W\d]+\s+){0,3}(?:videos?|відео)"),
    ("sites", _NUM + r"\s*(?:[^\W\d]+\s+){0,2}(?:web ?sites|sites|web destinations|сайт\w*)"),
    # not a CVSS score ("CVSS 10.0 flaw" is one flaw rated 10.0)
    ("flaws", r"(?<!cvss )(?<!cvss: )(?<!score of )" + _NUM + r"\s*(?:[\w-]+\s){0,2}(?:flaws|vulnerabilities|bugs|"
              r"вразливост\w*)"),
    ("years", _NUM + r"\s*(?:years|років|роки)"),
    ("days", _NUM + r"[- ]?(?:days?|днів|дні)"),
)
#: Organisations affected, counted ("40 Irish credit unions", "12 hospitals").
#: The words between the number and the noun are kept when they are a plain
#: qualifier ("Irish", "regional"); the label stays English and ASCII.
_ORG_NOUNS = {
    "credit unions": "credit unions", "banks": "banks", "hospitals": "hospitals", "companies": "companies",
    "organizations": "organizations", "organisations": "organisations", "firms": "firms",
    "businesses": "businesses", "schools": "schools", "universities": "universities", "councils": "councils",
    "municipalities": "municipalities", "agencies": "agencies", "retailers": "retailers", "insurers": "insurers",
    "clinics": "clinics", "pharmacies": "pharmacies", "school districts": "school districts",
    "кредитних спілок": "credit unions", "банків": "banks", "лікарень": "hospitals", "компаній": "companies",
    "організацій": "organizations", "шкіл": "schools", "університетів": "universities",
}
_ORGS = re.compile(r"(?<![\w$.,-])(\d{1,4})\s+((?:[A-Za-z][\w-]*\s+){0,2}?)(" +
                   "|".join(sorted(map(re.escape, _ORG_NOUNS), key=len, reverse=True)) + r")\b", re.I)


def _org_noun(m: re.Match[str]) -> str:
    noun = _ORG_NOUNS[m.group(3).lower()]
    qual = m.group(2).strip()
    if qual and qual.isascii() and len(qual) <= 18 and not re.search(r"\d", qual):
        return f"{qual} {noun}"
    return noun


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
                if re.search(r"(more than|over|at least|понад|більше|щонайменше)\s*$", prefix):
                    facts[key + "_plus"] = True
                elif re.search(r"(nearly|almost|майже|близько)\s*$", prefix):
                    facts[key + "_approx"] = True
        if "money" not in facts:
            m = _MONEY.search(text)
            if m:
                unit = (m.group(2) or "").lower()
                unit = "M" if unit.startswith(("m", "мільйон", "млн")) else "B" if unit.startswith(("b", "млрд"))\
                    else ""
                # "40,5 млн" is a decimal comma (Ukrainian), "1,500" a thousands separator
                amount = re.sub(r"^(\d+),(\d{1,2})$", r"\1.\2", m.group(1))
                facts["money"] = f"${amount}{unit}"
                prefix = text[max(0, m.start() - 22):m.start()].lower()
                if re.search(r"(more than|over|at least|понад|більше|щонайменше)\s*$", prefix):
                    facts["money_plus"] = True
                elif re.search(r"(nearly|almost|майже|близько)\s*$", prefix):
                    facts["money_approx"] = True
        if "orgs" not in facts:
            m = _ORGS.search(text)
            if m and m.group(1) != "0":
                facts["orgs"] = _clean_num(m.group(1))
                facts["orgs_noun"] = _org_noun(m)
    # The headline rounds ("$40M"); the excerpt states the same amount precisely
    # ("more than $40.5 million"): draw the precise figure with its qualifier.
    if facts.get("money") and excerpt:
        m = _MONEY.search(excerpt)
        if m:
            unit = (m.group(2) or "").lower()
            unit = "M" if unit.startswith(("m", "мільйон", "млн")) else "B" if unit.startswith(("b", "млрд")) else ""
            amount = re.sub(r"^(\d+),(\d{1,2})$", r"\1.\2", m.group(1))
            head = re.match(r"\$(\d+)([MB])$", str(facts["money"]))          # a rounded headline figure only
            if head and "." in amount and amount.split(".")[0] == head.group(1) and head.group(2) == unit:
                prefix = excerpt[max(0, m.start() - 22):m.start()].lower()
                facts["money"] = f"${amount}{unit}"
                facts.pop("money_approx", None)
                if re.search(r"(more than|over|at least|понад|більше|щонайменше)\s*$", prefix):
                    facts["money_plus"] = True
                elif re.search(r"(nearly|almost|майже|близько)\s*$", prefix):
                    facts["money_approx"] = True
    cves = sorted({c.upper() for c in _CVE.findall(" ".join((title, post, excerpt)))})
    if cves:
        facts["cves"] = cves[:4]
    return facts


#: A protocol version stays part of the name: "HTTP/2", "HTTP/3".
_NAME = re.compile(r"\b([A-Z][A-Za-z0-9$]*(?:[-.][A-Za-z0-9]+)*(?:/\d(?:\.\d)?\b)?|[A-Z]{2,}[0-9]*(?:/\d\b)?)")
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
               "Exploits", "Patch", "Second", "Life", "Spreading", "Vulnerability", "Zero", "Malicious", "Fake", "Rogue"}


#: Generic technology, role and place terms. Alone they never name an
#: organisation, product or sender ("IT provider", "AI platform", "RCE flaw").
#: A genuine name that contains one keeps it whole ("Wellington IT", "Scale AI").
GENERIC_TERMS = frozenset({
    "IT", "AI", "ML", "LLM", "LLMs", "GenAI", "API", "APIs", "VPN", "VPNs", "SaaS", "IoT", "OT", "ICS", "SCADA",
    "ERP", "CRM", "CMS", "DNS", "SSO", "MFA", "2FA", "RCE", "SQL", "SQLi", "XSS", "CSRF", "SSRF", "DDoS", "DoS",
    "PC", "PCs", "OS", "USB", "GPU", "GPUs", "CPU", "CPUs", "NAS", "HR", "PR", "CEO", "CTO", "CFO", "CISO", "IP",
    "URL", "URLs", "PDF", "SMS", "EDR", "XDR", "SIEM", "SOC", "NFT", "NFTs", "CVE", "CVEs", "CVSS", "LPE", "PoC",
    "MSP", "MSPs", "ISP", "ISPs", "OTP", "QR", "ID", "IDs", "PIN", "ATM", "ATMs", "POS", "KEV", "RAT", "RATs",
    "UK", "EU", "UN", "UAE", "USA",
})
#: Nationalities and regions describe where, not who.
DEMONYMS = frozenset({
    "Irish", "British", "English", "Scottish", "Welsh", "Chinese", "Iranian", "Ukrainian", "American", "German",
    "French", "Dutch", "Israeli", "Indian", "Italian", "Spanish", "Polish", "Japanese", "Vietnamese", "Turkish",
    "Swedish", "Danish", "Finnish", "Norwegian", "Australian", "Canadian", "Brazilian", "European", "Pakistani",
    "Belarusian", "Romanian", "Czech", "Hungarian", "Taiwanese", "Singaporean", "Mexican", "Nigerian", "Estonian",
    "Latvian", "Lithuanian", "Georgian", "Moldovan", "Slovak", "Austrian", "Belgian", "Swiss", "Portuguese",
    "Greek", "Thai", "Malaysian", "Indonesian", "Filipino", "Saudi", "Emirati", "Egyptian", "African", "Asian",
    "Korean", "Russian", "South",
})


#: Generic terms that can end a company name ("Wellington IT", "Scale AI").
_NAME_SUFFIXES = frozenset({"IT", "AI"})


def is_generic(w: str) -> bool:
    """True for a token that can never be an entity label on its own."""
    return w in GENERIC_TERMS or w in DEMONYMS or w.upper() in {t.upper() for t in GENERIC_TERMS if len(t) > 2}


def mentions(name: str, text: str) -> bool:
    """`name` occurs in `text` as a whole word (case-insensitive). Unlike a
    substring test, "IT" is not found in "with" and "Roller" not in "rollers"."""
    return bool(name) and re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text.lower()) is not None


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
    last_end = -2          # end of the last accepted name in `title`
    for m in _NAME.finditer(title):
        w = m.group(1)
        if is_generic(w):
            # "IT"/"AI" end a company name when they directly follow one and the
            # source writes that compound ("Wellington IT", "Fireworks AI").
            # Otherwise, and for every other generic term ("RCE flaw", "Turin
            # CPU"), it is a common noun and never a label.
            compound = f"{out[-1]} {w}" if out else ""
            if (w in _NAME_SUFFIXES and out and m.start() == last_end + 1 and title[last_end] == " "
                    and (not context or re.search(r"(?<!\w)" + re.escape(compound) + r"(?!\w)", context))):
                out[-1] = compound
                last_end = m.end()
            continue
        if w in _NOT_ENTITY or len(w) < 2 or w in out:
            continue
        if title_case and not _name_like(w) and context and (
                re.search(r"\b" + re.escape(w.lower()) + r"\b", context)
                or not re.search(r"\b" + re.escape(w) + r"\b", context)):
            continue
        out.append(w)
        last_end = m.end()
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
    #: The headline as published. Scenes take their subject from it first; the
    #: article body may refine a scene but never chooses its subject (not hashed).
    headline: str = ""
    alternatives: tuple[tuple[str, float], ...] = ()

    def hashable(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("text", "headline", "evidence", "reason", "alternatives", "subject", "action", "target", "environment",
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
        # Exclusions and actors read the headline only: that is where the subject is decided.
        head = f"{texts.get('main', '')} {texts.get('title', '')}"
        if spec.excludes and re.search(spec.excludes, head, re.I):
            continue
        if spec.actor and not re.search(spec.actor, head, re.I):
            continue
        if spec.head_requires and not re.search(spec.head_requires, head, re.I):
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


#: Scenes whose picture asserts that an attack or compromise took place: a
#: server knocked over, records leaking, a wiped host, money draining.
INCIDENT_SCENES = frozenset({
    "kernel_dos", "edge_wiper", "ransomware_impact", "gpu_cryptominer", "crypto_theft", "payment_skimmer",
    "compromised_sites", "session_theft", "usb_worm", "cloud_breach", "breach_notice", "espionage_backdoor",
    "dev_supply_chain", "code_signing", "third_party_script", "deepfake_call", "credential_phish",
    "malware_campaign",
})
#: Incident scenes that show a specific victim's damage. They need a reported
#: incident even when the headline is not an advisory.
IMPACT_SCENES = frozenset({
    "kernel_dos", "edge_wiper", "ransomware_impact", "crypto_theft", "payment_skimmer", "compromised_sites",
    "cloud_breach", "breach_notice", "espionage_backdoor",
})
#: Evidence statuses (pipeline.evidence) that report an attack or compromise.
ATTACK_STATUSES = frozenset({"exploited", "confirmed", "attacks_observed", "compromise"})
#: A headline that announces a vulnerability, a fix or a warning.
_ADVISORY = re.compile(
    r"\bwarn(?:s|ing|ed)?\b|advisor(?:y|ies)|\bflaws?\b|vulnerabilit|\bbugs?\b|\bpatch(?:es|ed)?\b|"
    r"\bfix(?:es|ed)?\b|security updates?|\bCVE-\d|\b(?:can|could|may|might) (?:crash|allow|let|lead|enable|"
    r"cause|expose)\b|попереджа|вразлив|виправ|оновлен|бюлетен", re.I)
#: Headline wording that reports an incident, not a possibility.
_INCIDENT = re.compile(
    r"\bexploited\b|\bexploiting\b|actively exploit|in the wild|under (?:active )?attack|\battacked\b|\bhacked\b|"
    r"\bbreach(?:ed|es)?\b|\bcompromised\b|\bstole\b|\bstolen\b|\bleak(?:ed|s)?\b|\binfect(?:ed|s|ing)\b|"
    r"\bhijack|\bwiped?\b|\bspread(?:s|ing)\b|\b(?:hackers|attackers|threat actors|criminals|cybercriminals|"
    r"gangs?|apt\w*) (?:exploit|abuse|use|target|hit|breach|hijack|deploy)|експлуатую|експлуатува|атакува|"
    r"зламал|зламан|викрал|витік|заражен|скомпрометов", re.I)


#: "could leak", "may allow attackers to steal": a possibility, not a report.
_HYPOTHETICAL = re.compile(r"\b(?:could|may|might|can|would|lets?|allows?|enables?)\b(?:\s+\w+){0,3}", re.I)


#: A claim, allegation or investigation: the headline reports what someone says,
#: not a compromise (O59: "NVIDIA investigating Gentlemen ransomware breach claims").
#: An investigation counts only when it is into the incident itself; "hackers under
#: investigation" in a story about a confirmed theft is not a claim.
_CLAIMED = re.compile(r"\bclaim(?:s|ed|ing)?\b|\balleg\w*|leak site|says it (?:hacked|breached|stole)|"
                      r"\binvestigat\w* (?:a |the |an? )?(?:possible |potential |suspected |reported )?"
                      r"(?:breach|hack|cyberattack|attack|incident|security incident|data (?:breach|leak|theft)|"
                      r"intrusion|claims?|reports?)|"
                      r"нібито|заяв\w*|розслідує|стверджу\w*", re.I)
_CONFIRMS = re.compile(r"\bconfirm(?:s|ed)\b|підтверди\w*", re.I)


#: Analysis, guidance, research or opinion: the headline explains or advises;
#: it does not report an attack. Such a story never gets a scene that shows one.
_ANALYSIS = re.compile(
    r"\bwhy\b|\bhow (?:to|attackers|hackers|threat actors|it works|they)\b|\bchecklist\b|questions to ask|"
    r"warning signs|\btips\b|what (?:you |to )?(?:need to )?know|\bexplain|\bguide\b|"
    r"researchers (?:show|demonstrate)|\bshows? how\b|\bshowed how\b|\bwho runs\b|isn.t the main|"
    r"could be your|\bwebinar\b|\bopinion\b|"
    r"чому|\bяк (?:захист|працю|виглядал|хакери|це працювал|непомітно)|що потрібно знати|показал\w* як|поради",
    re.I)


#: A closing question that explains a reported incident ("... How did it work?")
#: does not turn the incident into analysis.
_EXPLAINER_TAIL = re.compile(r"[.!?]\s*(?:як це працювал\w*|how (?:did )?it work\w*|що відомо|what we know)\??\s*$",
                             re.I)


def analysis_piece(headline: str) -> bool:
    return _ANALYSIS.search(_EXPLAINER_TAIL.sub("", headline)) is not None


def ics_advisory(item: Any) -> bool:
    """A CISA ICS advisory: its headline is the affected product's name."""
    return "/ics-advisories/" in str(getattr(item, "url", "") or "")


def claimed_only(headline: str) -> bool:
    return _CLAIMED.search(headline) is not None


def reports_incident(headline: str) -> bool:
    """The headline reports an attack or compromise as having happened (a claim
    or an investigation into one does not)."""
    if claimed_only(headline):
        return False
    return _INCIDENT.search(_HYPOTHETICAL.sub(" ", headline)) is not None


#: Package registries: a compromised package there is not a browser/editor extension.
_REGISTRY = re.compile(r"\b(?:pypi|npm|rubygems|crates\.io|nuget|maven|packagist|python package|pip package|"
                       r"npm package|packages?|пакет\w*)\b", re.I)
_EXTENSION = re.compile(r"extension|marketplace|VS Code|plugin|add-?on|розширен", re.I)


def advisory_without_incident(headline: str, status: str) -> bool:
    """O55: the headline announces a flaw, fix or warning, and neither the
    evidence status nor the headline reports an attack. Such a story is drawn
    as exposure, never as an incident ("F5 warns flaws CAN crash traffic" is
    not a crashed server)."""
    return (status not in ATTACK_STATUSES and _ADVISORY.search(headline) is not None
            and not reports_incident(headline))


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
    if ics_advisory(anchor):
        # The headline is the product: an industrial-controller scene when the
        # sources support one, else the advisory scene, with that name.
        if not (ranked and ranked[0][1].id in ("ics_controller", "refrigeration_controller")):
            ranked = [(20.0, SPECS["vuln_advisory"], ["title: CISA ICS advisory for the named product"])]
    elif claimed_only(title) and not _CONFIRMS.search(f"{title} {excerpt}"):
        # O59: a claim is not an incident (whatever the evidence heuristics read into
        # "the group says it stole 2 TB"); only a confirmation in the sources lifts it. Only the breach scene's sealed "ALLEGED"
        # envelope may draw it; no locked systems, leaking records or wiped hosts.
        # The breach scene stays only for a headline about an alleged breach itself
        # (it draws the victim's sealed envelope stamped ALLEGED); a gang's leak-site
        # listing would put the gang's name on the envelope, so V3 draws that.
        keep = "breach_notice" if re.search(r"\bbreach\b", title, re.I) and \
            re.search(r"\bclaim(?:s|ed)?\b|\balleg\w*", title, re.I) else ""
        ranked = [r for r in ranked if r[1].id not in IMPACT_SCENES or r[1].id == keep]
    elif _REGISTRY.search(title) and not _EXTENSION.search(title):
        # A package-registry compromise (PyPI, npm ...) has no faithful V4.1 scene:
        # the extension picture would invent a marketplace and a stolen key. V3 draws it.
        ranked = []
    elif advisory_without_incident(title, status):
        # O55: an advisory never wins an incident scene; the next-ranked scene decides.
        ranked = [r for r in ranked if r[1].id not in INCIDENT_SCENES]
    elif status not in ATTACK_STATUSES and not reports_incident(title):
        # A scene that shows a victim's damage (locked systems, leaking records,
        # a wiped host) needs a reported incident: not an explainer, an opinion
        # piece or a profile of a ransomware group.
        ranked = [r for r in ranked if r[1].id not in IMPACT_SCENES]

    if analysis_piece(title):
        # Analysis, guidance or research: nothing that shows an attack happening.
        ranked = [r for r in ranked if r[1].id not in INCIDENT_SCENES and r[1].id != "patch_to_exploit"]
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
    # Figures come from the sources only (headline, then excerpt). Our own summary
    # may name a figure of another subject in the same story (Oracle's 11 Java SE
    # fixes are not CVE-2026-114938), so it never adds one.
    facts = extract_facts(title, excerpt, "")
    sources = " ".join(f"{getattr(m, 'title', '')} {getattr(m, 'raw_content', '') or ''}"
                       for m in (getattr(story, "members", None) or [anchor])).upper()
    cves = [c for c in extract_facts(title, excerpt, post).get("cves", []) if c in sources]
    if cves:
        facts["cves"] = cves[:4]
    # Entities are drawn in the image, so they come from the headline and the
    # source text only: rewording our own post must not change the picture.
    names = extract_entities(title, excerpt)
    # Our published headline may name what the source's own headline does not
    # ("BBC, CNN and Zoom among 178 sites..."): such names count only when the
    # source text itself contains them, so rewording a post cannot add one.
    post_title = post.split(". ")[0]
    for e in extract_entities(post_title, excerpt):
        if e not in names and re.search(r"(?<!\w)" + re.escape(e) + r"(?!\w)", excerpt):
            names.append(e)
    if ics_advisory(anchor) and title.strip():
        names = [title.strip()]                   # the advisory's subject is exactly the product it names
    entities = tuple(names[:6])
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
        text=" ".join(texts.values()).lower(), headline=title,
        alternatives=tuple((s.id, round(sc, 1)) for sc, s, _ in ranked[1:4]))


def alt_text(brief: EditorialBrief) -> dict[str, str]:
    spec = SPECS.get(brief.scene, FALLBACK)
    en, ua = spec.alt_en, spec.alt_ua
    # A scene that draws story-dependent variants describes the one it drew.
    try:
        import importlib
        mod = importlib.import_module(f"{__package__}.scenes.{brief.scene}")
        hook = getattr(mod, "alt_for", None)
        got = hook(brief) if hook else None
    except ImportError:
        got = None
    if got:
        en, ua = got
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
