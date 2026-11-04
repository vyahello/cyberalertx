# CyberAlertX English style guide

House rules for the English edition. The Ukrainian edition has its own guide
(`UKRAINIAN_STYLE_GUIDE.md`); both are written from the same facts, neither
is a translation of the other. Evidence and counts: `CONTENT_AUDIT.md`.

## 1. Voice

- **Alert, not alarmed.** Calm, specific, declarative. State what happened,
  to whom, how serious it is and why, and what to do.
- **Facts before adjectives.** "Massive", "unprecedented", "sophisticated"
  only when the source gives the number or detail that earns them.
- **Second person for actions**, imperative mood: "Update DSM today." Not
  "Users are advised to consider updating."
- **No lectures.** Explain what this incident needs, not what phishing is.
- No rhetorical questions, exclamation marks, all caps or emoji.
- **US spelling** (the site declares `en-US`): organization, behavior,
  recognize, defense. The archive mixes them: "organiz-" 169 briefs vs
  "organis-" 107, "recognise" 85 vs "recognize" 21. Prompt examples must
  follow the rule too.

## 2. Headlines

1. **Sentence case.** Capitalize the first word and proper nouns only. (Haiku
   era: 37 of 115 headlines in Title Case.)
2. **Actor, verb, object, consequence.** "Synology urges NAS owners to update
   as C3RB3R attacks rise."
3. **80 characters or fewer** (132 headlines exceed it now).
4. **Precise nouns.** "Flaw" is in 21% of headlines and "flaw/bug lets" in 71.
   Name the class when it helps: "authentication bypass", "SQL injection".
5. **Attribute contested claims in the headline**: "Researcher says…",
   "Hackers claim…".
6. No question marks, exclamation marks, "Here's what you need to know",
   "Everything we know", "Urgent".
7. No CVE ID unless it is the story; no internal labels.

## 3. Lead sentence (`plain_summary`)

- One sentence, 30 words or fewer, written for a non-specialist.
- New information first: who did what to whom, and the consequence.
- **Retire the appositive gloss formula** "X, software that does Y, is …"
  (74 of 1,242 current leads). Put the explanation where it reads naturally:
  "Attackers are encrypting Synology storage boxes with C3RB3R ransomware,
  and Synology says to update now."
- "If you…" openings only when the story is about a reader action.

## 4. Attribution

- **Name the source** in `short_summary`. Vary the structure: 68.2% of
  summaries now open "<Source> reports". Facts first, attribution after is
  usually stronger: "Synology is telling every NAS owner to update after a
  spike in C3RB3R attacks, BleepingComputer reports."
- Never "experts say", "reports suggest", "it is believed".
- **Never attribute our pipeline labels to anyone.** "CISA lists this as
  informational" (11 briefs) is false: "informational" is our actionability
  label, not a CISA rating.
- **Background knowledge needs a source.** A historical fact from model
  memory ("In late 2023 it encrypted Confluence servers…") is published only
  if it is in the fact sheet or the reference list, and then with
  attribution ("CISA said in 2024…"). Otherwise cut it.

Sponsored research: when the source's byline is "Sponsored by X", the
findings are X's. Name X ("Material Security, which sponsored the article,
says ...") and keep the disclosure; the article page also shows it under
Sources. Do not present a secondary publication as the researcher.

## 5. Confirmed vs claimed

| Status | Wording | Use when |
|---|---|---|
| Confirmed | "Microsoft confirmed", "CISA added it to KEV", "is being exploited" | Vendor, agency or victim confirms |
| Reported | "reports", "according to" | A named outlet or researcher reports |
| Claimed | "claims", "says" (interested party) | Ransomware gangs, hacktivists, vendor marketing |
| Suspected | "suspected", "tied to … with moderate confidence" | Source hedges; keep the hedge and its owner |
| Unknown | "Synology has not said which DSM versions are affected." | Always state material unknowns |

