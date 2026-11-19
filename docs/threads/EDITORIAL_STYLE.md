# Threads editorial style (EN and UA)

How CyberAlertX writes for `@cyberalertx` (English) and `@cyberalertx_ua`
(Ukrainian). The writer is `cyberalertx/threads/editorial.py`: a language
model drafts both posts for one story from the source evidence, and
deterministic checks decide whether the draft may be published. This page
is the human-readable version of those rules; the prompt (`SYSTEM`) and the
checks (`check()`) are the source of truth.

## Voice

Professional, technically informed, calm, specific. It should read like an
experienced security editor who has read the reporting, not like an RSS feed
or a press release.

- No clickbait, hype words (massive, huge, alarming, shocking), exclamation
  marks or rhetorical questions.
- No fear framing. The facts carry the weight.
- At most one emoji (normally none), no hashtags. One topic tag per post:
  `Cybersecurity` / `Кібербезпека`.

## Structure

```
<hook>                      one line, ≤ 100 characters, not the headline

<what happened>             who, which product or organisation, the mechanism,
                            and what is confirmed, alleged or under investigation

<why it matters>            one insight beyond the headline, from the facts

[<Audience>: <advice>]      only when the source gives the step

Reporting: <outlet>         Джерело: <outlet>
<article link>
```

- **Hook.** Gives a reason to stop scrolling and makes sense as the very
  first thing a reader sees. It carries the story's most consequential
  specific: a number, a named product or organisation, an unexpected
  technical detail, or a clear security implication. It never refers back to
  something not yet said ("the list", "too", "also", "this", "it"). It never
  repeats or paraphrases our headline or the source's.
- **What happened.** Concrete details from the source. Keep the source's
  status exactly (see below).
- **Why it matters.** One genuine point: why a third-party script reaches
  every site that loads it, or why an investigation is not a confirmed
  breach. Never a restatement of "what happened".
- **Advice.** Only when the source itself gives a concrete step, addressed
  to a named audience ("Site administrators: …"). The same advice must appear
  in both languages, or none.
- **Length.** Target 350–450 characters including the source line and the
  link; hard limit 500 (Threads counts emoji as bytes). Choose the strongest
  angle instead of cramming. Text is never truncated: a draft that is too
  long is rejected.

## Facts and status

- Every number, name, product, CVE id and status comes from the source
  article (headline or text). If the source does not say it, the post does
  not say it. Figures are written as digits.
- Keep these distinctions: confirmed, reported, alleged, under
  investigation, potentially affected, exploited in the wild, proof of
  concept, patched, patching urged, and fix announced but not yet released.
  - An attacker's claim, a leak-site listing, or a company investigating a
    claim is **not** a confirmed breach. The post says it is a claim.
  - A vulnerability is **not** exploited unless the source says so.
  - A capability is not proof of use.
- **No relative time.** Posts go out hours after the article. "today",
  "yesterday", "in the past day", "this week", «сьогодні», «вчора» and
  «за останню добу» are not allowed. An absolute date (the article date) is
  used only when it adds something.
- **No generic remediation.** Never add antivirus scans, password or device
  resets, "patch now", disabling systems or rotating credentials unless the
  source gives that step. Advice needs a quoted source sentence.

## English and Ukrainian

The Ukrainian post is written as natural, professional Ukrainian, not a
word-for-word translation. Both posts carry exactly the same:
- facts and numbers;
- organisations, products and CVE ids;
- status and caveats;
- time references;
- advice.

Official product and organisation names stay in Latin script. Where an
established Ukrainian form exists (ФБР for FBI), the draft records the pair
so the check can match them.

## Image

The post uses only the story's canonical illustration from the production
image index, the same asset as the website and Telegram, with its alt text
in the post's language. Quarantine candidates are never used. The post must
not contradict the image, and the alt text must not name an organisation or
state a figure that neither the source nor our headline gives.

## Hard gates

| Gate | Floor | What decides it |
|---|---|---|
| Factual accuracy | 5 | every number, CVE and Latin-script name is in the source |
| Evidence integrity | 5 | facts quoted verbatim; claims stay claims; exploitation and "confirmed" only when reported; no relative time; no unsupported advice |
| EN/UA equivalence | 5 | same numbers, CVEs, names (or recorded pairs) and advice in both languages |
| Image relevance | 5 | alt text consistent with the source |
| Technical clarity | 4 | "what happened" names the product or organisation and the mechanism in both languages |
| Readability | 4 | short sentences; no repeated paragraph; within the target length |
| Editorial value | 4 | "why it matters" adds something beyond "what happened" |
| Overall | 4 | lowest of all scores and the average of the soft ones |

Hook quality and professional tone are scored as well and pull "overall"
down. A failed hook (headline repeat, dangling reference) or any form
problem (hashtag, link in the text, over the limit) blocks publication.

The writer gets one retry with the failed checks as feedback. A draft that
still fails is stored and **never published**: the job ends as invalid
content, and nothing falls back to another text. The stored draft records
the version of the checks it was judged by. When the checks change, a
failed draft is rewritten once; a passing one is reused unchanged, so a
retry after an uncertain send always sends the same words.

## What is not automated

- **Discussion prompts.** Drafted with each story for the editor and never
  posted.
- **Replies and comments.** None are sent automatically.

## Before and after (the 18 Nov baseline test posts)

Before, EN (`threads.com/@cyberalertx/post/Df5kr6QCFcO`, kept unchanged):

- the headline was copied as the first line;
- a paragraph was repeated;
- "in the past day" was used hours later;
- it gave antivirus advice the source does not give;
- the sites named differed from the UA post.

After (same story, writer output, 451 characters):

> Equifax and Ledger were among the sites that silently served data-stealing code to visitors.
>
> At least 178 top websites, including the BBC, CNN and Zoom, served malware through a security vulnerability involving Optimizely…
>
> Experts say the incident was made worse because few popular sites strictly limit which sources can supply third-party content.
>
> Reporting: Krebs on Security

The 20-story review (EN and UA side by side, with scores, character counts,
the image and its alt text) is kept with the release review records under
`$REVIEW_DIR`.
