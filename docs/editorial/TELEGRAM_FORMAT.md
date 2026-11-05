# Telegram post format

Each channel post is one photo: the story's canonical illustration, the
same asset as the website. The caption is described below, and a single
inline button links to the full article. The caption is built by
`cyberalertx/publish/format.py` from the reviewed brief, the stored severity
and the evidence labels. Nothing is recalculated or invented for
presentation.

## Structure

```
🧩 Headline                                    one semantic emoji + bold headline
TL;DR — one complete sentence                   plain_summary
What happened — one paragraph                   short_summary, only if it adds a name, product or number

🎯 Why it matters: one sentence                 why_it_matters
⚙️ How it works: one sentence                   from the article analysis, only when it explains the mechanism
👥 Who is affected: a · b · c                   affected_users (max 3)
🛡️ What to do: • … • …                          what_to_do (max 2), only when justified
⚠️ Unconfirmed: …                               attackers' claims, suspected exploitation (always shown)
❔ Not yet known: …                             open questions the source states

🟠 Severity: High · exploitation confirmed      stored threat_level + confirmed evidence only
🔗 Source: <linked outlet> · also CISA          original article
#vulnerability #Windows                         at most 3, only category and platforms
[📖 Read the full analysis]                    inline button → /{en,ua}/threat/{id}
```

UA labels: Чому це важливо, Як це працює, Кого стосується, Що робити,
Не підтверджено, Поки невідомо, Рівень загрози: високий, Джерело, and the
button «📖 Читати повний розбір».

Sections without content are omitted. Nothing is forced into every post.

## Emoji vocabulary

| Headline emoji | When |
|---|---|
| 🏭 | industrial / OT, cold-chain and building controllers (checked first) |
| 🕵️ | the headline is about a threat actor (APT, state-linked, named group), or the story is a group's claim |
| 🧩 🦠 🎣 🔓 🔐 | category: vulnerability/exploit, malware/botnet, phishing/scam, breach/leak, ransomware |
| ☁️ | cloud, SaaS, Microsoft 365, Kubernetes, when the category says nothing more specific |
| 🔬 | research, statistics or tests, for Low or Medium stories |
| none | when nothing fits (no generic decoration) |

Severity dots 🔴 🟠 🟡 🔵 map one-to-one to the stored `threat_level`. An
unknown value gets no label. Section markers are the ones shown above, each
used at most once.

## Accuracy rules

- **Claims are labelled.** When the brief reports a statement by the
  attackers themselves ("NoName057(16) claimed…", «хакери заявили…»), the
  post says so in ⚠️. It never shows "data exposure confirmed" for a claim.
  A vendor or agency statement ("CISA says") is not a claim.
- **Severity and evidence stay apart.** Only confirmed evidence appears
  next to the severity. Suspicion goes to ⚠️ and open questions to ❔.
- **Advice must fit the threat.** Only `what_to_do` is used, at most two
  steps. Steps unrelated to the affected systems (consumer food-safety tips
  under a refrigeration-controller attack) are dropped, never rewritten.
- **No repetition.** A paragraph that mostly restates the headline and TL;DR
  is dropped. The check uses Ukrainian-aware 5-letter stems. "BleepingComputer
  reports that…" or «dev.ua повідомляє, що…» is removed when that outlet is
  already on the source line.
- **No truncation.** Optional sections are added in priority order while the
  caption stays at or under 900 characters:
  1. action;
  2. why it matters;
  3. open questions;
  4. what happened;
  5. who is affected;
  6. how it works;
  7. tags.

  A section that does not fit is skipped whole. The hard limit is
  Telegram's 1024 characters (UTF-16), including an update prefix. A
  sentence is never cut.
- **Formatting is checked before every send** (`format_problem`):
  - only `b`, `i`, `a` and `code` tags, balanced;
  - links only to http(s);
  - escaped markup characters;
  - within the limit.

  A failing post is not sent.

## Illustration

The photo is `https://cyberalertx.com/media/{asset}/telegram.png`, the same
asset as the article page. No second, Telegram-only image exists. Stories
whose source describes a compromised website script (analytics or
third-party code, skimming, watering holes) are drawn as that script inside
a site, spreading to visitors' phones and laptops. The renderer is
unchanged; this is one more event in it. On current data it applies to five
stories:
- APT29's Plerdy attack (EN and UA);
- Convertr skimming;
- the iOS/Android watering hole;
- Polymarket's third-party JavaScript.

## Evaluation (5 Nov 2026)

