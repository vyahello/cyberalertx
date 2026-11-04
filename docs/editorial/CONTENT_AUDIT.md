# CyberAlertX content audit (archive snapshot, 2 November 2026)

Editorial quality review of every cached brief in
`data/threat_posts.json`. All numbers below were computed from that file and
`data/items.json` with read-only Python scripts. Nothing here was estimated.

## 1. Scope and method

| | Count |
|---|---|
| Briefs | 4,453 (EN 2,020, UA 2,433) |
| Fingerprints | 2,436: 2,017 bilingual, 416 UA-only, 3 EN-only |
| Generator | `claude-cli:default` 4,204; `anthropic:claude-haiku-4-5` 249 (EN 115, UA 134) |
| Source items available (`items.json`) | 200 items; 164 of them have briefs (285 briefs: 121 EN, 164 UA) |

**Generations.** Posts carry no timestamp, but the file is in insertion order
and three schema versions follow each other, so we use them as generations:

| Bucket | Definition | EN | UA |
|---|---|---|---|
| haiku-A | Haiku, oldest schema | 115 | 134 |
| cli-A | CLI, no `plain_summary` | 309 | 368 |
| cli-B | CLI, `plain_summary`, no `severity_reason` | 354 | 411 |
| cli-C | CLI, current schema (`severity_reason`, `am_i_affected`) | 1,242 | 1,520 |

**Reading.** 35 UA and 19 EN briefs were read in full (sources shown where
available), across all four buckets, all eight outlets (BleepingComputer, The
Hacker News, CISA, Securelist, dev.ua, itc.ua, dou.ua, ain.ua) and categories
vulnerability, exploit, malware, ransomware, breach, phishing, spyware, scam,
other. Further briefs were read when a count needed checking.

**Counting.** Linguistic counts are regex scans over all text fields, with a
word boundary that treats apostrophes as part of the word. Counts are
"briefs containing the form", unless marked "occurrences". Regexes for
constructions (passives, calques) over-count somewhat; where we checked false
positives by hand, the table says so.

**Limits.**
- Source fidelity can be checked only for the 285 briefs whose item is in
  `items.json`. Those items are RSS teasers: median 382 characters (The Hacker
  News ≈392, BleepingComputer ≈201, CISA ≈2,820). A fact absent from the
  teaser may still be in the full article, but the pipeline never sees the
  full article (baseline audit §6), so a brief cannot legitimately contain it.
- The automated fidelity check (CVE IDs, years, version strings, ports and
  "background" phrases not in the teaser) is a lower bound.

Severity labels used below: **Critical** (published content is false,
misattributed or not news), **High** (misleads or fails the reader on a
material point), **Medium** (degrades quality or trust at scale), **Low**
(polish).

## 2. Scorecard

| Metric | EN | UA |
|---|---|---|
| Empty analysis (`detail_body`), whole archive | 252 / 2,020 (12.5%) | 471 / 2,433 (19.4%) |
| Empty analysis, current generation (cli-C) | 173 / 1,242 (13.9%) | 366 / 1,520 (24.1%) |
| Empty analysis, UA-only stories | — | 215 / 416 (51.7%) |
| Empty analysis, UA side of bilingual stories | — | 256 / 2,017 (12.7%) |
| Empty `am_i_affected` (cli-C) | 121 / 1,242 (9.7%) | 252 / 1,520 (16.6%) |
| Empty `if_already_affected` (cli-C, often legitimately) | 276 (22.2%) | 459 (30.2%) |
| Empty `what_not_to_do` | 57 (2.8%) | 151 (6.2%) |
| Brief's banned filler phrases (7 phrases) | 0 | n/a |
| Internal pipeline labels in text (threat score, actionability, "informational") | 73 | 21 |
| Meta references to "the source"/teaser | 196 (narrative fields) | 83 |
| Severity differs EN vs UA on same story | 443 / 2,017 pairs (22.0%); cli-C 139 / 1,242 (11.2%) | |

## 3. Findings