- One hedge per claim. Not "could potentially possibly".
- "Likely" only with the reason in the same sentence, and only for the
  reader's decision, not to fill gaps ("The stealer likely targets SSH keys"
  is a guess; say what is reported, then advise).
- Do not predict timelines ("exploits will appear within days") unless the
  source does.

### 5.1. Evidence status is not severity (Nov 2026)

Severity is potential impact; action priority is urgency. Neither says that
attacks happened. The site shows evidence separately, from the source text
only (`pipeline/evidence.py`), in fixed wording: "Exploitation confirmed",
"Attacks observed", "Suspicious activity reported", "Data exposure not
confirmed", "Activity appears to have declined", "Attack infrastructure
taken down", "Campaign status unknown". Brief text must never outrun it:

- Vendor advice is advice, not proof. "mSeven advises customers to change
  their passwords", not "passwords were stolen".
- An unconfirmed compromise is a condition: "If the vault data was
  accessed, ...". Hedged sentences (if, whether, may, could) are not
  counted as claims by the quality gate.
- Campaign status only as the source states it, and a takedown is not an end
  ("infrastructure taken down" is not "the campaign is over").
- Name the gap where it changes what the reader does: "The company has not
  said whether stored data was exposed."

The scorecard puts a brief in the review queue when it asserts exploitation,
theft/exposure or an active campaign that the source does not support
(`unsupported_exploitation`, `unsupported_compromise`,
`campaign_status_conflict`).

## 6. Explaining terms once, without condescension

- Gloss a term **once**, at first use, in the reader-1 fields, in a few
  words: "a flaw attackers were using before a fix existed (a zero-day)".
- Do not gloss words everyone knows (password, update, browser).
- In specialist fields (`short_summary`, `detail_body`, `quick_facts`) use the
  precise term without a gloss.
