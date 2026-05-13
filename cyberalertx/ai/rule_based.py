"""Deterministic, dependency-free ThreatPost generator.

In MVP mode this is the **primary** path — the LLM provider is opt-in. The
goal here is output that reads like a careful human draft: concise, scannable,
mobile-friendly, never robotic.

How variety is achieved without randomness:
  * `why_it_matters` is keyed on (category, urgency_bucket) — a 13×3 grid of
    pre-written one-liners. Same input ⇒ same output (testable); different
    items ⇒ different copy.
  * `what_to_do` / `what_not_to_do` defer to the matched `PromptTemplate.rule_based`
    overrides when present, falling back to per-category defaults. Adding
    audience-aware copy is one dict edit, no code change.
  * `quick_facts` are computed from the actual item state (active exploitation
    detected? patch mentioned? credible source?) so they describe THIS item.

Localization:
  Everything that ends up in the rendered card is provided in both `en` and
  `uk`. Pass `language=` to `generate()` to pick a locale. The rule-based
  generator can localize metadata (why_it_matters, what_to_do, quick_facts,
  audience labels) but cannot translate the article's title or summary
  body — those stay in the source language. The API layer caches per
  (fingerprint, locale).

Quality vs LLM: this is the floor, not the ceiling. The LLM path remains
the upgrade — see `cyberalertx/ai/generator.py` for the wiring.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

from ..models import NewsItem
from .models import ThreatPost
from .templates import TemplateRegistry, default_template_registry

# Short, descriptive audience labels (kept in sync with audience.AUDIENCES keys).
_HUMAN_AUDIENCE_EN: Mapping[str, str] = {
    "normal_users": "Everyday users",
    "developers": "Developers",
    "sysadmins": "IT / sysadmins",
    "enterprise": "Enterprise IT teams",
    "mobile_users": "Mobile users",
    "crypto_users": "Crypto users",
}

_HUMAN_AUDIENCE_UK: Mapping[str, str] = {
    "normal_users": "Звичайні користувачі",
    "developers": "Розробники",
    "sysadmins": "ІТ-адміністратори",
    "enterprise": "Корпоративні ІТ-команди",
    "mobile_users": "Користувачі мобільних пристроїв",
    "crypto_users": "Криптокористувачі",
}

# Why-it-matters copy keyed by (category, urgency_bucket).
# Urgency buckets: "urgent" / "soon" / "fyi".
#
# Each value is a list of 1-3 hand-written variants. The renderer picks
# one deterministically from `item.fingerprint`, so:
#   * the same item always gets the same line (testable, cacheable)
#   * two items in the same bucket usually get different lines
#     (no "10 phishing alerts all say the same thing" fatigue)
_WHY_IT_MATTERS_EN: Mapping[tuple[str, str], Sequence[str]] = {
    ("phishing", "urgent"): [
        "Once attackers have your password, they can read every email — including the 2FA codes that get sent there.",
        "Live phishing wave. A few seconds spent checking the URL is the whole defense.",
        "Real victims today. The lure looks legitimate by design — verify the sender before you sign in anywhere.",
    ],
    ("phishing", "soon"): [
        "Phishing waves peak fast. A minute spent recognizing the bait pays for itself.",
        "Worth a quick read so you can spot the lure when it lands.",
        "Knowing the playbook is most of the defense.",
    ],
    ("phishing", "fyi"): [
        "Useful phishing pattern to recognize when something feels off in your inbox.",
        "A phishing technique you'll likely see referenced again — worth knowing the shape of it.",
    ],
    ("ransomware", "urgent"): [
        "If this gang reaches you, you lose access to your files. Backups and patching are the defense.",
        "Active extortion campaign. Confirm your backups before someone tests them for you.",
        "Real incidents in progress. Now is the moment to verify your recovery plan works.",
    ],
    ("ransomware", "soon"): [
        "Worth checking your backup and patch status now, while there's still time.",
        "If your environment looks like the victim profile, take the mitigations seriously.",
    ],
    ("ransomware", "fyi"): [
        "Context on a ransomware crew you'll probably hear about again.",
        "Worth knowing this group's tradecraft so you spot it early if it lands nearby.",
    ],
    ("vulnerability", "urgent"): [
        "Attackers are chasing the patch. The window between 'fix shipped' and 'fix exploited' is shrinking.",
        "Patched flaw, but exploitation has started. Roll out the update before you read about it again.",
    ],
    ("vulnerability", "soon"): [
        "Fix is available. Applying it is the cheapest action you can take.",
        "Patch first, debrief later — the fix exists, and someone will write the exploit shortly.",
        "Quick wins: install the update, audit anywhere the affected component runs.",
    ],
    ("vulnerability", "fyi"): [
        "Heads-up on a flaw to track if you run the affected software.",
        "Worth bookmarking so you can act if it lights up later.",
    ],
    ("exploit", "urgent"): [
        "Working exploit, in the wild, today. Patch or mitigate now.",
        "Live attack code. The grace period is over — apply the vendor fix.",
        "Active exploitation observed. This is the part where waiting starts costing.",
    ],
    ("exploit", "soon"): [
        "Exploit code is circulating. Apply the vendor fix before it becomes ubiquitous.",
        "Public exploit, vendor patch available — close the gap quickly.",
    ],
    ("exploit", "fyi"): [
        "Technique disclosure — worth knowing the shape even if it's not a fire drill yet.",
    ],
    ("zero-day", "urgent"): [
        "No patch yet, and attackers are already using it. Apply the vendor's workaround if one exists.",
        "Zero-day, live exploitation. Mitigations now, full patch when it ships.",
    ],
    ("zero-day", "soon"): [
        "A zero-day is more dangerous than the usual CVE. Keep an eye on the vendor advisory.",
        "Worth tracking — no fix yet, and the bug is out there.",
    ],
    ("zero-day", "fyi"): [
        "Zero-day disclosure to track — relevant if you run the affected stack.",
    ],
    ("breach", "urgent"): [
        "If your email was here, attackers can request password resets across every service tied to it.",
        "Treat the leaked password as burned and rotate it anywhere you've reused it — credential stuffing is automated.",
    ],
    ("breach", "soon"): [
        "Worth changing the password here and anywhere you reused it.",
        "Standard breach hygiene: rotate the credential, check breach trackers.",
    ],
    ("breach", "fyi"): [
        "Breach disclosure — worth noting in case you're a customer of the affected service.",
    ],
    ("data leak", "urgent"): [
        "Records are publicly out there. Phishers will use them this week.",
        "The data is out. Expect targeted lures referencing details from the leak.",
    ],
    ("data leak", "soon"): [
        "Good time to check breach-tracking sites for your accounts.",
    ],
    ("data leak", "fyi"): [
        "Leaked dataset disclosure — useful to know what's circulating.",
    ],
    ("malware", "urgent"): [
        "Real infections, real victims. Worth checking your defenses.",
        "Active campaign in the wild. Defenders should hunt for the indicators.",
    ],
    ("malware", "soon"): [
        "Family-level intel; useful for sharpening detections.",
        "Background you'll want when one of these shows up in your logs.",
    ],
    ("malware", "fyi"): [
        "Malware-family research — worth keeping context on as it evolves.",
    ],
    ("spyware", "urgent"): [
        "Targeted surveillance tooling. Review app permissions and update.",
        "Live spyware activity. If you might be in the targeting profile, act today.",
    ],
    ("spyware", "soon"): [
        "If you might be in the targeting profile, take the article's mitigations seriously.",
    ],
    ("spyware", "fyi"): [
        "Spyware ecosystem update — relevant to anyone in a targeting profile.",
    ],
    ("scam", "urgent"): [
        "Active fraud playbook. Slow down before sending money or codes.",
        "Live scam in progress. Time pressure is the lure — don't bite.",
    ],
    ("scam", "soon"): [
        "Pattern worth being able to spot — and worth warning family about.",
        "Tactic to recognize before it lands in your DMs.",
    ],
    ("scam", "fyi"): [
        "Scam pattern worth being able to name when you see it.",
    ],
    ("botnet", "urgent"): [
        "Live recruitment campaign. Patch consumer routers and IoT devices now.",
    ],
    ("botnet", "soon"): [
        "If you own consumer routers or IoT, this is what silently recruits them.",
        "Worth a glance at any internet-connected device with default settings.",
    ],
    ("botnet", "fyi"): [
        "Botnet research — useful to track if you're responsible for any edge devices.",
    ],
    ("social engineering", "urgent"): [
        "Live pretexting campaign. Verify any urgent request out of band.",
        "Active social engineering. Slow the request down; call back through a known channel.",
    ],
    ("social engineering", "soon"): [
        "Specific con; useful to recognize when your colleague forwards it.",
    ],
    ("social engineering", "fyi"): [
        "Social-engineering tactic to file away for the next 'urgent' Slack message.",
    ],
    # Catch-alls used when no category-specific line is defined.
    ("default", "urgent"): [
        "Active situation. Attackers are exploiting this before patches are widely deployed.",
        "Worth acting on now — the window for safe response is short.",
    ],
    ("default", "soon"): [
        "A fix or guidance has been published. Applying it soon reduces your exposure.",
        "Not a fire drill, but worth handling this week.",
    ],
    ("default", "fyi"): [
        "Useful context for staying current on threats in your environment.",
        "Worth filing away so the pattern is recognizable next time it appears.",
    ],
}

_WHY_IT_MATTERS_UK: Mapping[tuple[str, str], Sequence[str]] = {
    ("phishing", "urgent"): [
        "Активна кампанія — якщо ваша скринька в списку цілей, лист уже там.",
        "Жива хвиля фішингу. Секунда сумніву рятує акаунт.",
        "Сьогодні є реальні жертви. Перевірте відправника, перш ніж десь логінитись.",
    ],
    ("phishing", "soon"): [
        "Фішингові хвилі швидко набирають обертів. Хвилина на розпізнавання приманки окупається.",
        "Варто швидко прочитати, щоб упізнати наживку, коли вона прилетить.",
        "Знання сценарію — це більша частина захисту.",
    ],
    ("phishing", "fyi"): [
        "Корисний фішинговий патерн — допоможе зрозуміти, коли лист «пахне» обманом.",
        "Техніка, яку ви, ймовірно, ще побачите — варто розуміти її форму.",
    ],
    ("ransomware", "urgent"): [
        "Якщо ця група вас зачепить — ви втрачаєте доступ до файлів. Резервні копії та патчі — ваш захист.",
        "Активна кампанія здирства. Перевірте свої бекапи, поки це не зробив хтось інший.",
        "Реальні інциденти прямо зараз. Саме час перевірити, що план відновлення працює.",
    ],
    ("ransomware", "soon"): [
        "Варто зараз перевірити статус резервних копій і патчів, поки є час.",
        "Якщо ваше середовище схоже на профіль жертви — поставтесь до мітигацій серйозно.",
    ],
    ("ransomware", "fyi"): [
        "Контекст про угруповання, про яке ви ще, ймовірно, почуєте.",
        "Варто знати тактику цієї групи, щоб розпізнати її швидко поряд із собою.",
    ],
    ("vulnerability", "urgent"): [
        "Атакувальники женуться за патчем. Вікно між «фікс випущено» та «фікс експлуатовано» стискається.",
        "Уразливість виправлено, але експлуатація вже почалась. Розгортайте оновлення зараз.",
    ],
    ("vulnerability", "soon"): [
        "Фікс доступний. Встановити його — найдешевша дія, яку можна зробити.",
        "Спочатку патч, потім розбір — фікс існує, експлойт напишуть найближчим часом.",
        "Швидкі перемоги: встановіть оновлення, перевірте, де працює уражений компонент.",
    ],
    ("vulnerability", "fyi"): [
        "Звертайте увагу на цю ваду, якщо використовуєте уражене ПЗ.",
        "Варто зберегти, щоб діяти, якщо вона «спалахне» пізніше.",
    ],
    ("exploit", "urgent"): [
        "Експлойт вже використовують у реальних атаках. Кожен непропатчений вузол — потенційна точка входу.",
        "Жива атака. Період відстрочки закінчився — встановіть фікс від вендора зараз.",
        "Активна експлуатація. Чим довше ви чекаєте — тим більше шансів, що зайдуть.",
    ],
    ("exploit", "soon"): [
        "Код експлойта циркулює. Застосуйте фікс, поки він не став повсюдним.",
        "Публічний експлойт, патч є — закрийте розрив якнайшвидше.",
    ],
    ("exploit", "fyi"): [
        "Розкриття техніки — варто знати її форму, навіть якщо це ще не пожежа.",
    ],
    ("zero-day", "urgent"): [
        "Патча ще немає, а атакувальники вже використовують. Застосуйте обхідне рішення від вендора, якщо воно є.",
        "Нульовий день, жива експлуатація. Мітигації зараз, повний патч — коли вийде.",
    ],
    ("zero-day", "soon"): [
        "Нульовий день небезпечніший за звичайний CVE. Слідкуйте за рекомендаціями вендора.",
        "Варто моніторити — фікса ще нема, а баг вже у природі.",
    ],
    ("zero-day", "fyi"): [
        "Розкриття zero-day — актуально, якщо ви використовуєте уражений стек.",
    ],
    ("breach", "urgent"): [
        "Якщо ваші дані тут — пароль вважайте скомпрометованим, а email — точкою входу до інших ваших акаунтів.",
        "Витік вже використовують для фішингу. Змініть паролі і чекайте на цільові листи з деталями зі зливу.",
    ],
    ("breach", "soon"): [
        "Варто змінити пароль на цьому сервісі і всюди, де ви його повторювали.",
        "Стандартна гігієна після витоку: змініть пароль, перевірте сервіси відстеження витоків.",
    ],
    ("breach", "fyi"): [
        "Розкриття витоку — варто знати, якщо ви клієнт ураженого сервісу.",
    ],
    ("data leak", "urgent"): [
        "Записи вже публічно доступні. Фішери використають їх цього ж тижня.",
        "Дані опубліковані. Чекайте таргетованих листів із посиланнями на деталі витоку.",
    ],
    ("data leak", "soon"): [
        "Гарний момент перевірити свої акаунти на сайтах відстеження витоків.",
    ],
    ("data leak", "fyi"): [
        "Опубліковано набір зливних даних — корисно знати, що циркулює.",
    ],
    ("malware", "urgent"): [
        "Реальні зараження, реальні жертви. Варто перевірити захист.",
        "Активна кампанія у дикій природі. Захисникам — полювати на індикатори.",
    ],
    ("malware", "soon"): [
        "Інформація рівня сімейства — корисна для уточнення детектування.",
        "Контекст, який знадобиться, коли щось із цього з'явиться у ваших логах.",
    ],
    ("malware", "fyi"): [
        "Дослідження сімейства шкідливого ПЗ — варто тримати контекст, бо воно еволюціонує.",
    ],
    ("spyware", "urgent"): [
        "Інструментарій таргетованого стеження. Перевірте дозволи додатків і оновіться.",
        "Жива активність шпигунського ПЗ. Якщо ви можете бути в профілі цілей — дійте сьогодні.",
    ],
    ("spyware", "soon"): [
        "Якщо ви можете бути ціллю — поставтесь до мітигацій у статті серйозно.",
    ],
    ("spyware", "fyi"): [
        "Оновлення в екосистемі шпигунського ПЗ — релевантно для тих, хто може бути ціллю.",
    ],
    ("scam", "urgent"): [
        "Активний шахрайський сценарій. Не поспішайте, перш ніж надіслати гроші чи коди.",
        "Шахрайство в дії. Тиск часу — це і є приманка, не ведіться.",
    ],
    ("scam", "soon"): [
        "Патерн, який варто вміти впізнавати — і попередити рідних.",
        "Тактика, яку треба розпізнати до того, як вона прилетить у ваші повідомлення.",
    ],
    ("scam", "fyi"): [
        "Шахрайський патерн, який варто вміти назвати, коли побачите його.",
    ],
    ("botnet", "urgent"): [
        "Жива кампанія рекрутингу. Патчіть домашні роутери та IoT-пристрої зараз.",
    ],
    ("botnet", "soon"): [
        "Якщо у вас домашні роутери чи IoT — саме це їх безшумно вербує.",
        "Варто перевірити будь-який інтернет-пристрій із стандартним налаштуванням.",
    ],
    ("botnet", "fyi"): [
        "Дослідження ботнету — корисно, якщо ви відповідаєте за edge-пристрої.",
    ],
    ("social engineering", "urgent"): [
        "Активна кампанія з підробкою особи. Будь-який терміновий запит підтверджуйте через інший канал.",
        "Соціальна інженерія у дії. Не поспішайте — передзвоніть на офіційний номер, а не на той, що в повідомленні.",
    ],
    ("social engineering", "soon"): [
        "Конкретний прийом — корисно впізнати, коли колега перешле його далі.",
    ],
    ("social engineering", "fyi"): [
        "Прийом соцінженерії — запам'ятайте на випадок наступного «термінового» повідомлення в Slack.",
    ],
    ("default", "urgent"): [
        "Активна загроза. Зловмисники експлуатують її швидше, ніж захисники встигають патчити.",
        "Реальний інцидент прямо зараз — вікно для спокійної реакції закривається.",
    ],
    ("default", "soon"): [
        "Опубліковано фікс або інструкції. Застосуйте найближчими днями — це зменшить ваш ризик.",
        "Не пожежа, але якщо відкласти — стане проблемою цього місяця.",
    ],
    ("default", "fyi"): [
        "Корисний контекст, щоб вчасно впізнати схожу загрозу у власному середовищі.",
        "Цей патерн ще побачите — варто запам'ятати, як він виглядає.",
    ],
}


# Per-category action pools.
#
# Each list has 5-7 candidate actions. The renderer picks 3 of them
# deterministically from the item's fingerprint, so:
#   * Two items in the same category get DIFFERENT subsets — no two
#     phishing posts look identical.
#   * The same item always renders the same actions (testable, cacheable).
#   * Adding/removing entries is a one-line edit; the picker handles it.
#
# Authoring rules:
#   * Each line starts with an imperative verb ("Check", "Enable", "Review").
#   * Concrete commands beat vague advice ("Open chrome://settings/passwords"
#     beats "Stay safe online"). Reference actual UIs / file paths /
#     command names where they're stable.
#   * Avoid corporate jargon ("posture", "robust"). Address the user as "you".
#   * No exclamation marks. No ALL-CAPS.
_DEFAULT_ACTIONS_EN: Mapping[str, list[str]] = {
    "phishing": [
        "Open the service directly in your browser instead of clicking the link",
        "Hover over the link to see the real domain before clicking",
        "Use a password manager — it won't autofill on lookalike domains",
        "Enable two-factor authentication, ideally with an authenticator app",
        "Check the sender's full email address, not just the display name",
        "If you already clicked, reset the password and revoke active sessions",
        "Report the message to your IT team or the service's abuse channel",
    ],
    "ransomware": [
        "Confirm you have offline backups of important files",
        "Test the restore path — a backup you can't restore from doesn't count",
        "Apply security updates as soon as your vendor releases them",
        "Disable Remote Desktop (RDP) if you don't actively need it",
        "Segment shared drives so a single compromised machine can't reach everything",
        "Make sure endpoint protection is on and actually reporting in",
        "Review who has Domain Admin / privileged access — keep the list short",
    ],
    "vulnerability": [
        "Update the affected software as soon as a patch is available",
        "Search your inventory for the affected version — you can't patch what you don't know you run",
        "Subscribe to the vendor's security advisories so the next one isn't a surprise",
        "Check whether the bug requires authentication; unauthenticated flaws move fastest",
        "If a patch isn't ready yet, apply the workaround the advisory recommends",
    ],
    "exploit": [
        "Apply the vendor patch immediately if one is available",
        "Pull the indicators of compromise (IOCs) from the article and search your logs",
        "If you can't patch right away, block exploitation paths at the network edge",
        "Check the affected component is even reachable from the internet — that's the real risk surface",
        "Watch your EDR for the post-exploit activity the article describes",
    ],
    "zero-day": [
        "Apply the emergency mitigations from the vendor advisory verbatim",
        "Watch for the official patch and roll it out the day it ships",
        "Limit who can reach the affected component while you're exposed",
        "Hunt for the post-exploitation indicators the advisory lists",
        "Treat any access from the affected system as suspect until you've patched",
    ],
    "malware": [
        "Run a full scan with a reputable anti-malware product on suspicious systems",
        "Avoid installing software from unknown sources or 'cracked' downloads",
        "Check for unexpected scheduled tasks, browser extensions, or startup entries",
        "Rotate any passwords typed on a machine you suspect was infected",
        "If you handle anything sensitive, reimage rather than 'clean' an infected machine",
    ],
    "spyware": [
        "Review which apps have microphone, camera, and location access",
        "Update your phone and apps to the latest version",
        "Sign out of accounts you don't actively use",
        "If you might be a targeting candidate (journalist, activist, exec), use lockdown / advanced protection modes",
        "Audit Bluetooth and Wi-Fi auto-connect lists",
    ],
    "breach": [
        "Change the password for the affected service",
        "If you reused that password anywhere else, change it there too",
        "Turn on two-factor authentication if you haven't already",
        "Watch for phishing emails referencing this breach for the next few weeks",
        "Check whether the breach included security questions — change those too",
        "Review recent account activity for unfamiliar logins or transfers",
    ],
    "data leak": [
        "Change the password for the affected service immediately",
        "Check haveibeenpwned.com for any of your other accounts",
        "Watch for fraud and phishing attempts referencing the leaked details",
        "If the leak includes payment data, set up alerts with your bank or card issuer",
        "Rotate any API keys or tokens that may have been in the dataset",
    ],
    "scam": [
        "Slow down — scammers rely on time pressure to short-circuit your thinking",
        "Verify any payment request through a second channel you already trust",
        "If 'support' contacted you first, hang up and call the real number from the company's website",
        "Don't share screen control with anyone who reached out to you unsolicited",
        "Pause before sending crypto — recovery options are essentially zero",
    ],
    "botnet": [
        "Patch consumer routers and IoT devices, or replace ones the vendor stopped updating",
        "Change default passwords on any internet-connected device",
        "Disable UPnP and remote management on your home router",
        "Put IoT devices on a separate network from your main devices",
        "Check your router's logs for outbound connections to unknown hosts",
    ],
    "social engineering": [
        "Pause before responding to urgent or unusual requests",
        "Verify the requester through a known channel — not by replying to the same message",
        "If a request bypasses normal process ('keep this confidential'), that's the red flag",
        "Confirm wire-transfer details on a recorded line before sending money",
        "Train your team to flag — not silently resolve — anything that feels off",
    ],
}

# Ukrainian action pool. Authoring rules same as English plus:
#   * Use natural Ukrainian — not literal translation. "Slow down" maps to
#     "Не поспішайте", NOT "Сповільніться". "Verify through another channel"
#     maps to "Перевірте іншим каналом", not "Підтвердіть запит через
#     другий канал".
#   * Address the reader as "ви" (formal). Imperative form for actions.
#   * Avoid Russian-grammar artifacts (no "путем", "являться", "только что").
_DEFAULT_ACTIONS_UK: Mapping[str, list[str]] = {
    "phishing": [
        "Відкрийте сервіс напряму в браузері — не клацайте посилання з листа",
        "Подивіться, який реальний домен криється за посиланням, перш ніж натиснути",
        "Користуйтесь менеджером паролів — він не автозаповнить дані на підробленому домені",
        "Увімкніть двофакторну автентифікацію, краще через додаток-автентифікатор",
        "Подивіться на повну адресу відправника, а не лише на ім'я, яке показано",
        "Якщо вже ввели пароль на фейковій сторінці — змініть його і завершіть усі активні сесії",
        "Повідомте про лист ІТ-команді або службі підтримки сервісу",
    ],
    "ransomware": [
        "Переконайтесь, що у вас є офлайн-копії важливих файлів",
        "Перевірте, що з резервної копії дійсно можна відновитись — недосвідчений бекап не рятує",
        "Встановлюйте оновлення безпеки одразу після релізу від вендора",
        "Вимкніть Remote Desktop (RDP), якщо він вам не потрібен",
        "Сегментуйте мережеві диски — одна заражена машина не повинна діставати до всього",
        "Переконайтесь, що захист робочих станцій (EDR/антивірус) увімкнено і він звітує",
        "Перегляньте список адміністраторів домену — він має бути коротким",
    ],
    "vulnerability": [
        "Оновіть уражене ПЗ, щойно вийде патч",
        "Пройдіться інвентарем — патчити те, що ви не знаєте, що використовуєте, неможливо",
        "Підпишіться на security-розсилку вашого вендора",
        "Подивіться, чи вимагає вразливість автентифікації — без неї ризик зростає",
        "Якщо патча ще немає, застосуйте обхідне рішення з рекомендацій вендора",
    ],
    "exploit": [
        "Негайно встановіть патч від вендора, якщо він уже є",
        "Витягніть із статті індикатори компрометації (IOC) і пошукайте їх у логах",
        "Якщо патчити прямо зараз не можна — заблокуйте шлях експлуатації на периметрі мережі",
        "Перевірте, чи уражений компонент взагалі досяжний з Інтернету — це справжня поверхня атаки",
        "Слідкуйте у вашому EDR за пост-експлуатаційною активністю, описаною у статті",
    ],
    "zero-day": [
        "Застосуйте екстрені мітигації з рекомендацій вендора точно як написано",
        "Стежте за офіційним патчем і розгорніть у день виходу",
        "Обмежте доступ до ураженого компонента, поки ви відкриті",
        "Шукайте у логах індикатори пост-експлуатації, перелічені у рекомендаціях",
        "До встановлення патча ставтесь до будь-яких дій із ураженої системи як до підозрілих",
    ],
    "malware": [
        "Запустіть повне сканування підозрілих машин надійним антивірусом",
        "Не встановлюйте ПЗ з невідомих джерел і не качайте «зламані» версії",
        "Перевірте автозавантаження, заплановані задачі та розширення браузера на дивні записи",
        "Змініть паролі, які ви вводили на машині, що могла бути зараженою",
        "Якщо машина обробляла щось чутливе — краще переустановити систему, ніж «чистити»",
    ],
    "spyware": [
        "Перевірте, які додатки мають доступ до мікрофона, камери та геолокації",
        "Оновіть телефон і додатки до останньої версії",
        "Вийдіть з акаунтів, якими активно не користуєтесь",
        "Якщо ви можете бути ціллю (журналіст, активіст, керівник) — увімкніть режим Lockdown або Advanced Protection",
        "Перегляньте списки автоматичного підключення Bluetooth і Wi-Fi",
    ],
    "breach": [
        "Змініть пароль на ураженому сервісі",
        "Якщо цей пароль повторюється деінде — змініть і там",
        "Увімкніть двофакторну автентифікацію, якщо ще не увімкнули",
        "Слідкуйте за фішинговими листами, що згадують цей витік, найближчі тижні",
        "Перевірте, чи витік містив контрольні питання — їх теж треба змінити",
        "Подивіться нещодавню активність акаунта — невідомі входи, перекази, нові пристрої",
    ],
    "data leak": [
        "Негайно змініть пароль на ураженому сервісі",
        "Перевірте інші свої акаунти через haveibeenpwned.com",
        "Чекайте на цільові фішингові листи з посиланнями на деталі з витоку",
        "Якщо у витоку були платіжні дані — налаштуйте сповіщення в банку чи емітента картки",
        "Замініть будь-які API-ключі чи токени, які могли бути у наборі даних",
    ],
    "scam": [
        "Не поспішайте — шахраї грають саме на тиску часу",
        "Перевірте будь-який запит на платіж іншим каналом, якому ви довіряєте",
        "Якщо «служба підтримки» зателефонувала першою — покладіть слухавку і передзвоніть на офіційний номер сайту",
        "Не давайте керування екраном людині, яка зателефонувала вам без вашого запиту",
        "Подумайте двічі перш ніж надсилати крипту — повернути її практично неможливо",
    ],
    "botnet": [
        "Оновіть домашні роутери та IoT-пристрої або замініть ті, які вендор більше не підтримує",
        "Змініть стандартні паролі на всіх інтернет-пристроях",
        "Вимкніть UPnP і віддалене керування на домашньому роутері",
        "Винесіть IoT-пристрої в окрему мережу від основних",
        "Перевірте логи роутера на вихідні з'єднання з підозрілими хостами",
    ],
    "social engineering": [
        "Зупиніться, перш ніж відповідати на термінові чи незвичні запити",
        "Перевірте людину через відомий вам канал — не відповідаючи на той самий лист чи повідомлення",
        "Якщо просять оминути звичний процес («між нами», «нікому не кажи») — це сигнал тривоги",
        "Підтверджуйте реквізити переказу телефоном, перш ніж відправляти гроші",
        "Привчіть команду повідомляти про підозрілі запити, а не «розв'язувати» їх мовчки",
    ],
}

# "Don't" pools — 3-5 anti-patterns per category. Same deterministic picker
# as actions; picks up to 2 by default so the don't list stays short.
_DEFAULT_AVOIDS_EN: Mapping[str, list[str]] = {
    "phishing": [
        "Don't enter passwords on links you reached from email or SMS",
        "Don't ignore browser security warnings, even on familiar-looking sites",
        "Don't approve a 2FA prompt you didn't trigger — that's the attacker testing",
        "Don't trust a sender just because their display name is correct",
    ],
    "ransomware": [
        "Don't pay the ransom — it funds the next attack and rarely restores everything",
        "Don't connect a backup drive to a system you suspect is infected",
        "Don't treat 'we backed up' as the same as 'we tested restore' — they aren't",
    ],
    "scam": [
        "Don't share verification codes by phone or chat — no real service asks for them",
        "Don't transfer money to people you've only spoken to online",
        "Don't act on time pressure — anyone legitimate will let you verify first",
        "Don't switch the conversation to WhatsApp / Telegram on a stranger's request",
    ],
    "breach": [
        "Don't reuse the leaked password on other sites — credential stuffing will find them",
        "Don't dismiss the breach notification because 'they only got hashes' — hashes get cracked",
    ],
    "vulnerability": [
        "Don't skip the patch because the bug 'sounds theoretical'",
        "Don't delay the update just because the maintenance window is inconvenient",
    ],
    "exploit": [
        "Don't wait for a centralized exploit hunt to start — apply the patch on your own systems first",
    ],
    "malware": [
        "Don't run executables from email attachments, even if the sender looks familiar",
        "Don't disable Defender / your endpoint product because an installer asked you to",
    ],
    "spyware": [
        "Don't grant accessibility or device-admin permissions to apps that don't obviously need them",
        "Don't sideload apps from links shared by strangers, even if they look like a known brand",
    ],
    "data leak": [
        "Don't reuse the leaked password anywhere else, ever",
        "Don't engage with 'recovery services' that contact you about the leak — they're scammers",
    ],
    "social engineering": [
        "Don't bypass a security policy because someone framed it as urgent",
        "Don't take requests through a single channel — verify out-of-band",
    ],
}

_DEFAULT_AVOIDS_UK: Mapping[str, list[str]] = {
    "phishing": [
        "Не вводьте паролі за посиланнями з email чи SMS",
        "Не ігноруйте попередження браузера, навіть на знайомих сайтах",
        "Не підтверджуйте 2FA-запит, який ви не ініціювали — це атакувальник перевіряє",
        "Не довіряйте відправнику лише через те, що ім'я в заголовку виглядає знайомим",
    ],
    "ransomware": [
        "Не платіть викуп — це фінансує наступну атаку і рідко відновлює все",
        "Не підключайте резервний диск до системи, яку підозрюєте у зараженні",
        "«Ми робимо бекапи» — це не те саме, що «ми тестуємо відновлення»",
    ],
    "scam": [
        "Не передавайте коди підтвердження телефоном чи в чаті — реальні сервіси ніколи не питають",
        "Не переказуйте гроші людям, з якими спілкувались лише онлайн",
        "Не діяти під тиском часу — справжня сторона завжди дасть час перевірити",
        "Не переходьте у WhatsApp / Telegram на прохання незнайомця",
    ],
    "breach": [
        "Не використовуйте «зливний» пароль ніде більше — credential stuffing його знайде",
        "Не списуйте сповіщення про витік на «там лише хеші» — хеші підбирають",
    ],
    "vulnerability": [
        "Не відкладайте патч лише тому, що ваду названо «теоретичною»",
        "Не зволікайте з оновленням через незручне вікно обслуговування",
    ],
    "exploit": [
        "Не чекайте, поки централізоване полювання на загрози почнеться — застосуйте патч у себе першим",
    ],
    "malware": [
        "Не запускайте виконувані файли з вкладень email, навіть від знайомого відправника",
        "Не вимикайте Defender чи інший антивірус на прохання інсталятора",
    ],
    "spyware": [
        "Не давайте дозволи Accessibility чи Device Admin додаткам, яким вони очевидно не потрібні",
        "Не встановлюйте APK з посилань від незнайомців, навіть якщо це «нова версія» відомого додатка",
    ],
    "data leak": [
        "Не використовуйте «зливний» пароль більше ніде. Ніколи",
        "Не довіряйте «службам відновлення», що вам пишуть після витоку — це шахраї",
    ],
    "social engineering": [
        "Не обходьте правила безпеки, лише тому що хтось назвав запит «терміновим»",
        "Не приймайте запити лише через один канал — перевіряйте out-of-band",
    ],
}

# Short labels used in quick_facts in place of "Type: <category>".
# Reads as a noun phrase, which mobile users scan faster than a key:value pair.
_CATEGORY_FACT_LABEL_EN: Mapping[str, str] = {
    "phishing": "Phishing campaign",
    "ransomware": "Ransomware",
    "vulnerability": "Vulnerability",
    "exploit": "Active exploit",
    "zero-day": "Zero-day",
    "breach": "Data breach",
    "data leak": "Data leak",
    "malware": "Malware",
    "spyware": "Spyware",
    "scam": "Scam",
    "botnet": "Botnet",
    "social engineering": "Social engineering",
}

_CATEGORY_FACT_LABEL_UK: Mapping[str, str] = {
    "phishing": "Фішингова кампанія",
    "ransomware": "Програма-вимагач",
    "vulnerability": "Вразливість",
    "exploit": "Активна атака",
    "zero-day": "Нульовий день",
    "breach": "Витік даних",
    "data leak": "Злив даних",
    "malware": "Шкідливе ПЗ",
    "spyware": "Шпигунське ПЗ",
    "scam": "Шахрайство",
    "botnet": "Ботнет",
    "social engineering": "Соціальна інженерія",
}

# Short locale-aware phrases used inside quick_facts and as fallbacks.
_PHRASES_EN: Mapping[str, str] = {
    "actively_exploited": "Actively exploited",
    "patch_available": "Patch available",
    "affects_one": "Affects {p1}",
    "affects_two": "Affects {p1} & {p2}",
    "multi_platform": "Multi-platform",
    "threat_score": "Threat score {n}/100",
    "users_one": "{p1} users",
    "users_two": "{p1} and {p2} users",
    "users_many": "{leading}, and {last} users",
    "summary_fallback": "{source} reports: {title}",
    "affected_fallback": "Anyone following cybersecurity news",
}

_PHRASES_UK: Mapping[str, str] = {
    "actively_exploited": "Активно експлуатується",
    "patch_available": "Патч доступний",
    # Natural Ukrainian — "Уражає" reads like a Ukrainian editor wrote it,
    # while the earlier "Стосується" was a literal "Affects" calque.
    "affects_one": "Уражає {p1}",
    "affects_two": "Уражає {p1} та {p2}",
    "multi_platform": "Кілька платформ",
    "threat_score": "Рівень загрози {n}/100",
    "users_one": "Користувачі {p1}",
    "users_two": "Користувачі {p1} та {p2}",
    "users_many": "Користувачі {leading} і {last}",
    "summary_fallback": "{source}: {title}",
    "affected_fallback": "Усі, хто стежить за новинами кібербезпеки",
}


# =========================================================================
# Editorial brief templates.
#
# The rule-based `short_summary` is now built from these — NOT extracted
# from the article body. This is a deliberate product decision: CyberAlertX
# must read as a curated intelligence feed, not as scraped RSS. Even when
# the LLM journalist layer is disabled, the rule-based path produces a
# clean, attribution-anchored brief instead of dumping the source's first
# sentences into the card.
#
# Format: "{attribution-verb} {category-noun-phrase}{target-modifier}."
#   attribution-verb  → "{source} reports", "{source} details", ...
#   category-noun     → "a phishing campaign", "a ransomware incident", ...
#   target-modifier   → " targeting {platform}" / " affecting {audience}",
#                       or empty when neither is known.
#
# Picked deterministically from the fingerprint so two items in the same
# category use different verbs and read like distinct briefings, not
# rubber-stamped templates.
# =========================================================================

# Attribution verbs — used in the leading "{source} {verb}..." clause.
# Mixed register: most are reportorial neutral; "warns of" is reserved for
# urgent buckets so the brief reflects the actual urgency of the item.
_ATTRIBUTION_VERBS_EN: list[str] = [
    "reports",
    "details",
    "documents",
    "describes",
    "outlines",
]
_ATTRIBUTION_VERBS_UK: list[str] = [
    "повідомляє про",
    "описує",
    "розповідає про",
    "висвітлює",
    "розбирає",
]
# Urgency-specific verb — overrides the random pick when the item is in
# the "urgent" actionability bucket. Reads as a real-newsroom alert
# instead of generic reportage.
_URGENT_VERB_EN: str = "warns of"
_URGENT_VERB_UK: str = "попереджає про"

# Category → noun phrase that goes after the verb. Stays grammatically
# consistent with "warns of / reports / повідомляє про" (so always
# accusative case in UK, indefinite article in EN).
_BRIEF_NOUN_EN: Mapping[str, str] = {
    "phishing": "a phishing campaign",
    "ransomware": "a ransomware incident",
    "vulnerability": "a newly disclosed vulnerability",
    "exploit": "active exploitation of a vulnerability",
    "zero-day": "a zero-day vulnerability",
    "breach": "a data breach",
    "data leak": "a data leak",
    "malware": "a malware campaign",
    "spyware": "a spyware operation",
    "scam": "a scam campaign",
    "botnet": "a botnet operation",
    "social engineering": "a social-engineering campaign",
    "other": "a cybersecurity incident",
    "default": "a cybersecurity incident",
}
_BRIEF_NOUN_UK: Mapping[str, str] = {
    "phishing": "нову фішингову кампанію",
    "ransomware": "інцидент із програмою-вимагачем",
    "vulnerability": "щойно розкриту вразливість",
    "exploit": "активну експлуатацію вразливості",
    "zero-day": "вразливість нульового дня",
    "breach": "витік даних",
    "data leak": "оприлюднений набір зливних даних",
    "malware": "кампанію зі шкідливим ПЗ",
    "spyware": "операцію зі шпигунським ПЗ",
    "scam": "шахрайську кампанію",
    "botnet": "ботнет-операцію",
    "social engineering": "кампанію соціальної інженерії",
    "other": "інцидент кібербезпеки",
    "default": "інцидент кібербезпеки",
}

# Target-modifier patterns — appended when we know the platform or audience.
# Keep them short; the whole brief is one sentence (two at most).
_TARGET_PLATFORM_EN: str = " targeting {platforms}"
_TARGET_PLATFORM_UK: str = " проти {platforms}"

# Generic audience modifiers used when no platform is known but we DO
# know the targeted reader group.
_AUDIENCE_MODIFIER_EN: Mapping[str, str] = {
    "normal_users": " aimed at everyday users",
    "developers": " aimed at developers",
    "sysadmins": " hitting IT and sysadmins",
    "enterprise": " against enterprise IT environments",
    "mobile_users": " aimed at mobile users",
    "crypto_users": " targeting crypto users",
}
_AUDIENCE_MODIFIER_UK: Mapping[str, str] = {
    "normal_users": " щодо звичайних користувачів",
    "developers": " щодо розробників",
    "sysadmins": " проти ІТ-адміністраторів",
    "enterprise": " проти корпоративного ІТ",
    "mobile_users": " щодо мобільних користувачів",
    "crypto_users": " щодо криптокористувачів",
}

# Generic "what to do" lines used when the item's category has no
# category-specific list. Keeps the actions block non-empty for every
# locale, so the UI always has something to render.
_GENERIC_ACTIONS_EN: list[str] = [
    "Read the source article for the specifics",
    "Apply patches and updates as your vendors release them",
]
_GENERIC_ACTIONS_UK: list[str] = [
    "Прочитайте оригінальну статтю для деталей",
    "Встановлюйте патчі та оновлення, щойно їх випустить вендор",
]


# =========================================================================
# Platform-aware hints.
#
# When the item targets a known platform (one of NewsItem.affected_platforms),
# we PREPEND one platform-specific action so the recommendations name the
# reader's actual environment. The hint is picked deterministically from
# the item's fingerprint so two items on the same platform stay distinct.
#
# Keys are matched case-insensitively against affected_platforms entries.
# Only the *first* matching platform contributes (deduplication is downstream).
# =========================================================================
_PLATFORM_HINTS_EN: Mapping[str, list[str]] = {
    "Microsoft 365": [
        "Open security.microsoft.com → Sign-in activity and review recent logins",
        "Switch the M365 account from SMS 2FA to the Microsoft Authenticator app",
        "Revoke OAuth-app permissions for any third-party app you don't recognize at myaccount.microsoft.com",
    ],
    "Outlook": [
        "Check Outlook → File → Manage Rules — attackers often add hidden forwarding rules",
        "Open security.microsoft.com → Sign-in activity for the connected mailbox",
    ],
    "Gmail": [
        "Open myaccount.google.com/security → Recent security events and review every entry",
        "Visit myaccount.google.com/permissions and revoke apps you don't actively use",
    ],
    "Google": [
        "Run myaccount.google.com/security-checkup end-to-end",
    ],
    "Windows": [
        "Run a full Microsoft Defender scan — Settings → Privacy & security → Windows Security → Virus & threat protection",
        "Open Event Viewer → Security and look for unfamiliar logon events",
    ],
    "Android": [
        "Open Settings → Apps and remove anything you don't remember installing",
        "Settings → Security → Google Play Protect and run a manual scan",
        "Revoke device-admin and accessibility permissions from anything that isn't a known security app",
    ],
    "iOS": [
        "Settings → General → VPN & Device Management — remove any configuration profile you didn't install",
        "Settings → Privacy & Security → Lockdown Mode if you're a likely targeting candidate",
    ],
    "macOS": [
        "System Settings → General → Login Items and remove anything unfamiliar",
        "Run a scan with Malwarebytes or Objective-See KnockKnock for known persistence",
    ],
    "Linux": [
        "Check ~/.ssh/authorized_keys on internet-facing hosts for entries you didn't add",
        "Run rkhunter or chkrootkit against suspicious systems",
    ],
    "Chrome": [
        "Open chrome://settings/passwords and run Password Check Now",
        "chrome://extensions — remove anything you don't actively use",
    ],
    "Firefox": [
        "Open about:logins and review Saved Logins for entries you don't recognize",
        "about:addons — remove unused or unrecognized extensions",
    ],
    "Safari": [
        "Safari → Settings → Extensions and remove anything you don't actively use",
    ],
    "WordPress": [
        "Update WordPress core, plugins, and themes — most WP compromises hit unpatched plugins",
        "Audit the Users list for admin accounts you didn't create",
    ],
    "Telegram": [
        "Settings → Devices and end any session you don't recognize",
        "Settings → Privacy and Security → Two-Step Verification and set a password",
    ],
    "Discord": [
        "User Settings → Devices and log out of sessions you don't recognize",
        "User Settings → Authorized Apps and revoke anything unfamiliar",
    ],
    "WhatsApp": [
        "Settings → Linked Devices and remove sessions you don't recognize",
    ],
}

_PLATFORM_HINTS_UK: Mapping[str, list[str]] = {
    "Microsoft 365": [
        "Зайдіть на security.microsoft.com → Sign-in activity і перегляньте нещодавні входи",
        "Переведіть M365-акаунт з SMS-2FA на додаток Microsoft Authenticator",
        "На myaccount.microsoft.com заберіть дозволи у сторонніх OAuth-додатків, яких не впізнаєте",
    ],
    "Outlook": [
        "Outlook → Файл → Управління правилами — атакувальники часто додають приховані правила пересилання",
        "Перевірте Sign-in activity на security.microsoft.com для підключеної поштової скриньки",
    ],
    "Gmail": [
        "Відкрийте myaccount.google.com/security → Recent security events і перегляньте кожен запис",
        "На myaccount.google.com/permissions заберіть доступ у додатків, якими ви не користуєтеся",
    ],
    "Google": [
        "Пройдіть до кінця myaccount.google.com/security-checkup",
    ],
    "Windows": [
        "Запустіть повну перевірку Microsoft Defender — Параметри → Конфіденційність → Безпека Windows → Захист від вірусів",
        "Event Viewer → Security: подивіться на незнайомі події входу",
    ],
    "Android": [
        "Налаштування → Програми і видаліть усе, що не пам'ятаєте, як встановлювали",
        "Налаштування → Безпека → Google Play Protect і запустіть перевірку вручну",
        "Заберіть дозволи Device Admin та Accessibility у всього, що не є відомим захисним додатком",
    ],
    "iOS": [
        "Налаштування → Загальні → VPN і керування пристроєм — видаліть профілі, які ви не встановлювали",
        "Налаштування → Конфіденційність → Lockdown Mode, якщо ви потенційна ціль",
    ],
    "macOS": [
        "Системні параметри → Загальні → Об'єкти входу — видаліть незнайоме",
        "Запустіть Malwarebytes або Objective-See KnockKnock для перевірки на постійні зловмисники",
    ],
    "Linux": [
        "Перегляньте ~/.ssh/authorized_keys на серверах з публічним інтерфейсом — видаліть ключі, які не додавали",
        "Запустіть rkhunter або chkrootkit на підозрілих системах",
    ],
    "Chrome": [
        "Відкрийте chrome://settings/passwords і запустіть Password Check Now",
        "chrome://extensions — видаліть розширення, якими не користуєтесь",
    ],
    "Firefox": [
        "Відкрийте about:logins і перегляньте збережені логіни на незнайомі записи",
        "about:addons — видаліть невідомі чи невикористовувані розширення",
    ],
    "Safari": [
        "Safari → Параметри → Розширення і вимкніть незнайомі",
    ],
    "WordPress": [
        "Оновіть ядро WordPress, плагіни і теми — більшість зламів WP — це непропатчені плагіни",
        "Перегляньте список Users — видаліть адмін-акаунти, які ви не створювали",
    ],
    "Telegram": [
        "Налаштування → Пристрої і завершіть сесії, які не впізнаєте",
        "Налаштування → Конфіденційність → Двоетапна перевірка — встановіть пароль",
    ],
    "Discord": [
        "User Settings → Devices і вийдіть з сесій, які не впізнаєте",
        "User Settings → Authorized Apps і відкличте дозволи незнайомих додатків",
    ],
    "WhatsApp": [
        "Налаштування → Зв'язані пристрої і вийдіть з сесій, які не впізнаєте",
    ],
}


def _tables(language: str) -> tuple:
    """Return the locale-specific bundle:
    (why_it_matters, actions, avoids, audience, category_label, phrases,
    generic_actions, platform_hints)."""
    if language == "ua":
        return (
            _WHY_IT_MATTERS_UK,
            _DEFAULT_ACTIONS_UK,
            _DEFAULT_AVOIDS_UK,
            _HUMAN_AUDIENCE_UK,
            _CATEGORY_FACT_LABEL_UK,
            _PHRASES_UK,
            _GENERIC_ACTIONS_UK,
            _PLATFORM_HINTS_UK,
        )
    return (
        _WHY_IT_MATTERS_EN,
        _DEFAULT_ACTIONS_EN,
        _DEFAULT_AVOIDS_EN,
        _HUMAN_AUDIENCE_EN,
        _CATEGORY_FACT_LABEL_EN,
        _PHRASES_EN,
        _GENERIC_ACTIONS_EN,
        _PLATFORM_HINTS_EN,
    )


def _pick_n(pool: Iterable[str], fingerprint: str, n: int, salt: int = 0) -> list[str]:
    """Pick `n` items from `pool` deterministically from `fingerprint`.

    Strategy: rotate the pool by `(hash(fp) + salt) % len(pool)` and take
    the first `n`. Two items in the same category have different
    fingerprints → different rotations → different subsets. Same item
    always picks the same subset (cacheable, testable).

    `salt` lets two callers (what-to-do / what-not-to-do) for the same
    item pick *different* subsets of an action pool — pass salt=1 from
    the don't-list site and the picker rotates by an additional step.
    """
    items = list(pool)
    if not items or n <= 0:
        return []
    if len(items) <= n:
        return items
    try:
        seed = int(fingerprint[:8], 16) + salt * 0x9e3779b9
    except (ValueError, IndexError):
        seed = salt
    offset = seed % len(items)
    rotated = items[offset:] + items[:offset]
    return rotated[:n]


def _join_platforms(platforms: Sequence[str], conj: str) -> str:
    """Natural-language join: ['A', 'B'] → 'A and B' / 'A та B'; one→one."""
    if not platforms:
        return ""
    if len(platforms) == 1:
        return platforms[0]
    if len(platforms) == 2:
        return f"{platforms[0]} {conj} {platforms[1]}"
    return f"{', '.join(platforms[:-1])} {conj} {platforms[-1]}"


def _build_editorial_brief(item: NewsItem, *, language: str) -> str:
    """Compose a single-sentence intelligence brief for `item` in `language`.

    Shape: `{source} {verb} {category-noun}{platform-modifier-or-audience}.`

    Rule-based path — no AI, no source-body reuse. Even with the title
    omitted (which we never do — the card has its own title field), the
    resulting summary is a self-contained, attribution-anchored fact that
    a reader can grasp in one glance.

    Pick determinism comes from the item's fingerprint, so re-renders are
    stable and the same author/category never collide on the same verb.
    """
    if language == "ua":
        verbs = _ATTRIBUTION_VERBS_UK
        urgent_verb = _URGENT_VERB_UK
        noun_table = _BRIEF_NOUN_UK
        platform_tmpl = _TARGET_PLATFORM_UK
        audience_table = _AUDIENCE_MODIFIER_UK
        conjunction = "та"
    else:
        verbs = _ATTRIBUTION_VERBS_EN
        urgent_verb = _URGENT_VERB_EN
        noun_table = _BRIEF_NOUN_EN
        platform_tmpl = _TARGET_PLATFORM_EN
        audience_table = _AUDIENCE_MODIFIER_EN
        conjunction = "and"

    # Verb selection — urgent items use the alarm-leaning verb so the
    # brief itself signals urgency before the threat-level badge is read.
    if item.actionability_level == "urgent_action":
        verb = urgent_verb
    else:
        verb = _pick_n(verbs, item.fingerprint, 1, salt=42)[0]

    category_key = item.category if item.category in noun_table else "default"
    noun_phrase = noun_table[category_key]

    # Target modifier — prefer platforms (most concrete), fall back to
    # audience, otherwise leave empty. Multi-platform items collapse the
    # list with a natural-language join.
    target = ""
    if item.affected_platforms:
        joined = _join_platforms(list(item.affected_platforms), conjunction)
        target = platform_tmpl.format(platforms=joined)
    elif item.audience_targets:
        modifier = audience_table.get(item.audience_targets[0])
        if modifier:
            target = modifier

    return f"{item.source} {verb} {noun_phrase}{target}."


def _platform_hint_for(
    item: NewsItem, platform_hints: Mapping[str, list[str]],
) -> str | None:
    """Return a platform-specific hint for the first matched platform, or None.

    Match is case-insensitive on `affected_platforms` entries. Order
    preserved — first match wins. The picked hint within the matched
    platform's pool varies deterministically per fingerprint.
    """
    if not item.affected_platforms:
        return None
    # Build a lower-cased lookup once.
    lookup = {k.lower(): v for k, v in platform_hints.items()}
    for plat in item.affected_platforms:
        pool = lookup.get(plat.lower())
        if pool:
            picked = _pick_n(pool, item.fingerprint, 1)
            return picked[0] if picked else None
    return None


_PATCH_AVAILABLE_RE = re.compile(
    r"\b(patch|fix|update)\s+(is\s+)?(available|released|now\s+available|out)\b",
    flags=re.IGNORECASE,
)
_ACTIVE_EXPLOIT_RE = re.compile(
    r"\b(actively\s+exploited|in\s+the\s+wild|under\s+(active\s+)?attack)\b",
    flags=re.IGNORECASE,
)
# Lines like "By John Doe, May 11, 2026" — common feed prefixes we want to skip.
_BYLINE_RE = re.compile(
    r"^\s*(by\s+\S+|posted\s+by\s+\S+|on\s+\w+\s+\d{1,2},?\s*\d{4})\b",
    flags=re.IGNORECASE,
)


def _urgency_bucket(item: NewsItem) -> str:
    """Map (actionability_level, threat_score) to one of: urgent | soon | fyi."""
    if item.actionability_level == "urgent_action":
        return "urgent"
    if item.actionability_level == "recommended_action":
        return "soon"
    # Informational with a high threat score still benefits from "soon" framing.
    if item.threat_score >= 50:
        return "soon"
    return "fyi"


def _variant_index(fingerprint: str, count: int) -> int:
    """Pick a variant index deterministically from the item's fingerprint."""
    if count <= 1:
        return 0
    try:
        seed = int(fingerprint[:8], 16)
    except (ValueError, IndexError):
        seed = 0
    return seed % count


