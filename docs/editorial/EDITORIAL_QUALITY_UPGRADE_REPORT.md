# Editorial quality and UX upgrade report

Branch `feature/editorial-quality-ux` (from `redesign/cti-platform` @ `676d800`), 4 November 2026. **Not deployed.**

## Summary

CyberAlertX now keeps **evidence apart from severity**. A deterministic layer
(`cyberalertx/pipeline/evidence.py`) reads only the source title, feed excerpt
and byline. It decides:
- whether exploitation is confirmed, attacks were observed, or only suspicious
  activity was reported;
- whether a data exposure is confirmed;
- the campaign status;
- whether the source is sponsored;
- what the reporting leaves open.

The labels, filters, article page and quality gate all use it. The public site
no longer mentions AI authorship. The article page is organised around reader
questions, and the generic "Background" block is gone. Both regression cases
(Google Calendar AitM, mSecure) now render what the sources support.

Costs and architecture:
- **No AI calls were added.** The prompt rules are no longer than before
  (EN −39, UA −5 characters).
- Fact sheets stay off, and the provider and publication engine are unchanged.

## 1. Initial audit

### Method

1. **Live labels:** 26 articles, read-only from the public API, covering 11
   categories. 21 are EN+UA and 5 are UA-only.
2. **Ground truth:** the full original reports for the two regression cases.
3. **Mechanical checks on every article:**
   - the evidence assessment, compared with the published "exploited" flag and
     "who should care" label;
   - the new unsupported-claim gate;
   - the Ukrainian calque and terminology checker;
   - whether the generic Background block was shown.
4. **Manual reading:** Case A and Case B in full, and the flagged items.

### Main weaknesses found

1. **Action priority was published as evidence.** `signals.active_exploitation`
   was true whenever actionability was `urgent_action`. The mSecure vendor
   warning about "suspicious activity" was therefore labelled "Exploited in
   attacks" and "Active exploitation". Across the archive, 3 of the 12 old
   "exploited" flags had no exploitation in the source. The old phrase list also
   missed CISA KEV additions and "active exploitation observed": 24 true cases
   were unlabelled. On the 200-item archive the old flag fired 12 times and
   the new rule 33 times; 9 overlap.
2. **The audience was mislabelled.**
   - Every phishing story was tagged as for everyday users by category alone,
     including Case A, which concerns corporate Google Workspace sessions.
   - Stories matching nothing got the catch-all "Cybersecurity professionals":
     11 of 26 in the sample, including a consumer password manager.
3. **A generic Background block appeared on 22 of 26 articles.** It is
   per-category template text. For Case A it described lookalike pages
   capturing passwords and "everyone with an email address", which is not how
   the reverse-proxy session theft worked.
4. **There was no notion of "unknown".** The page had nowhere to say that the
   reporting does not establish exposure, scope or campaign end. Briefs had
   nowhere to signal it either.
5. **AI authorship was stated publicly** on 42 of 42 checked page loads (footer
   and method text, article attribution), in both languages.
6. **Sponsored research was not disclosed.** The BleepingComputer Case A article
   is "Sponsored and written by Material Security". The ingest dropped the feed
   author, so the brief could not know.
7. **Ukrainian terminology:** 13 of 26 UA editions had flagged terms: colloquial
   «адміни», the calque «атакувальник», and «закрила вразливості». Case A UA
   also used «в обхід MFA», «MFA обходять», «захоплювали робочі облікові
   записи» and «довірені переадресації».
8. **Recommendations repeated themselves.** Advice could appear in several
   lists, and in "Key facts".
9. **The source excerpt is short** (median 377 characters). Whatever the
   excerpt does not say, the brief cannot know. The fix is to label gaps, not to
   fetch more text, which would add cost.

### Articles reviewed