- Never explain the same term twice in one brief.
- Spell out acronyms readers would not search for (FCEB → "US federal civilian
  agencies"); keep identifiers as they are (CVE, CVSS, KEV, MITRE ATT&CK).

## 7. Banned and retired phrases

**Banned (from the editorial brief).** Currently 0 occurrences each; keep it so:
"In today's digital landscape", "In an increasingly connected world",
"It is important to note that", "As cyber threats continue to evolve",
"Organizations must remain vigilant", "This highlights the importance of",
"In conclusion"; repetitive triads ("detect, respond and recover" when only
one applies); generic conclusions that could end any brief.

**Retired house tells** (found in the archive):

| Pattern | Count | Instead |
|---|---|---|
| "<Source> reports …" as the opening of `short_summary` | 1,377 | lead with the fact |
| "Treat X as Y" | 396 briefs; 156 analysis paragraphs end with "Treat…" | say the action: "Rebuild any PC that logged an Amadey detection." |
| "Attackers are…" opening `severity_reason` | 147 | name the deciding factor |
| "not just X" / "This is not X, it is Y" | 104 | state what it is |
| "Defenders/organizations should…" | 125 | address the reader or name who |
| "suggests/signals/indicates" (combined), "underscores/highlights", "leverage" | 517 / 7 / 32 briefs | plain verbs, or the fact itself |
| "in the wild" in reader-1 fields | 191 briefs overall | "in real attacks" (fine in specialist fields) |
| Meta: "the source gives no…", "available reporting" | 196 briefs (mostly older) | "BleepingComputer does not say…" or "It is not known…" |
| Internal labels: "Threat score 14.3", "actionability" | 73 briefs | never |

## 8. Numbers, dates, versions

- Numerals for 10 and above, and always with units, money, percentages,
  versions, scores, dates; words for one to nine otherwise.
- Thousands with commas: 180,000. Money: "$15 million", "$1.5 billion";
  "$15M" only in `quick_facts`.
- Percent: "31%".
- Dates in prose: "November 2, 2026"; "November 2" when the year is obvious.
  No ISO dates in prose (161 briefs have them), no "2 November 2026" (39).
- Time: 24-hour with zone, "19:38 UTC".
- Ranges with an en dash, no spaces: 2018–2021, versions 6.1–6.7.
- Versions: "version 3.0.4" in prose, "v3.0.4" acceptable in `quick_facts`;
  no "<3.0.4" or ">=1.0.0" in prose: "versions before 3.0.4".
- CVSS: "CVSS 9.8"; give the scale for lay readers only: "rated 9.8 out of 10".
- CVE IDs in full, never abbreviated.

## 9. Structure

What happened → who is affected → why it matters → what to do → what is
unknown. Each field adds a fact; none repeats the headline. If the source
gives nothing to analyse, leave `detail_body` empty rather than pad it. If
there is no reader action, leave `what_to_do` empty.

### 9.1. The article page (Nov 2026)

The page is built around reader questions, and empty blocks are not shown:
headline → plain lead → evidence strip (with a "What to do" anchor) → What
happened (with "Why it matters") → Key details (facts not already in the
prose) → Who is affected (+ How to check) → What to do (+ If you're already
affected, What to avoid; each step appears once) → What is not yet known →
Sources (attribution, author or sponsorship disclosure, other coverage) →
usefulness vote → Report a problem (factual error, outdated, translation).
The generic "Background: this kind of attack" block was removed: it
described the attack family, not the incident, and could contradict it.

What each category should cover, where the source supports it:

| Category | Cover |
|---|---|
| Vulnerability | CVE and type; affected products and exact versions; prerequisites; impact; exploitation status; patch or mitigation; action |
| Malware / ransomware | delivery; target platforms; infection chain; behaviour; persistence and C2 if documented; detection and mitigation; verified indicators |
| Phishing / scams | lure and impersonated service; the actual mechanism (e.g. AitM session theft vs password capture); what is stolen; who is targeted; what to do if exposed; prevention |
| Data breach | organisation; confirmed data types; verified numbers; timeframe; whether exfiltration is confirmed; consequences; protective actions; what is unknown |
| APT / targeted | attributed group and confidence; sectors and regions; initial access; TTPs; observed activity; sourced indicators; defences |
| Incident | what happened; affected services; operational impact; timeline; current status; the organisation's response; actions |

Audience: workplace accounts concern employees and their admins. Employees
report to IT; only admins revoke sessions or change organisation settings.

## 10. Rewrites from the archive

1. **`0f81648bf5c6b707:en`, plain_summary**
   ✗ C3RB3R ransomware, software that locks your files, is hitting Synology home and office storage boxes, and Synology says update now.
   ✓ Attackers are locking files on Synology home and office storage boxes with C3RB3R ransomware, and Synology says to update now.
   *Retires the gloss formula; the verb carries the explanation.*

2. **`0f81648bf5c6b707:en`, detail_body**
   ✗ In late 2023 it encrypted Confluence servers within days of CVE-2023-22518 going public, so its operators tend to move fast once a weakness is known. … No free decryptor exists for current C3RB3R builds.
   ✓ Synology has not said which DSM versions are being attacked or how attackers get in.
   *Both claims came from model memory, not the source; replace with the real unknown.*

3. **`d33a9ec3b29273d0:en`, detail_body**
   ✗ … attackers scanning for the framework by banner grabbing or common port discovery likely identified vulnerable instances within minutes.
   ✓ The Hacker News reports exploitation attempts began within four hours of disclosure.
   *Speculation replaced with the reported fact.*

4. **`4eceb1003b08db8e:en`, quick_facts**
   ✗ Threat score 14.3, informational
   ✓ No campaign using the kit reported yet
   *Internal label leaked to readers.*

5. **`23544328fc327905:en`, detail_body**
   ✗ … CISA's actionability rating is informational, so this is patch-planning rather than firefighting.
   ✓ CISA reports no exploitation, so the update can go into your next maintenance window.
   *CISA has no such rating; the label is ours.*

6. **`26bdb3c668b98590:en`, detail_body**
   ✗ If your UniFi controller is exposed to the internet or untrusted networks, assume active reconnaissance is occurring.
   ✓ If your UniFi console is reachable from the internet, restrict it to your VPN today; Ubiquiti has not said whether attacks have started.
   *Unfounded assumption turned into an action plus the real unknown.*

7. **`189314d5a4d0ae05:en`, detail_body**
   ✗ This remains a he-said-she-said incident until one party produces technical evidence the broader security community can audit.
   ✓ Until the researcher publishes technical details or Microsoft explains the change, AKS administrators have nothing to patch.
   *Colloquial and generic; the rewrite tells the reader what it means for them.*

8. **`4eceb1003b08db8e:en`, detail_body**
   ✗ The disclosure is research-driven, not incident response, so treat this as prioritization signal rather than an active fire.
   ✓ This is research on a phishing kit, not a report of attacks, so the fix can wait for your normal review of Microsoft 365 sign-in rules.
   *"Treat X as Y" formula and jargon.*

9. **`30de94b7338e400a:en`, what_to_do / quick_facts**
   ✗ Audit deployments for pynetdicom below v3.0.4. … Do not assume a vendor patch exists yet. … pynetdicom >=1.0.0, <3.0.4 affected
   ✓ Find every pynetdicom 1.0.0–3.0.3 deployment. CISA says the maintainer has not responded, so check the GitHub repository for a fixed release before upgrading.
   *The original contradicts itself on whether 3.0.4 is fixed; the UA render says it is.*

10. **`79b6f0e77988a6a0:en`, detail_body**
    ✗ The credential stealer likely targets environment variables, SSH keys, and authentication tokens cached in the VS Code workspace or global config.
    ✓ The Hacker News does not list what the stealer takes, so replace every token and SSH key that was on a machine with version 18.95.0 installed.
    *Guess replaced with an action that holds whatever the stealer took.*

11. **`f635e51b46992649:en`, detail_body**
    ✗ A flaw only goes into KEV with clear mitigation guidance, so a vendor fix or documented workaround should already exist.
    ✓ CISA's notice does not name a fixed release; check Ivanti's advisory before scheduling the update.
    *An inferred claim about another organization's process, stated as fact.*

12. **Haiku headline (`PraisonAI CVE-2026-44338 Auth Bypass Exploited Within Hours`, `d33a9ec3b29273d0:en`)**
    ✓ Attackers exploited a PraisonAI authentication bypass four hours after disclosure
    *Title Case, abbreviation, no verb phrase.*

13. **`690940732ff7fbfe:en`, detail_body**
    ✗ Eight of those fixes are maximum severity, so working exploits are likely to appear sooner than they would after a routine release.
    ✓ HPE has not reported attacks. Patch controllers whose management interface is reachable from the internet or guest Wi-Fi first.
    *Prediction without a source; the rewrite keeps the useful prioritization.*

14. **`51a7ae357cae7505:en`, detail_body**
    ✗ The use of AdaptixC2, an open-source post-exploitation framework, fits a pattern of espionage crews favoring commodity tooling that blends into existing red-team telemetry and complicates attribution.
    ✓ The attackers used AdaptixC2, a free post-exploitation tool, which Seqrite Labs says makes the activity harder to tell apart from authorized security testing.
    *Generalization from model knowledge; attribute it or drop it (the rewrite assumes the source says it; otherwise delete).*

## 11. Checklist

- [ ] Every fact is in the source or the fact sheet; background is attributed.
- [ ] Severity matches the Ukrainian render.
- [ ] Headline: sentence case, actor + verb, 80 characters or fewer.
- [ ] Lead: one sentence, no gloss formula.
- [ ] Attribution named; no "<Source> reports" opening by reflex.
- [ ] One stated unknown.
- [ ] Advice fits this incident and this reader; empty when there is none.
- [ ] No internal labels, no meta talk about "the source".
- [ ] US spelling; dates "November 2, 2026"; ranges with en dash.
