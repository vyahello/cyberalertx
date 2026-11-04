# Before / after examples (hand-edited, awaiting editor review)

These "after" versions were **rewritten by Claude following the new style
guides**, not produced by the new pipeline (which has not been run yet; see
`EDITORIAL_REVIEW_PROCESS.md` §5 for `cyberalertx.tools.benchmark`). They are
not published. They show the target, and they need the owner's review —
especially the Ukrainian.

---

## 1. EN — Synology / C3RB3R (`0f81648bf5c6b707`)

Problem: analysis asserts background the source does not contain (a 2023
Confluence campaign, a CVE, "no free decryptor exists", a DSM 7.2 feature),
and the plain summary uses the inline-gloss formula.

**Plain summary — before**
> C3RB3R ransomware, software that locks your files, is hitting Synology home and office storage boxes, and Synology says update now.

**Plain summary — after**
> Synology is telling everyone who owns one of its storage boxes to update it now: attacks with the C3RB3R file-locking ransomware have jumped.

**Analysis — before (excerpt)**
> C3RB3R is the name used by the revived Cerber operation. In late 2023 it encrypted Confluence servers within days of CVE-2023-22518 going public, so its operators tend to move fast once a weakness is known. No free decryptor exists for current C3RB3R builds.

**Analysis — after**
> Synology's warning is general: it names no vulnerability and no affected DSM version, so the safest reading is that any unpatched box reachable from the internet is a target. Devices exposed through QuickConnect or forwarded router ports carry the most risk; boxes used only inside a home or office network are less exposed but can still be reached from another infected computer on that network.
>
> The source does not say how C3RB3R gets in or whether encrypted files can be recovered. Until Synology publishes details, the only reliable protection against losing data is a backup the attackers cannot reach: an offline copy, or snapshots configured before an attack.

What changed: every claim now traces to the source; what is unknown is said once, with its consequence; no inline gloss formula.

---

## 2. UA — Ivanti Connect Secure (`5ff3e4930a9500af`, UA headline)

Problem: «закрила вразливості» is a calque (141 briefs in the archive); «як zero-day» leaves an English term inline.

**Заголовок — до**
> Ivanti закрила ще дві вразливості Connect Secure, які атакують із жовтня

**Заголовок — після**
> Ivanti виправила ще дві вразливості Connect Secure, через які зловмисники атакують шлюзи з жовтня

**Short summary — до**
> …дві його вразливості використовують ланцюжком як zero-day щонайменше з 1 жовтня.

**Short summary — після**
> BleepingComputer повідомляє, що Ivanti випустила оновлення для шлюзу віддаленого доступу Connect Secure. Дві його вразливості зловмисники поєднують в одну атаку щонайменше з 1 жовтня, тобто ще до виходу виправлення.

---

## 3. UA — DOU News #274 (`9406dd2ee53324ce`)

Problem: a weekly IT-news podcast became a "Binance breach" brief with account-security advice built from one line in the episode's contents.

**До:** «Тижневий огляд DOU News: злам Binance і модель Mistral для кібербезпеки» + поради щодо Binance.

**Після:** не публікувати. Це огляд новин, а не повідомлення про інцидент; рекомендується фільтр релевантності перед рендером (`CONTENT_AUDIT.md`). Сам злам Binance — окрема історія, яку вже покрили dev.ua та ain.ua (тепер вони обʼєднані кластеризацією).

---

## 4. UA — «Повітряна тривога» (`1acc7714f97ae941`)

Problem: repeats an impossible date from the source (attack "ввечері 2 листопада" — it happened on 1 November) and is one of five separate briefs about one incident.

**Після:** обʼєднано з чотирма іншими повідомленнями в одну історію (кластеризація, 5 видань), тож читач бачить одну подію, а не пʼять. Хибну дату 2 листопада автоматична перевірка **не** ловить: вона звіряє бриф лише з його власним джерелом, а itc.ua сам подає цю дату. Звіряння дат між джерелами кластера — рекомендоване наступне покращення.