### F1. Non-security items published as threat briefs — Critical
**29 UA-only briefs** (verified one by one) cover topics with no security
content: game trailers (`8f1d28b46a63775d`, `883eb214111ce7d3`,
`c0f0a626c0d0a328` "Cronos: Lazarus", probably matched on "Lazarus"), monitor
and laptop reviews (`3e659275d2c056b2`, `037a9bae09febe7d`,
`82e7ac3eddc04a16`), trains (`2091b0f17e2cbc62`, `fa849eb9421929f8`),
satellites (`13f9c1aa686f04a0`, `c050f89a66ca62f0`, `ff9b95fee00b5a5b`),
eSports (`27814544e0ba7af7`, `0af8a563559912cd`, `4a2b9668bebf6b9a`,
`6cfeddc8a98e866e`, `1ef37aa9b444644a`, `0ae1af88418f6bb6`), TV series
(`ed59ae1703be6ab2`, `503728559f8b39b6`), a wine-bottle collection
(`76d31b2a3fa2b8d0`), a hydro plant (`9bdbaf0ff3a13ca5`), mobilisation-deferment
rules (`4dec087390da4de4`), drone codification (`65a32171ba5abfd1`,
`3a1ee0d3b835193a`), a hydrogen deposit (`98b97728663ba724`), recruiting
(`48868757f348f25e`), a QR-code hobby project (`449181ad69e3a70a`), a coding
school (`c6da58c9db09652c`).
All 29 are rated Low and all 29 carry "what to do" advice, e.g.
"Перевірте розклад Sound Transit перед поїздкою" (`fa849eb9421929f8`),
"Пропустіть цей матеріал: він не про кібербезпеку" (`76d31b2a3fa2b8d0`).
Several headlines admit it: «Огляд монітора Acer Nitro XF273 UF3 — це не
новина про безпеку». The model recognised the problem; nothing let it decline.
**Origin:** ingest relevance filter for UA outlets (keyword matches on
"кібер-", "Lazarus"), plus no reject path in generation, plus the website
publishing every cached post.

### F2. Unattributed background knowledge stated as reporting — High
In the 285 source-checkable briefs, the automated check flagged 29; manual
review confirmed **12 briefs (9 of 121 EN = 7.4%, 3 of 164 UA = 1.8%)** that
state historical facts absent from the teaser, without attribution:

| Brief | Claim not in source |
|---|---|
| `0f81648bf5c6b707:en` (Synology/C3RB3R) | "In late 2023 it encrypted Confluence servers within days of CVE-2023-22518"; "No free decryptor exists for current C3RB3R builds" (also in `quick_facts`) |
| `62af280b86d2c33a:en` (Nefilim/Hive sentence) | FBI inside Hive July 2022, keys to 1,000+ victims, server seizure January 2023, Nefilim active from early 2020, No More Ransom check |
| `f635e51b46992649:en` (Ivanti KEV) | early-2024 wave CVE-2023-46805 / CVE-2024-21887; "A flaw only goes into KEV with clear mitigation guidance, so a vendor fix … should already exist" |
| `e24342c52a0b2ee1:en`, `c305d693e177d5ef:en` | Ivanti appliances mass-exploited since 2024; malware surviving upgrades in 2024–2025 |
| `68f2c8a7a2b64fb9:en` and `:ua` (BlackX) | Kaspersky tied MoonBounce to APT41 in 2022; Microsoft left BlackLotus revocations manual (EN) |
| `0b33a76a486a83fb:en` (Volt Typhoon) | FBI's January 2024 KV-botnet disruption |
| `87bf34b6e070a947:en` (VeloCloud) | "Broadcom sold the VeloCloud line to Arista in 2025" |
| `20494af63ce3fb8e:en` | Baohuo "previously reported by Doctor Web" |
| `1db2acb4ab2e96ad:ua` | comparison with the $1.5 bn Bybit theft of February 2025 |
| `f0992e1c241436c4:ua` | PHP 5.4 released in 2012 |

A further 6 briefs give operational detail not in the source (ports TCP 4343
`690940732ff7fbfe:en`, 8443 `47c9e2c2f127bea1` EN+UA, 1972
`c0863d2cd64d70e9:en`, 5064–5076 `b933b8867a0cffd5` EN+UA). Probably correct
and useful, but unverified.
Older generations add **speculation stated as analysis**: "attackers …
likely identified vulnerable instances within minutes" (`d33a9ec3b29273d0:en`),
"The credential stealer likely targets environment variables, SSH keys…"
(`79b6f0e77988a6a0:en`). Narrative fields: "likely/probably" in 125 EN
briefs, "within hours/days/minutes" in 106.
**Origin:** generation (prompt asks for analysis that "adds information" from
a teaser; no fact sheet to bound it).