These are 34 real stories, 61 captions (EN and UA), rendered by the
previous and the new formatter from the same briefs. The set covers APT
campaigns, vulnerabilities, malware, phishing, ransomware, breaches,
industrial attacks, cloud attacks, threat-actor claims, security research and
supply-chain scripts. All counts are measured by script.

| Check | Before | After |
|---|---|---|
| Sentences not traceable to the brief | 0 | 0 |
| Wrong severity label | 0 | 0 |
| Captions over 1024 / cut mid-sentence / malformed | 0 / 0 / 0 | 0 / 0 / 0 |
| Article link correct | 61 | 61 (button) |
| Source linked | 61 | 61 |
| Attackers' claims labelled as unconfirmed | 0 of 3 | 3 of 3 |
| Off-topic advice shown | 2 | 0 |
| Block pairs that largely repeat each other | 7 | 6 |
| Captions within 700–900 characters | 31 | 47 |
| Length min / median / max | 409 / 773 / 957 | 522 / 808 / 899 |
| English labels in UA posts | 0 | 0 |
| Emoji per post (median / max) | 0 / 0 | 5 / 7 |

What did not change:
- every fact and sentence (all text comes verbatim from the brief);
- severity values;
- eligibility, schedule, channels, ledger and deduplication.

Repetition improves only modestly. The clear restatements from before
(APT29/Plerdy, UNM Health, JAL) are gone. Of the six remaining pairs, three
are the 👥 audience list sharing a product name with the TL;DR or an action,
and three are partial prose overlaps that each add a detail ("one supplier,
three sites").

## Examples

**Claim (UA, Rosstat).** Before, the group's statement had no
qualification. After:

```
🕵️ Silent Crow і «Кіберпартизани BY» заявили, що знищили ІТ-системи Росстату й винесли 23 ТБ

Білоруські «Кіберпартизани» й Silent Crow кажуть, що зламали російську статслужбу Росстат і винесли 23 терабайти даних, зокрема про втрати Росії у війні.

🎯 Чому це важливо: Якщо дані справжні і їх оприлюднять, цифри Росстату про втрати Росії у війні можна буде звірити з офіційними заявами Москви.

👥 Кого стосується: Росстат, державна статистика Росії · Відомства, що користуються даними Росстату · Аналітики відкритих джерел

⚠️ Не підтверджено: це заява самих зловмисників, незалежного підтвердження поки немає.

🟡 Рівень загрози: середній
🔗 Джерело: dev.ua
[📖 Читати повний розбір]
```

**Advice (UA, supermarket freezers).** Before, the first action was
«Гляньте на термометр морозильної вітрини, перш ніж брати заморожені
продукти». After, the actions address the operators:

```
🛡️ Що робити:
• Приберіть з інтернету панелі керування холодильними контролерами в магазинах.
• Налаштуйте сповіщення про будь-яку зміну температурних налаштувань морозильників.
```

**Repetition (UA, APT29 / Plerdy).** Before, a second paragraph restated
the TL;DR («APT29 заражала iPhone і Android-смартфони через українські та
західні сайти…»). After, the paragraph is gone. The headline gets 🕵️ instead
of 🔓, and the photo shows the analytics script spreading from a site to
visitors' phones instead of "an archive under inspection".

**Vulnerability (EN, "SMS of Death").** Before and after both keep the facts,
the CVE link and the two actions. After adds the emoji, the section markers,
"Who is affected" and the button, and drops the "Read more" text line:

```
🧩 Unpatched Android phones can be knocked offline by a single text message

Update your Android phone: a booby-trapped text message can crash it or cut its mobile signal, and the attack method is now public.

BleepingComputer reports a public proof-of-concept for CVE-2026-58882, the recently patched "SMS of Death" Android flaw that crashes phones or disrupts cellular service through a crafted SMS.

🎯 Why it matters: With public exploit code, anyone who has your number can crash an unpatched phone or cut its signal.

👥 Who is affected: Unpatched Android phone owners · Owners of out-of-support Android phones · Corporate Android fleet admins

🛡️ What to do:
• Install pending updates in Settings > System > Software update, then restart the phone.
• Push the latest Android security patch to managed phones through your MDM console.

🟠 Severity: High
🔗 Source: BleepingComputer
[📖 Read the full analysis]
```

## Limits

- Claim detection is wording-based (an actor noun plus a claim verb, in EN
  and UA). An unusual phrasing can be missed. It errs towards labelling.
- The off-topic advice filter knows only the consumer-goods pattern seen in
  the data. Other irrelevant advice must be fixed in the brief, which the
  review gate covers.
- ⚙️ "How it works" needs an article analysis (`detail_body`). About a
  quarter of briefs have none, and the category templates in
  `detail_context` are deliberately not used, because they are not specific
  to the article.