| # | Category | Ed. | Article (id) | Published labels | Now (evidence · who) | Gate | UA terms flagged |
|---|---|---|---|---|---|---|---|
| 1 | phishing | en+ua | Fake Google Calendar invites steal work Google logins despite two-step (`646c23c0`) | not exploited · Everyday internet users | attacks observed, campaign disrupted · Organisations and their IT teams | — | — |
| 2 | other | en+ua | mSecure password manager users told to replace saved passwords and pas (`e357dd7a`) | exploited · Cybersecurity professionals | suspected, exposure not confirmed · — | — | — |
| 3 | vulnerability | en+ua | Barracuda devices can be fully taken over without a password (`5350cf64`) | not exploited · Cybersecurity professionals | not reported · — | — | Адміни |
| 4 | vulnerability | en+ua | cPGuard security tool pushed a backdoor to its own customers' Linux se (`c3e615c4`) | not exploited · Linux administrators | not reported · Linux administrators | compromise (en) | Адміни |
| 5 | vulnerability | en+ua | Barracuda customers told to patch two bugs that give full device contr (`7a78f5e7`) | not exploited · Cybersecurity professionals | not reported · — | — | Адміни, атакувальнику |
| 6 | exploit | en+ua | Russia-linked APT29 hid phone exploits in a Ukrainian website analytic (`f4b7ff86`) | not exploited · Android users | attacks observed, campaign unknown · Android users | — | — |
| 7 | exploit | en+ua | Russian-linked hackers break into unpatched iPhones and Android phones (`e3fd45fd`) | not exploited · Android users | attacks observed, campaign unknown · Android users | — | — |
| 8 | zero-day | en+ua | Ivanti Connect Secure gateways attacked for at least a month before fi (`5ff3e493`) | not exploited · Cybersecurity professionals | attacks observed, campaign unknown · — | — | Адміни, закрила ще дві вразливості |
| 9 | zero-day | en+ua | Cisco ASA and FTD firewalls with SSL VPN are being knocked offline in  (`4665f17a`) | not exploited · IT administrators | confirmed · IT administrators | — | Адміни |
| 10 | malware | ua | Шкідливі програми WardenStealer та Aoki крадуть акаунти ChatGPT, Claud (`d9e95edf`) | not exploited · Cybersecurity professionals | not reported, exposure confirmed, campaign unknown · Organisations and their IT teams | — | — |
| 11 | malware | en+ua | cPGuard security tool's own updates planted a backdoor on servers (`e3626c78`) | not exploited · Cybersecurity professionals | attacks observed, exposure confirmed, campaign unknown · — | — | Адміни |
| 12 | malware | ua | Шкідник VOLTA-AUTODOXER краде дані з комп'ютерів Windows і доручає Cla (`de1cf247`) | not exploited · Windows users | not reported, campaign unknown · Windows users | — | Адміни |
| 13 | ransomware | en+ua | 3AM ransomware locks most computers on a UK school network (`4fc8c8dd`) | not exploited · Cybersecurity professionals | attacks observed, campaign unknown · — | — | адміни |
| 14 | ransomware | en+ua | Synology NAS owners urged to update now amid C3RB3R ransomware surge (`0f81648b`) | not exploited · Cybersecurity professionals | attacks observed, campaign unknown · — | — | Адміни, нападника |
| 15 | phishing | en+ua | A tampered Homebrew install and fake recruiters cost Binance $6.43 bil (`62e23c78`) | not exploited · Cryptocurrency users | attacks observed, campaign unknown · Cryptocurrency users | compromise (ua) | — |
| 16 | phishing | en+ua | Stolen AI service keys are running up company cloud bills to $1 millio (`c5631e1f`) | not exploited · Everyday internet users | not reported, campaign unknown · Private internet users | — | Адміни |
| 17 | scam | en+ua | European police take down servers behind fake investment trading websi (`89f0cc01`) | not exploited · Everyday internet users | attacks observed, campaign disrupted · Private internet users | — | — |
| 18 | breach | en+ua | DreamHost customers' FTP passwords and webmail sessions stolen in brea (`622646b5`) | not exploited · Enterprise IT teams | not reported, exposure confirmed · Organisations and their IT teams | — | — |
| 19 | breach | en+ua | WorkOS sales app breach exposes business contacts and customer convers (`cf2ea752`) | not exploited · Enterprise IT teams | attacks observed, exposure confirmed, campaign unknown · Organisations and their IT teams | — | Атакувальник |
| 20 | breach | en+ua | Chainstack break-in exposes customer data and scrambled account passwo (`49acf980`) | not exploited · Enterprise IT teams | attacks observed, exposure confirmed, campaign unknown · Organisations and their IT teams | — | — |
| 21 | data leak | ua | Через злам панелі операторів «Повітряна тривога» розіслала фейкові спо (`54f3d5a6`) | not exploited · Telegram users | not reported, exposure confirmed · Telegram users | — | — |
| 22 | other | en+ua | Hackers changed fridge settings holding blood supplies at three French (`324db880`) | not exploited · Cybersecurity professionals | attacks observed, campaign unknown · — | — | — |
| 23 | other | ua | NoName057(16) і Z-Pentest Alliance заявили про атаки на холодильники є (`7699be6b`) | not exploited · Cybersecurity professionals | not reported · — | — | Адміни |
| 24 | other | ua | Через фальшиві співбесіди хакери вивели з Binance 6,34 млрд доларів (`3747cf72`) | not exploited · Cryptocurrency users | not reported · Cryptocurrency users | compromise (ua) | атакувальники |
| 25 | botnet | en+ua | Google cuts off botnet of 1.3 million Android TV boxes renting home in (`ee5bbf62`) | not exploited · Android users | not reported, campaign disrupted · Android users | — | — |
| 26 | botnet | en+ua | Android spyware, hijacked Linux devices and sign-in code scams top thi (`a3562df3`) | not exploited · Android users | attacks observed, exposure confirmed, campaign unknown · Android users | — | — |