### F3. Irrelevant or invented advice — High
- `9406dd2ee53324ce:ua`: a DOU News podcast whose only security item is the
  chapter title "02:00 Злам Binance" became a "Binance breach" brief rated
  Medium, with advice to switch Binance to passkeys and delete API keys.
- `8e48377fa4e2c01a:ua` (hack of the Russian MNS alert app): "Вимагайте
  підтвердження другого адміністратора для кожної push-розсилки у вашій
  системі оповіщення".
- `115437b12ee0299e:ua` (GRU hack of Jared Kushner's iPhone): general readers
  told to enable Lockdown Mode.
- 29 off-topic briefs with advice (F1).
**Origin:** generation (every brief must fill `what_to_do`; no "no action"
outcome) and ingest (digests treated as single incidents).

### F4. EN and UA disagree on severity — High
Severity is chosen separately in each render. **443 of 2,017 bilingual
stories (22.0%)** show a different level in each language: haiku 51.8%, cli-A
37.2%, cli-B 37.0%, cli-C 11.2%. Typical: Low→Medium 161, Medium→High 160. Of
the 121 bilingual stories with a source item, 7 still disagree, e.g.
`76da600891769837` (Sandworm wiper: EN Medium, UA High).
**Origin:** generation architecture (severity should come from the shared
fact sheet, not from each locale).

### F5. Factual drift between languages — High
- `30de94b7338e400a` (pynetdicom): EN says "No vendor fix; maintainer
  unresponsive" and "Do not assume a vendor patch exists yet"; UA says
  "Оновіть pynetdicom до v3.0.4 або новішої". The EN also contradicts itself
  ("pynetdicom >=1.0.0, <3.0.4 affected" implies 3.0.4 is fixed). Severity
  Medium vs High.
- CVE sets differ in **29 pairs (1.4%)**; version-number sets differ in
  **202 pairs (10.0%)**. The latter needs manual triage: many differences are
  legitimate omissions, some are contradictions.
- Analysis present in only one language: **162 pairs (8.0%)** (UA empty 83,
  EN empty 79), e.g. `62af280b86d2c33a`, `690940732ff7fbfe`,
  `0f81648bf5c6b707` (UA empty).
**Origin:** generation (two independent renders with no shared facts).

### F6. Thin Ukrainian-native coverage — High
UA-only stories (Ukrainian outlets: attacks on Ukrainian services, CERT-UA,
local fraud) are the edition's unique value, yet **51.7% of them (215 / 416)
have no analysis**, against 12.7% for the UA side of bilingual stories. In
the current generation UA analysis is empty twice as often as EN (24.1% vs
13.9%). Source teasers from ain.ua (median 169 chars) and dev.ua (≈298) are
short.
**Origin:** ingest (teaser only) and generation.

### F7. Pipeline labels leak into reader text, sometimes attributed to CISA — High
- "Threat score" appears in **22 EN and 5 UA** briefs ("Threat score 14.3,
  informational" in `4eceb1003b08db8e:en`; "Threat score 9/100" in
  `c0f0a626c0d0a328:ua`). Any internal label (threat score, actionability,
  "informational", "recommended_action"): **73 EN, 21 UA**.
- **11 EN briefs attribute our "informational" actionability label to
  CISA**: "CISA's actionability rating is informational"
  (`23544328fc327905:en`), "CISA lists this as informational"
  (`6d35f23fa479f633:en`), "CISA rates this informational"
  (`b230769980bb94d1:en`). CISA publishes no such rating. UA has the same
  pattern, e.g. «CISA класифікує матеріал як інформаційний»
  (`136828a6975ec7a5:ua`).
- Current generation: 0 such leaks in EN, 0 in UA. The problem is in the
  older 94 + 21 briefs that are still live.
**Origin:** generation (labels passed in the prompt); website (renders them).

### F8. Duplicate stories and conflicting dates — High
The «Повітряна тривога» incident is **5 separate UA briefs**, all rated High
(`51db3aa02d6f157a`, `8a50c75c1b7cc336`, `1acc7714f97ae941`,
`75ba357ae93203ae`, `c741ac626ea63cce`). One says the hack became known
"ввечері 2 листопада": itc.ua's own teaser says so, but it was published at
04:39 UTC on 2 November, so the date is impossible; the brief repeated it.
**Origin:** ingest clustering; no date sanity check in generation. Telegram
publishes High items, so duplicates may reach the channel (not verified).

### F9. Vendor webinars and sponsored guides rendered as threat briefs — Medium
At least **10 bilingual stories** are vendor webinars or sponsored content:
`b12df17a52041075`, `874da1a0e0790cca`, `ac4d3b6f654bf5fb`,
`e2767d5bece11992`, `7ca52314a96c2217`, `46c8c5f2acb880df`,
`4913d1691ebd55e4`, `8abca2d5974c3170`, `ebd8326974b7bfdf` ("Picus pitches"),
`3cc3e48c3179ac60` (a CISO guide turned into «Зловмисники використовують нові
вразливості за пʼять днів…»). They take advice slots and severity labels.
**Origin:** ingest (no sponsored-content flag).

### F10. Meta-commentary about the source — Medium (mostly historical)
"Patch status … remain unclear from available reporting", "The source
article provides…", «Текст обривається на умовах застосування»
(`800b7492fcac870c:ua`), «Jерело не називає ані CVE…»
(`b06dad6c3071ec1f:ua`, also mixed-script). EN narrative fields: 196 briefs
(cli-A 27%, cli-B 23%, cli-C 1%, haiku 16%); UA: 83 (cli-C 11). Saying what
is unknown is good; describing the teaser is not.
**Origin:** generation; largely fixed in cli-C.

### F11. English formulas — Medium
- **Banned filler list from the brief: 0 occurrences** of all seven phrases.
  "landscape" 2, "underscores/highlights" 7, "leverage" 32.
- The house tells are different:
  - `short_summary` opens with "<Source> reports" in **1,377 / 2,020 (68.2%)**;
    "<Source> warns" in 305 more.
  - "treat … as" in narrative fields of **396 briefs**; **156 of 1,768
    analysis paragraphs end with a sentence starting "Treat"** ("Treat any…"
    62).
  - `severity_reason` opens "Attackers are…" 147 times; `plain_summary`
    opens "Attackers are"/"Hackers are" 146 times.
  - The appositive gloss formula ("C3RB3R ransomware, software that locks your
    files, is hitting…"; "Rockwell ThinManager, software running factory and
    utility plant screens, has a bug…") opens **74 of 1,242 current
    plain summaries (6.0%)**; 0 before cli-C. "software that" anywhere: 43.
  - "not just X" 104 briefs; "Defenders/organizations/teams should" 125.
**Origin:** generation (prompt examples and few-shot structure).

### F12. English headlines and conventions — Low
- Title Case: Haiku 37 / 115, CLI 1 / 1,905 ("PraisonAI CVE-2026-44338 Auth
  Bypass Exploited Within Hours").
- 132 headlines over 80 characters (6.5%); "flaw" in 425 headlines (21.0%);
  "flaw/bug lets" construction 71.
- Mixed spelling: "organiz-" 169 briefs vs "organis-" 107; "recognise" 85 vs
  "recognize" 21; "behavior" 70 vs "behaviour" 45, while the site declares
  `en-US`.
- Dates in four formats: ISO (161 briefs), "May 17, 2026" (30),
  "30 July 2026" (39), month-day without year (88).
- Passive voice is moderate and stable: 12.8–15.4% of narrative sentences
  per generation.
**Origin:** generation.

### F13. Ukrainian calques from English and slang — Medium
Classic Russianisms are nearly absent: of 20 listed forms, 13 have zero hits
(являтися, приймати участь, на протязі, у відповідності, слідуючий,
співпадати, прийняти міри, вірно, міроприємство, получати, по причині, в той
же час, кидатися в очі); «шляхом», «рахувати», «в якості», «із-за» hits were
checked by hand and are almost all correct uses. The live problems:

| Form | UA briefs | of which cli-C |
|---|---|---|
| «закрити вразливість / діру» | 141 | 107 |
| «у дикій природі» (in the wild) | 104 | 19 |
| «діра/дірка» | 128 | 88 |
| «адмін(и)» | 1,213 (1,312 `affected_users` items start «Адміни») | 813 |
| «вендор» | 215 | 138 |
| «вада» | 239 | 125 |
| «патч*» (acceptable for Reader 2) | 636 | 286 |
| «на предмет» | 47 | 20 |
| «полювати» (hunt) | 49 | 13 |
| «ротувати» (rotate) | 40 | 2 |
| «дозволяє + віддієслівний іменник» | 41 | 7 |
| «різниця патча» (patch diff) | 20 | 16 |
| «інстанс» / «мейнтейнер» / «ендпоінт» / «білд» | 54 / 47 / 24 / 26 | 16 / 19 / 6 / 9 |
| «був/була + -ний» passive | 98 | 70 |
| «-ний + орудний виконавця» | 22 | 12 |
| active participles «-учий/-ючий» | 66 | 25 |
| register slip «гляньте» | 2 | 2 |

Further register slips read in samples: «туди вже залізли»
(`a9e03aba59c7b794`), «на потік» (`2edf45c2ce558056`), «Тейкдауни
інфраструктури рідко вбивають MaaS-родину… Очікуйте спроб ребілду C2»
(`472190b28d242f85`). Bureaucratic «здійснювати» is rare (6 briefs). The
prompt itself lists «шляхом» as the "canonical" Ukrainian form for «путём»
(`templates.py`), which invites the construction this guide bans.
**Origin:** generation; the prompt and `uk_glossary.py` can fix most.

### F14. Ukrainian grammar errors and corrupted words — High (per brief)
- **Mixed-script tokens** (Latin letters inside Ukrainian words) in **27
  briefs**, 12 of them current generation: «вразvillності», «Просканujte»,
  «radше», «Viправлення», «Jерело», «Фoxconn», «ПлayCity».
- Russian letters (ы, э, ъ, ё) in 5 briefs; Russian words («утечка»,
  «необычні», «инфраструктури») in 5 Haiku briefs.
- Haiku UA is the weakest text in the archive: «автентичним користувачам»,
  «критична серійність», «дотримання забувань систем»
  (`321db785508b91ec`); «CIFSwitch видалення локальному зловмисникові
  маніпулювати…» (`e9a38cc4920196ee`); «Скомпрометована розширення»
  (`79b6f0e77988a6a0`); «креденшали», «евакуації компрометованих даних»
  (`6c3dd8f254d63f80`); «флешка зашита в кремній» (factually wrong for a boot
  ROM, `800b7492fcac870c`).
**Origin:** generation (Haiku era); the validator's script check misses
Latin-in-Cyrillic words.

### F15. Inconsistent Ukrainian terminology — Medium
- Attacker noun: зловмисник 915 briefs, хакер 337, атакувальник 228, нападник
  65, атакуючий 14; **70 briefs mix two or more** (e.g. `06c0ec5ab822387d:ua`
  uses зловмисник, нападник and атакувальник).
- «угрупування» (wrong for a group) 120 briefs vs «угруповання» 280; fixed in
  cli-C (0).
- «інфостілер» 24 vs «інфостилер» 15; «ланцюг поставок» 6 vs «ланцюг
  постачання» 88; «аутентифікація» 18 vs «автентифікація» 521; «веб-сайт»
  164 vs «вебсайт» 207; «проект» 11 vs «проєкт» 194.
- CISA agreement: feminine 166, neuter 10, masculine 1.
**Origin:** generation; no glossary in the prompt.

### F16. English terms left inline in Ukrainian — Medium
«zero-day» in 97 UA briefs (244 occurrences), «як zero-day» construction 21
(32), «ransomware» 119 (274), «PoC» 285, «IOC/IoC» 415 (mostly old: cli-C 23).
**86 UA headlines** contain zero-day, ransomware, PoC, exploit, infostealer,
backdoor or phishing in Latin.
**Origin:** generation.

### F17. Ukrainian typography — Low
- Apostrophe in Cyrillic words: U+0027 in 1,317 briefs, U+02BC in 94, U+2019
  in 1; 19 briefs mix two. The validator used to reject U+02BC (4 failures in
  `quality_metrics.json`); fixed.
- ASCII double quotes in UA prose: 81 briefs; ASCII single quotes around
  commands: 215.
- Spaced hyphen as dash: 16 briefs; ranges with hyphen («2018-2021»): 15.
- Em dashes: 1,276 UA briefs vs 6 of 1,242 current EN briefs; the EN prompt
  effectively bans them, the UA prompt does not.
- Euphony: «вразлив-» after a consonant in **260 briefs** (342 cases) and
  sentence-initial «Вразлив-» in 222, both caused by `uk_glossary.py`, which
  rewrites every «уразлив» to «вразлив». Other euphony slips are rare: «і»
  between vowels 55 briefs, «в» between consonants 3.
- ISO dates in UA prose 50 briefs; «$» 73 vs «доларів» 31.
**Origin:** generation and normalizer.

### F18. Headline and opening repetition (UA) — Low
«X повідомляє:» opens 1,079 UA `short_summary` (44.3%); `severity_reason`
opens «Атаки вже…» 114 times; «Якщо … вас це не стосується» appears in 481
of 1,268 non-empty `am_i_affected` lists (EN equivalent 235 of 1,121).
200 UA headlines use a colon; 125 exceed 90 characters; 45 begin with a
verbless «Вразливість…/Критична вразливість…»; 50 begin «Хакери».
**Origin:** generation.

### F19. Editorial value: what works — for calibration
Current-generation briefs (cli-C) are mostly natural in both languages and
add value beyond paraphrase: menu paths for checking exposure
(`0f81648bf5c6b707` DSM steps), the distinction between takedown and cleanup
(`eae2a3c7c621fbaa` Amadey), why file-integrity monitoring would miss a
poisoned third-party script (`02aa5589116e9160` Convertr), and Ukraine-specific
advice (`76da600891769837:ua` adds reporting to CERT-UA). The UA renders of
`51db3aa02d6f157a` and `4dec087390da4de4` read as original Ukrainian
journalism. The problems above are concentrated in older generations, in
UA-only stories, and in the analysis paragraph.

## 4. Where the problems originate

| Finding | Ingest / ranking | Generation (prompt, model) | Normalizer / validator | Website | Telegram |
|---|---|---|---|---|---|
| F1 off-topic | relevance filter | no decline path | — | publishes all | Low items not posted |
| F2 background, speculation | teaser only | prompt asks for added analysis | no fact check | — | — |
| F3 irrelevant advice | digests as incidents | mandatory `what_to_do` | — | — | — |
| F4 severity mismatch | — | per-locale severity | — | shows each | may post one language only |
| F5 factual drift | — | independent renders | protected tokens not compared | — | — |
| F6 thin UA-only | short teasers | — | — | — | — |
| F7 label leakage | — | labels in prompt | no check | renders quick facts verbatim | — |
| F8 duplicates, dates | clustering | no date check | — | shows all 5 | risk, not verified |
| F9 sponsored | no flag | — | — | — | — |
| F13–F18 language | — | prompt, model | `уразлив→вразлив`; no mixed-script check | commands not shown as code | — |

The website's own editorial issues, from the baseline audit and confirmed
here: there is no "held / needs review" state, so anything cached is public,
and the article page repeats the same fact in five boxes. Both make
generation problems more visible.

## 5. Recommendations (prioritised)

**P0 (stop publishing wrong content)**
1. Add a `not_security_news` outcome to generation and a reject path; hide
   the 29 F1 briefs now.
2. Remove internal labels from the prompt text the model may echo; strip
   "Threat score …" and the "CISA … informational" sentences from the 94 + 21
   live briefs (F7).
3. Decide severity once per story (fact sheet), render both languages from it
   (F4).
4. Treat podcast and newsletter digests as digests, or drop them (F3).

**P1 (accuracy)**
5. Introduce the shared fact sheet (baseline audit §6): allowed facts, CVEs,
   versions, dates, numbers; validate both renders against it (F2, F5). Any
   historical claim must cite a reference.
6. Allow `what_to_do`/`detail_body` to be empty when the source gives nothing
   to add; reward "what is unknown" sentences (F2, F3).
7. Date sanity check: event date after source publication time → flag (F8).
8. Cluster duplicates in ingest (F8); flag sponsored/webinar content (F9).
9. Route Haiku-era briefs and the 27 mixed-script briefs to re-render or
   review (F14).

**P2 (language)**
10. Put the glossary's "avoid" column and the style guide's §14–§17 tables
    into the UA prompt and the validator (F13, F15, F16); fix the prompt's
    «шляхом» line.
11. Replace the blind `уразлив→вразлив` rule with a euphony-aware rule or
    drop it (F17).
12. Add a mixed-script word check (Latin and Cyrillic letters in one token)
    to the validator (F14).
13. Normalise apostrophes to U+02BC, quotes to «», ranges to en dash; search
    must fold apostrophe variants (F17).
14. EN: vary attribution openings, retire the appositive gloss formula and the
    "Treat …" closer; fix spelling to US English; one date format (F11, F12).

**P3 (site)**
15. Editor review queue for flagged UA briefs; show commands as code.

## 6. Benchmark set (16 fingerprints)

For before/after comparison. "src" = source item is in `data/items.json`;
the two without one need their item pulled from the main store before
re-rendering.

**EN-only or bilingual (8)**

| # | Fingerprint | src | Why |
|---|---|---|---|
| 1 | `0f81648bf5c6b707` | yes | Synology/C3RB3R: unattributed Confluence and "no free decryptor" claims; gloss formula; UA analysis empty |
| 2 | `62af280b86d2c33a` | yes | Nefilim/Hive sentence: heaviest unattributed background in EN; UA analysis empty |
| 3 | `f635e51b46992649` | yes | Ivanti KEV from a CISA boilerplate notice: inferred "fix should exist", old CVEs; tests a fact-sheet bound |
| 4 | `68f2c8a7a2b64fb9` | yes | BlackX bootkit: strong brief in both languages with one unattributed claim; checks fixes don't flatten quality |
| 5 | `02aa5589116e9160` | yes | Convertr skimmer: positive control, natural EN and UA |
| 6 | `76da600891769837` | yes | Sandworm/UAC-0099 wiper in Ukraine: severity mismatch (EN Medium, UA High); Ukrainian relevance |
| 7 | `690940732ff7fbfe` | yes | HPE ArubaOS: unverified port detail and exploit speculation in EN; «закрила» calque; UA analysis empty |
| 8 | `30de94b7338e400a` | no | pynetdicom: EN/UA contradict each other on fix availability; severity mismatch |

**UA (8)**

| # | Fingerprint | src | Why |
|---|---|---|---|
| 9 | `9406dd2ee53324ce` | yes | DOU podcast turned into a Binance breach with account advice |
| 10 | `8e48377fa4e2c01a` | yes | Russian MNS app hack with advice for "your alert system" |
| 11 | `51db3aa02d6f157a` | yes | «Повітряна тривога»: good native Ukrainian; one of a 5-brief duplicate cluster |
| 12 | `1acc7714f97ae941` | yes | Same incident: impossible event date repeated from source; tests date check and dedup |
| 13 | `526db699eaf589d6` | yes | Node.js from dev.ua: «закрили вразливості» headline, empty analysis, broken conditional |
| 14 | `4dec087390da4de4` | yes | Mobilisation-deferment rules: off-topic but well written; tests the relevance gate |
| 15 | `115437b12ee0299e` | yes | Kushner iPhone: irrelevant Lockdown Mode advice, «Злам виконало ГРУ», empty analysis |
| 16 | `321db785508b91ec` | no | Gogs, Haiku UA: worst-case grammar («автентичним», «серійність»); tests re-render floor |

## 7. Reproducing the counts

Scripts used for this audit are not committed (they live in the session
scratchpad). Each count above names its field and pattern; the patterns are
listed in the style guide tables (§14–§17) and can be re-run with
`/home/cax/cax/venv/bin/python -I` over `data/threat_posts.json`.