def _select_why_it_matters(
    category: str, bucket: str, fingerprint: str, table: Mapping[tuple[str, str], Sequence[str]],
) -> str:
    """Pick the why_it_matters line for this (category, bucket, language).

    Resolution order, each used only if the previous misses:
      1. (category, bucket) — the precise, category-specific entry
      2. (default, bucket)  — the generic-by-urgency entry (always defined)
      3. (default, "fyi")   — final safety net (always defined)

    We never return a placeholder string; every path ends at a real line.
    """
    variants = (
        table.get((category, bucket))
        or table.get(("default", bucket))
        or table[("default", "fyi")]
    )
    return variants[_variant_index(fingerprint, len(variants))]


def _trim_at_word(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text.rfind(" ", 0, limit)
    if cut < limit * 0.6:
        cut = limit
    return text[:cut].rstrip(",.:;-"), True


_PRESERVED_ACRONYMS: frozenset[str] = frozenset({
    "AI", "API", "APT", "AWS", "BIOS", "CISA", "CVE", "DDoS", "DNS",
    "FBI", "GPU", "HTTP", "HTTPS", "ICS", "IoT", "IP", "JS", "JSON",
    "LDAP", "MFA", "NSA", "OAuth", "OS", "OTP", "PDF", "PHP", "PIN",
    "RAM", "RCE", "RDP", "SDK", "SMS", "SQL", "SSH", "SSL", "TLS",
    "UEFI", "URL", "USB", "VPN", "XML", "XSS", "2FA",
})


def _normalize_shouty_title(title: str) -> str:
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 8:
        return title
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.7:
        return title

    def fix(word: str) -> str:
        if any(c.isdigit() for c in word):
            return word
        if word in _PRESERVED_ACRONYMS:
            return word
        if word.isupper():
            return word.capitalize()
        return word

    return " ".join(fix(w) for w in title.split())


def _extract_lead(body: str, max_chars: int = 220) -> str:
    body = body.strip()
    if not body:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", body)
    while sentences and _BYLINE_RE.match(sentences[0]):
        sentences.pop(0)
    if not sentences:
        return ""

    snippet = sentences[0].strip()
    if len(snippet) < 100 and len(sentences) > 1:
        snippet = (snippet + " " + sentences[1].strip()).strip()

    trimmed, truncated = _trim_at_word(snippet, max_chars)
    return trimmed + ("…" if truncated else "")


class RuleBasedGenerator:
    """Always-available ThreatPost generator. No network, no LLM, no key required."""

    def __init__(self, template_registry: TemplateRegistry | None = None) -> None:
        self._templates = template_registry or default_template_registry()

    def generate(self, item: NewsItem, language: str | None = None) -> ThreatPost:
        """Generate a ThreatPost in the requested locale.

        `language` overrides item.language. When None, falls back to
        item.language, then "en". Only "en" and "ua" are accepted; anything
        else is normalized to "en".
        """
        lang = language or item.language
        if lang not in ("en", "ua"):
            lang = "en"
        audience = item.audience_targets[0] if item.audience_targets else "general"
        overrides = self._lookup_overrides(lang, item.category, audience)
        bucket = _urgency_bucket(item)
        (
            why_table, actions_table, avoids_table, audience_table,
            label_table, phrases, generic_actions, platform_hints,
        ) = _tables(lang)

        # References: regex-extracted from the article body. Cheap,
        # verifiable, no API tokens. Adds CVE/CISA/CERT-UA/MSRC links
        # automatically when present in the source text.
        from .references import extract_references
        references = extract_references(item.raw_content or "")

        return ThreatPost(
            title=self._title(item),
            short_summary=self._summary(item, lang),
            threat_level=self._threat_level(item),
            why_it_matters=self._why_it_matters(item, bucket, overrides, why_table),
            affected_users=self._affected_users(item, audience_table, phrases),
            what_to_do=self._what_to_do(
                item, overrides, actions_table, generic_actions, platform_hints,
            ),
            what_not_to_do=self._what_not_to_do(item, overrides, avoids_table),
            quick_facts=self._quick_facts(item, label_table, phrases),
            emotional_weight=self._emotional_weight(item),
            reading_time_seconds=self._reading_time(item),
            # Rule-based doesn't synthesize an expanded `detail_body` —
            # we leave it empty so the frontend gracefully falls back to
            # the per-category narrative blocks in `detail_context.py`.
            # The AI path is what fills detail_body with item-specific
            # analysis when it runs.
            detail_body="",
            references=references,
            language=lang,
            source_fingerprint=item.fingerprint,
            generated_by="rule_based",
        )

    # ---------- template integration ----------

    def _lookup_overrides(
        self, language: str, category: str, audience: str,
    ) -> Mapping[str, object]:
        template = self._templates.select(language, category, audience)
        return template.rule_based or {}

    # ---------- field derivations ----------

    @staticmethod
    def _title(item: NewsItem) -> str:
        t = _normalize_shouty_title(item.title.strip())
        trimmed, truncated = _trim_at_word(t, 120)
        return trimmed + ("…" if truncated else "")

    @staticmethod
    def _summary(item: NewsItem, language: str) -> str:
        """Editorial brief — pure synthesis, NEVER a copy of source body.

        We deliberately do NOT read `item.raw_content` here. CyberAlertX is
        an intelligence feed, not an RSS mirror; even when the LLM journalist
        layer is off, the card should look like a curated brief instead of
        the first sentences of a scraped article.

        The brief is built from facts we already extracted upstream (source,
        category, platforms, audience) plus a deterministic attribution verb,
        producing one short, attribution-anchored sentence in the requested
        locale. Different fingerprints yield different verbs so two items
        in the same category don't read identically.
        """
        return _build_editorial_brief(item, language=language)

    @staticmethod
    def _threat_level(item: NewsItem) -> str:
        if item.actionability_level == "urgent_action":
            return "Critical" if item.threat_score >= 50 else "High"
        if item.actionability_level == "recommended_action":
            return "High" if item.threat_score >= 50 else "Medium"
        return "Medium" if item.threat_score >= 30 else "Low"

    @staticmethod
    def _why_it_matters(
        item: NewsItem,
        bucket: str,
        overrides: Mapping[str, object],
        table: Mapping[tuple[str, str], Sequence[str]],
    ) -> str:
        override = overrides.get("why_it_matters")
        if isinstance(override, str) and override.strip():
            return override.strip()
        return _select_why_it_matters(item.category, bucket, item.fingerprint, table)

    @staticmethod
    def _affected_users(
        item: NewsItem,
        audience_table: Mapping[str, str],
        phrases: Mapping[str, str],
    ) -> list[str]:
        out: list[str] = []
        if item.affected_platforms:
            platforms = item.affected_platforms
            if len(platforms) == 1:
                out.append(phrases["users_one"].format(p1=platforms[0]))
            elif len(platforms) == 2:
                out.append(phrases["users_two"].format(p1=platforms[0], p2=platforms[1]))
            else:
                out.append(phrases["users_many"].format(
                    leading=", ".join(platforms[:-1]), last=platforms[-1],
                ))
        for a in item.audience_targets:
            label = audience_table.get(a, a.replace("_", " ").capitalize())
            if label not in out:
                out.append(label)
        return out or [phrases["affected_fallback"]]

    # Number of actions to render per card. 3 is the sweet spot for mobile —
    # enough to be useful, few enough to scan in a glance.
    _ACTIONS_PER_CARD = 3
    _AVOIDS_PER_CARD = 2

    @staticmethod
    def _what_to_do(
        item: NewsItem,
        overrides: Mapping[str, object],
        actions_table: Mapping[str, list[str]],
        generic_actions: list[str],
        platform_hints: Mapping[str, list[str]],
    ) -> list[str]:
        """Compose the do-list:
          1. Template override (when an audience-specific override is defined,
             trust it verbatim — the author hand-tuned that copy).
          2. Otherwise: pick N from the category pool deterministically
             from the item's fingerprint. Two items in the same category
             get different subsets.
          3. If the item targets a known platform, PREPEND one
             platform-specific hint so the recommendation names the
             reader's actual environment (e.g. "Open security.microsoft.com").
          4. Dedupe — overlap between platform hint and generic action
             would be confusing.
        """
        override = overrides.get("what_to_do")
        if isinstance(override, (list, tuple)) and override:
            return [str(s).strip() for s in override if str(s).strip()]
        pool = actions_table.get(item.category) or generic_actions
        actions = _pick_n(pool, item.fingerprint, RuleBasedGenerator._ACTIONS_PER_CARD)
        hint = _platform_hint_for(item, platform_hints)
        if hint and hint not in actions:
            # Prepend; trim the tail so the total list stays at N.
            actions = [hint] + actions[: RuleBasedGenerator._ACTIONS_PER_CARD - 1]
        return actions

    @staticmethod
    def _what_not_to_do(
        item: NewsItem,
        overrides: Mapping[str, object],
        avoids_table: Mapping[str, list[str]],
    ) -> list[str]:
        """Compose the don't-list:
          1. Template override (verbatim, like _what_to_do).
          2. Otherwise: pick N from the category pool, with a salt so
             two items rotate through DIFFERENT subsets than they would
             for the do-list. Keeps the two lists from feeling correlated.
        """
        override = overrides.get("what_not_to_do")
        if isinstance(override, (list, tuple)):
            return [str(s).strip() for s in override if str(s).strip()]
        pool = avoids_table.get(item.category, [])
        return _pick_n(pool, item.fingerprint, RuleBasedGenerator._AVOIDS_PER_CARD, salt=1)

    @staticmethod
    def _quick_facts(
        item: NewsItem,
        label_table: Mapping[str, str],
        phrases: Mapping[str, str],
    ) -> list[str]:
        facts: list[str] = []
        text_lower = (item.title + "\n" + item.raw_content).lower()

        if _ACTIVE_EXPLOIT_RE.search(text_lower) or item.actionability_level == "urgent_action":
            facts.append(phrases["actively_exploited"])
        elif _PATCH_AVAILABLE_RE.search(text_lower):
            facts.append(phrases["patch_available"])

        platforms = item.affected_platforms
        if len(platforms) == 1:
            facts.append(phrases["affects_one"].format(p1=platforms[0]))
        elif len(platforms) == 2:
            facts.append(phrases["affects_two"].format(p1=platforms[0], p2=platforms[1]))
        elif len(platforms) >= 3:
            facts.append(phrases["multi_platform"])

        if item.category and item.category != "other":
            facts.append(label_table.get(item.category, item.category.capitalize()))

        if item.source_tier == "trusted" and item.source_credibility_score >= 0.85:
            facts.append(f"{item.source}")

        # Intentionally no fallback labels when nothing fires.
        # The old code injected "source + threat_score N/100" which on
        # low-info items rendered "Source / Threat score 0/100" — a
        # misleading placeholder. The threat-level badge already
        # communicates severity, so an empty quick_facts list is a
        # better signal: the UI just hides the section.

        seen: set[str] = set()
        unique: list[str] = []
        for f in facts:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        return unique[:4]

    @staticmethod
    def _emotional_weight(item: NewsItem) -> float:
        weight = (
            item.actionability_score * 0.6
            + min(item.threat_score / 100.0, 1.0) * 0.3
            + item.source_credibility_score * 0.1
        )
        return round(max(0.0, min(1.0, weight)), 3)

    @staticmethod
    def _reading_time(item: NewsItem) -> int:
        words = len(item.raw_content.split())
        sec = max(15, min(45, words // 3))
        return sec


# Backwards-compatible aliases — the test suite and any callers that knew
# the pre-locale-aware module name still get the English tables under the
# old identifiers. Internal code should prefer `_tables(language)`.
_WHY_IT_MATTERS = _WHY_IT_MATTERS_EN
_CATEGORY_FACT_LABEL = _CATEGORY_FACT_LABEL_EN


__all__ = ["RuleBasedGenerator"]