Legend:
- **"Published labels"** are what readers saw on 4 Nov (exploited flag · who
  should care).
- **"Now"** is the feature branch on the same data.
- **"Gate"** shows unsupported claims in the existing briefs (these go to the
  editor queue).
- **"UA terms flagged"** come from `uk_glossary`.

## 2. Mandatory regression cases

### Case A: Google Calendar phishing (`646c23c08481b93b`)

Source-supported facts (BleepingComputer, "Sponsored and written by Material
Security"):
- **Lure:** Calendar invites, often from organisations the recipient had
  corresponded with (8,570 compromised sender addresses). Links ran through
  Google's own `/url` redirector, share.google and Drive.
- **Access:** a live reverse proxy in front of the genuine Google sign-in page
  relayed passwords, SMS and authenticator codes and number matching, and
  captured the session.
- **Reach:** a live session reaches Gmail, Drive and OAuth grants.
- **Status:** activity "appears to have dispersed. The campaign looks finished.
  That is a status update, not a verdict." An unactivated Microsoft 365 branch
  exists.

| | Before (live) | Now |
|---|---|---|
| Evidence | — | Attacks observed · Attack infrastructure taken down |
| Who should care | Everyday internet users | Organisations and their IT teams |
| Background | Generic: lookalike page, "everyone with an email address" | Removed |
| Unknowns | — | "Activity has slowed or infrastructure was taken down, but that does not confirm the campaign has ended." |
| Sponsored | Not shown | Shown under Sources when the feed byline says "Sponsored by …" (captured from now on) |

### Case B: mSecure (`e357dd7a35d8f16c`)

Source-supported facts (The Hacker News):
- mSeven emailed customers about suspicious activity linked to the app.
- The steps it offers are "possibilities".
- The email does not say what happened, whether stored data was exposed, which
  systems were involved, or when it happened.

| | Before (live) | Now |
|---|---|---|
| Evidence | Exploited in attacks · "Active exploitation" | Suspicious activity reported · Data exposure not confirmed |
| Who should care | Cybersecurity professionals | (none; the brief's own "mSecure customers" list stands) |
| Unknowns | — | "Whether any data was exposed has not been confirmed." |
| Gate | — | Flags "all saved secrets were stolen" (tested); accepts "If the vault data was accessed, …" |

### Proposed archive corrections (not applied)

**Case A, EN**
- *Current short_summary:* "BleepingComputer reports a Google Calendar phishing wave that hijacked corporate Google sessions past MFA. Material Security's Operation CloudFire helped take down nearly 900 attacker domains."
- *Proposed:* "Attackers sent Google Calendar invites that led to a proxy in front of the real Google sign-in page and stole signed-in work sessions despite two-step verification, according to Material Security, which sponsored the BleepingComputer report. It says activity appears to have dispersed."
- *Proposed why_it_matters:* "A stolen session opens the victim's work Gmail, Drive and the ability to grant OAuth access, and passing the two-step check is exactly what hands it over."
- *Proposed actions, employees:* report unexpected invites that ask you to sign in to IT; sign in only by typing `accounts.google.com`.
- *Proposed actions, admins:* review Workspace audit logs for unfamiliar sessions and OAuth grants; be ready to revoke sessions, contain OAuth grants and reset accounts within the hour (the source's own benchmark).
- *Reason:* the mechanism (AitM relay), the audience, the sponsorship and the campaign status. The current text says "past MFA" without explaining why.

**Case A, UA**
- *Current quick_facts:* «Довірені переадресації ведуть на фальшиві сторінки входу», «Мета: корпоративні сесії Google, MFA обходять».
- *Proposed short_summary:* «Через запрошення в Google Calendar зловмисники вели працівників на проміжний сервер перед справжньою сторінкою входу Google і перехоплювали вже відкриту робочу сесію попри багатофакторну автентифікацію. Про це пише BleepingComputer у спонсорованому матеріалі Material Security; за її даними, активність, схоже, спала.»
- *Proposed quick_facts:* «Посилання спершу вело через сервіси Google, а потім перенаправляло на сторінку зловмисників», «Пароль і код підтвердження передавалися Google в реальному часі», «Material Security заблокувала майже 900 доменів за місяць».
- *Reason:* the calques «MFA обходять» and «довірені переадресації», the missing explanation of why МФА did not help, and the sponsorship.

**Case B, EN**
- *Current why_it_matters:* "Anyone holding mSecure vault contents could sign in to email, banking and work accounts, then use email password resets to lock the real owner out."
- *Proposed:* "If the vault data was accessed, every stored login, 2FA code and passkey would be exposed at once. mSeven has not said whether that happened, so its advice is a precaution."
- *Proposed short_summary:* "mSeven Software emailed mSecure customers about suspicious activity linked to the app and suggested changing passwords, resetting 2FA and removing passkeys. The email does not say what happened or whether stored data was exposed, The Hacker News reports."
- *Reason:* the current text implies that someone holds the vault contents. The source does not say so.

**Case B, UA**
- *Current why_it_matters:* «Якщо сховище mSecure прочитали, той, хто це зробив, має паролі, коди 2FA і passkeys до всіх збережених акаунтів одразу…» (already conditional, so kept in substance).
- *Proposed short_summary:* «mSeven Software, розробник менеджера паролів mSecure, попередила клієнтів про підозрілу активність, повʼязану із застосунком, і радить змінити паролі, скинути 2FA та видалити ключі доступу (passkeys). Що саме сталося і чи до даних отримали доступ, компанія не повідомляє.»
- *Reason:* to attribute the advice to the vendor and name the gap.

## 3. Article structure

The page follows reader questions, and empty blocks are hidden:
1. headline;
2. plain lead;
3. **evidence strip** and a **What to do ↓** anchor, at every width;
4. **What happened**, with "Why it matters";
5. **Key details**, only facts not already in the prose;
6. **Who is affected**, with "How to check";
7. **What to do**, with "If you're already affected" and "What to avoid". Each
   step appears once: later lists drop exact or contained repeats;
8. **What is not yet known**;
9. **Sources**: "Source: X. Read the original report for full context." (UA:
   «Джерело: X. В оригінальній публікації — повний контекст і подробиці.»), the
   author from the feed byline, the sponsored disclosure, other coverage and
   advisories;
10. Share, **Was this brief useful?**, and a separate **Report a problem**
    (factual error, outdated information, translation problem).

The category-specific coverage is in ENGLISH_STYLE_GUIDE §9.1.

## 4. Pipeline and validation changes (no added AI calls)

| Area | Change |
|---|---|
| `pipeline/evidence.py` (new) | Exploitation (`confirmed` / `attacks_observed` / `suspected` / `not_reported`), campaign (`active` / `declined` / `disrupted` / `unknown`), compromise (`confirmed` / `not_confirmed`), sponsorship, unknown codes. Negations and statistics never confirm. A comeback beats a takedown. |
| `pipeline/signals.py` | `active_exploitation` = evidence `confirmed` (no longer `urgent_action`). Data-exposure impact is off when exposure is unconfirmed. Workplace cues raise `enterprise_risk`. Labels: "Exploitation confirmed", "Private internet users", "Organisations and their IT teams"; UA «Експлуатацію підтверджено», «Приватні користувачі», «Доступ до поштового облікового запису». The "Cybersecurity professionals" fallback is removed. |
| `pipeline/audience.py` | Workplace vocabulary for `enterprise`. A category-only `normal_users` is dropped for workplace stories. Re-derived at render time, so archived items show current labels; stored items are not modified. 2 of 200 archive items change. |
| `models.py`, `sources/rss.py` | `NewsItem.byline` from the feed author, used for attribution and sponsorship. Backward-compatible. |
| `api/app.py` | Payload adds `evidence` and `source_byline`. |
| `ai/templates.py` | FACTS AND SOURCING rewritten (EN/UA): evidence before conclusions without a fact sheet, vendor advice ≠ proof, conditional wording, attribution and sponsorship, workplace audience and who-does-what, gaps not filled. Ban lists condensed so the rules are not longer. The byline goes into SOURCE METADATA when present. |
| `ai/scorecard.py` | Evidence gate: `unsupported_exploitation`, `unsupported_compromise`, `campaign_status_conflict`, `ai_authorship` (hard, routed to review as "evidence: …"); `duplicate_recommendation` (minor). Hedged claims are ignored. It never rejects or retries, so it cannot add cost. 7 of 256 archive editions flagged (3 exploitation, 4 compromise). |
| `ai/uk_glossary.py` | Seven calque rules (flag only, no auto-replace). |
| `ai/rule_based.py` | Fallback audience labels updated. |
| `feedback.py`, admin | New reasons `outdated` and `translation`. |

## 5. UI changes

- **Homepage:**
  - headline "Cyber threat briefing" / «Огляд кіберзагроз», with the brief's
    subtitle;
  - lead story: evidence status beside severity, the specific severity reason,
    and the first "What to do" step;
  - «Інші важливі кіберподії» / "Other significant stories".
- **Feed marks:** severity, plus at most one evidence status (confirmed, attacks
  observed, suspicious activity, or confirmed exposure). "Exploited" can no
  longer appear without evidence.
- **Filters and overview:** "Exploitation confirmed" / «Експлуатацію
  підтверджено»; "Private users" / «Приватним користувачам».
- **Article:** as in §3, plus evidence rows in the side column.
- **Footer:** the cyan field and Aperture wordmark stay; the wordmark is scaled
  from 15.2cqw to min(9cqw, 7.5rem), with less padding. New footer text without
  AI.
- **Overflow fixes:** footer email at 320 px; header at 1024 px (the Telegram
  link moves to the menu and footer between `lg` and `xl`); the UA display
  heading hyphenates at 1024 px. All were pre-existing except the heading.

## 6. Responsive, accessibility, SEO and RSS verification

- **Browser check:** EN/UA homepage and both regression articles, at 320, 375,
  390, 768, 1024, 1440 and 1920 px: 42 loads per site.

  | Check | Live site | Feature branch |
  |---|---|---|
  | Overflow | 12 (all at 320/1024 px) | 0 |
  | Clipped headings | 0 | 0 |
  | AI-authorship text | 42 of 42 | 0 |
  | Broken images | 0 | 0 |
  | Console errors | 0 | 0 |
  | Wrong `lang` | 0 | 0 |
  | Exactly one H1 per page | yes | yes |
  | Keyboard focus visible | yes | yes |

- **Article reading width:** 612 px at 1440.
- **SEO and feeds:** localized OG titles; `og:locale` en_US / uk_UA; canonical
  URLs unchanged; `/en/feed.xml`, `/ua/feed.xml` and `/sitemap.xml` return 200.
  URL structures are unchanged.
- **Playwright** (existing suite plus the new `tests/e2e/editorial.spec.ts`):
  53 passed, 3 skipped, 2 failed. The failures are the known environmental
  `/healthz` test (O23: no nginx locally).
- **Screenshots:** before/after at 390 and 1440 px, plus section close-ups.
  Kept locally, not committed.

## 7. Tests

| Suite | Result |
|---|---|
| pytest (no Postgres) | 1399 passed, 13 skipped |
| pytest with a disposable PG 17 | 1419 passed, 1 skipped |
| New `tests/test_editorial_evidence.py` | 22 passed: Cases A/B, statistics and negation, KEV, campaign wording, breach and traced theft, attacks observed for exploit/zero-day, AI authorship vs news about AI, duplicates, prompt rules, a prompt-size cost guard, the real-feedparser byline |
| Updated tests | 7 assertions moved to the new semantics: urgent ≠ exploited, labels, the silent fallback |
| mypy (strict, `cyberalertx`) | clean, 120 files |
| tsc | clean |
| next build | success |
| Playwright | 53 passed, 2 environmental failures, 3 skipped |

## 8. Cost and performance

- **AI calls per story:** unchanged.
- **Prompt rules:** EN 30,794 → 30,755 characters, UA 34,388 → 34,383. One line
  is added (about 40 characters) only when a feed provides a byline. The cost
  guard test fails if the rules grow.
- **Output fields:** unchanged.
- **Render-time work:** evidence and audience re-derivation are pure regex
  passes over about 400 characters per item, in microseconds. Feed response
  times are unaffected.

## 9. Remaining issues

1. **Existing briefs are unchanged.** The new prompt applies to newly generated
   posts. Archive corrections above are proposals only.
2. **Sponsorship needs the byline,** captured from now on. It's unverified
   against BleepingComputer's live feed, which returns 403 to a direct request
   (production fetches through its RSS proxy). Items ingested before carry no
   byline.
3. **Detection is pattern-based** and conservative. Ambiguous wording stays
   "not reported" or "not confirmed".
4. **Some stories now show no audience label.** When nothing matches, no label
   is shown rather than a wrong one. Enterprise appliances (Barracuda, Ivanti)
   would benefit from platform-based audience rules.
5. **Category overlap is not resolved here.** Vulnerability / exploit /
   zero-day, and breach vs data leak, remain separate categories; the filters
   follow them.
6. **AI briefs are not rewritten automatically.** An unsupported claim in a new
   brief is flagged for the editor, not rewritten or hidden, because `flag`
   mode keeps it visible. Turning on `hold` for evidence issues is a separate
   decision.

## 10. Production deployment recommendations

1. Ship this branch together with the O27 read-path fix and the O28 fixes in
   **one release**, through the Stage C procedure (new release directory,
   verify, switch). No migration is needed: the new fields are JSON-only and
   optional.
2. After deploying, watch `/admin/review` for "evidence:" reasons for a week.
   Then decide whether evidence issues should hold posts.
3. Apply the Case A and Case B corrections through the review workflow, as a
   separately approved step.
4. Verify byline capture on the next BleepingComputer sponsored post.

## 11. Evidence hardening (5 Nov 2026)

Branch `feature/o27-api-latency`. Labels: **[tested]** = isolated copy of
production data; **[assumption]** = not proven here. Nothing is deployed.

### What was over-broad

| Pattern | Problem | Fix |
|---|---|---|
| `\bcampaign\b` in attacks-observed | a topic word: "a campaign could target users" counted as observed attacks | needs an action verb (`campaign targets / delivers / infects …`) or an observer (`observed / tracked / uncovered … campaign`); UA `кампані…` likewise |
| `\bdata breach\b` in compromise-confirmed | "how to prevent a data breach", "a possible data breach" counted as confirmed exposure | needs someone suffering/disclosing/confirming/linking one, or the breach hitting/affecting/exposing someone, or a fine/settlement for one |
| `targeted`, `targeting`, `infected`, `hijacked`, `hacked` | adjectives in forecasts ("targeted phishing could hit …") | the whole clause is checked for hedges |
| KEV | only "KEV catalog" matched | `KEV` alone, negation-aware ("not listed in KEV" does not confirm) |
| comeback wording | "returned", "resumed", "back online", "rebuilt" missing; "could return" counted | added; forecasts excluded |

### New rule: a hit counts only when its clause asserts it

`_asserted()` checks each hit's own clause (it stops at sentence ends and at
"but", ", and", ", with", "however", UA «але», «проте» …):

* **hedge** before or inside the hit: could, may (lower-case), might, would,
  can, potential(ly), possible, if, unless, whether, risk, prevent, avoid,
  protect/guard/defend against, how to, learn, hypothetical, simulated; UA
  може, можуть, якщо, потенційно, запобігти, уникнути, «для викрадення …»;
* **capability** in the few words right before the hit: lets, allows,
  enables, designed / built / able / intended / aims / tries to, capable of.
  Only the nearby words count, so "the bug allows RCE, with the flaw actively
  exploited" still confirms;
* **negation**: no, not, never, none, nothing, without, denied, n't; UA не, ні,
  без, немає, жодних;
* **statistics** (exploitation only): %, per cent, "number/share of",
  rose/fell by;
* **non-event formats**: webinar, CTF, podcast.

The brief-side check (`scorecard._asserts`) now also ignores denials ("no
observed abuse in the wild", «Даних не викрадено») and attributed claims
("the gang claims it stole", «заявляють, що викрали»), which a brief is
supposed to write.

Source-side wordings added after reviewing every changed label: present-tense
headlines ("Hackers Use …", "APT Deploys …", "Lazarus Exploits Windows
Zero-Day"), victim counts ("compromises 600 npm packages"), "malicious/fake X
pushes/steals …", "exploited in [ongoing RCE] attacks", "exploited to …",
"under active use", "attacks exploiting", "observed exploiting", "malicious
actors are exploiting", "theft of … assets", "vaults downloaded", "API keys
were exposed", UA «вкрав», «викрадені», «отримали несанкціонований доступ до».

### The nine required cases [tested]

| # | Text | Result |
|---|---|---|
| 1 | Researchers warn that a phishing campaign could target users. | not reported (was attacks observed) |
| 2 | The campaign was investigated, but no attacks were confirmed. | not reported (was attacks observed) |
| 3 | How organizations can prevent a data breach. | no compromise (was confirmed) |
| 4 | A company is investigating a possible data breach. | suspected; exposure not confirmed |
| 5 | Attackers stole customer records. | compromise confirmed |
| 6 | The vulnerability is listed in CISA KEV. | exploitation confirmed (was not reported) |
| 7 | The flaw could be exploited. | not reported; gap "exploitation unconfirmed" |
| 8 | The campaign was disrupted and later resumed. | active (was disrupted) |
| 9 | The campaign was disrupted, but no evidence of its end is available. | disrupted; gap "campaign end unconfirmed" |

`tests/test_evidence_adversarial.py`: the nine cases plus 33 boundary cases
(real headlines from the archive, UA hedges and negation). Existing
`test_editorial_evidence.py` (22) unchanged and passing.

### Effect on stored data [tested]

On the 2,811 source items in the Stage C Postgres snapshot (title + excerpt):

| Label | Before | After | Changed |
|---|---|---|---|
| exploitation confirmed / attacks observed / suspected / not reported | 437 / 517 / 21 / 1836 | 472 / 549 / 22 / 1768 | 200 items |
| compromise confirmed / not confirmed | 435 / 24 | 421 / 24 | 88 items |
| campaign active / disrupted / unknown | 30 / 59 / 920 | 36 / 58 / 923 | 63 items |

Every changed label was listed and read. Downgrades are topics, forecasts,
capabilities ("kit built to steal"), claims ("data breach claims"), webinars
and patch notes. Upgrades are explicit events the old patterns missed
("zero-day exploited in attacks", "data breach affects 13,000 customers").
The 200 items currently in `items.json`: 5 / 3 / 11 changes.

### Evidence gate: flag or hold? [tested]

The gate was run on all 4,498 stored editions with a source item:

| | Hard evidence flags |
|---|---|
| Before this change | 144 (82 exploitation, 53 compromise, 9 AI authorship) |
| After | 58 (21 exploitation, 28 compromise, 9 AI authorship), 1.3 % of editions |

A random sample of 25 flags before the last refinements had **about 5 true
overstatements (~20 % precision)**. Most false flags come from the source
side: the excerpt is a 1–3 sentence teaser, and the brief legitimately uses
the full article or idiomatic wording ("in the wild" for released code). All
58 currently have status `auto`, because stored editions are not re-scored.

**Recommendation: keep `flag` (the default; production sets no
`CYBERALERTX_REVIEW_MODE`).** `hold` would hide about 1 in 75 new briefs, and
most of them wrongly. Revisit `hold` for evidence reasons only after:
1. a week of `/admin/review` data on new briefs shows a true-positive rate of
   at least 70 % for `unsupported_exploitation` and `unsupported_compromise`;
2. the gate compares against the same text the generator saw (the full
   article, if it ever gets it), not only the feed excerpt.

`ai_authorship` is precise (self-referential wording only) and could hold on
its own; it is rare (9 archived editions). Review mode was not changed.

### Limits

* Pattern-based. It is conservative by design: under-claiming is preferred.
* Past exploitation still counts ("was exploited in the wild in 2019"); the
  brief must date it. Only hedged or negated wording is excluded.
* Evidence is computed when read, so after deployment the API shows the new
  labels for the whole archive at once (no data migration). Other consumers of
  `assess` (via `signals.active_exploitation`): the scorecard (new briefs
  only), `media/engine.py` (card images: already rendered images keep their
  old badge until regenerated) and `intel/dimensions.py` (story scoring: picks
  up the new value on the next ingest cycle). Checked by reading the code, not
  run against production.
