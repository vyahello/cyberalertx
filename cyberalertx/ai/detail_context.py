"""Detail-page context: structured paragraphs beyond the card content.

Each entry adds ~20-40% more material to a threat post: a short breakdown
of how the attack works, who is realistically affected, why attackers use
this technique, and the realistic user-side impact.

This is deliberately category-shaped (not per-item) for rule-based mode —
the paragraphs are about the *family* of attack, not a specific incident.
That keeps content honest without hallucinating incident-specific detail
we don't have.

When the LLM path is enabled, per-item context can be generated alongside
the main ThreatPost and override these defaults — the public output field
names stay the same, so the frontend doesn't change.
"""
from __future__ import annotations

from typing import Mapping, TypedDict


class DetailContext(TypedDict, total=False):
    """All four fields are optional — empty strings mean "no extra context
    for this category", and the frontend hides the corresponding section."""
    how_it_works: str
    who_is_affected: str
    attacker_motivation: str
    realistic_impact: str


# ---- English -------------------------------------------------------------

_EN: Mapping[str, DetailContext] = {
    "phishing": {
        "how_it_works": (
            "A phishing message — email, SMS, or DM — impersonates a service "
            "you trust. The link leads to a lookalike page that captures "
            "whatever you type: username, password, and (when prompted) the "
            "one-time code from your authenticator."
        ),
        "who_is_affected": (
            "Everyone with an email address or phone number. Phishing scales "
            "to millions of messages a day; the campaign only needs a small "
            "percentage of recipients to act for it to be profitable."
        ),
        "attacker_motivation": (
            "Stolen logins sell fast. Corporate credentials are reused for "
            "further intrusion; banking and shopping accounts get drained or "
            "resold; social accounts get hijacked for fraud against contacts."
        ),
        "realistic_impact": (
            "If you submit credentials, expect an account takeover within "
            "minutes. Attackers commonly change your recovery email and 2FA "
            "method first, locking you out before you notice."
        ),
    },
    "ransomware": {
        "how_it_works": (
            "Attackers gain initial access (phished credentials, an unpatched "
            "VPN, a compromised RDP) and move laterally. Once they have "
            "control, they exfiltrate sensitive data first, then encrypt "
            "everything — and threaten to publish what they stole if you "
            "don't pay."
        ),
        "who_is_affected": (
            "Any organization without offline backups and timely patching. "
            "Hospitals, schools, small businesses, and local government are "
            "the most common targets — they have meaningful data and limited "
            "security budgets."
        ),
        "attacker_motivation": (
            "Direct extortion. Ransom payments are paid in cryptocurrency and "
            "settle within hours, which is faster than almost any other "
            "monetization path available to attackers."
        ),
        "realistic_impact": (
            "Days of downtime even with backups. Without offline backups, "
            "weeks or months. Even after paying, decryption is partial — and "
            "the stolen data may surface on leak sites anyway."
        ),
    },
    "vulnerability": {
        "how_it_works": (
            "A flaw in software lets an attacker do something they shouldn't "
            "— read protected data, run code, escalate privileges. The vendor "
            "ships a patch; until you apply it, your installation is exposed."
        ),
        "who_is_affected": (
            "Anyone running an unpatched version of the affected product. "
            "Public-facing services (web apps, VPNs, mail servers) get scanned "
            "for known flaws within hours of disclosure."
        ),
        "attacker_motivation": (
            "Vulnerabilities are reusable. Once weaponized, a single exploit "
            "works against every unpatched instance on the internet — high "
            "yield for the effort."
        ),
        "realistic_impact": (
            "Depends on the bug class. Remote code execution can lead to a "
            "full host takeover. Information disclosure can leak credentials "
            "and session tokens. Authentication bypass nullifies your login "
            "controls."
        ),
    },
    "exploit": {
        "how_it_works": (
            "Working code that turns a known flaw into reliable access. "
            "Once an exploit is public, anyone — including low-skill "
            "attackers — can reach every exposed installation."
        ),
        "who_is_affected": (
            "Organizations that delayed patching. The gap between "
            "'patch shipped' and 'exploit shipped' is now measured in days, "
            "sometimes hours."
        ),
        "attacker_motivation": (
            "Speed and reliability. A working exploit is a force multiplier — "
            "the attacker stops needing to find their own way in."
        ),
        "realistic_impact": (
            "Compromise within minutes of being scanned, if you're still "
            "unpatched. Initial-access brokers will be the first to find you; "
            "ransomware crews or state actors typically follow."
        ),
    },
    "zero-day": {
        "how_it_works": (
            "A vulnerability being exploited before a patch exists. Defenders "
            "have only mitigations (configuration changes, network controls) "
            "until the vendor ships a fix."
        ),
        "who_is_affected": (
            "Initially: high-value, targeted organizations. Once details "
            "leak, every unpatched instance becomes a target."
        ),
        "attacker_motivation": (
            "Maximum stealth and reach. Zero-days are expensive to develop "
            "or buy, so they're reserved for high-value campaigns until they "
            "become public."
        ),
        "realistic_impact": (
            "Detection is hard — there's no signature for an attack the "
            "industry hasn't seen yet. Recovery requires the vendor patch and "
            "thorough forensics."
        ),
    },
    "breach": {
        "how_it_works": (
            "An attacker reached an organization's data store — through a "
            "stolen credential, an exploited vulnerability, or insider abuse "
            "— and exfiltrated records. The breach becomes public when the "
            "company discloses, the data appears for sale, or regulators "
            "force the announcement."
        ),
        "who_is_affected": (
            "Customers, employees, and anyone whose data the breached "
            "company held. The impact lasts years: stolen identifiers don't "
            "expire."
        ),
        "attacker_motivation": (
            "Reselling personal data, fueling targeted phishing, and "
            "credential-stuffing against other sites where victims reused "
            "the same password."
        ),
        "realistic_impact": (
            "Treat the leaked password as burned. Expect themed phishing "
            "in the following weeks that references your real account "
            "details from the breach."
        ),
    },
    "data leak": {
        "how_it_works": (
            "Records become publicly accessible — sometimes via a "
            "misconfigured storage bucket, sometimes posted by an attacker "
            "after a breach. Once public, the data is permanently out there."
        ),
        "who_is_affected": (
            "Anyone whose records appear in the leak. Even seemingly trivial "
            "fields (email, phone, employer) enable convincing targeted "
            "phishing later."
        ),
        "attacker_motivation": (
            "Reputational damage to the breached company, leverage in "
            "ongoing extortion, or simply revenue from selling the dataset "
            "on underground markets."
        ),
        "realistic_impact": (
            "Watch for phishing referencing details only the leaked dataset "
            "would know. Consider checking breach-tracker services for your "
            "email address."
        ),
    },
    "malware": {
        "how_it_works": (
            "A program that does something harmful on your device: steal "
            "credentials, log keystrokes, encrypt files, or quietly mine "
            "cryptocurrency. Delivery is usually a malicious download, a "
            "trojanized installer, or an email attachment."
        ),
        "who_is_affected": (
            "Anyone who installs software from unverified sources or runs "
            "attachments from unfamiliar senders. Some malware also spreads "
            "through unpatched network services."
        ),
        "attacker_motivation": (
            "Monetization: stealer logs sell on underground markets, "
            "infected hosts get rented out as proxies or botnet nodes, and "
            "ransomware operators use initial-access toolkits to find "
            "victims."
        ),
        "realistic_impact": (
            "Stored passwords and cookies harvested; financial fraud; "
            "potential lateral movement to other devices on the same "
            "network. Recovery often requires a full reinstall."
        ),
    },
    "spyware": {
        "how_it_works": (
            "Surveillance software installed silently — sometimes via a "
            "zero-click exploit, sometimes via social engineering. Once "
            "active, it can read messages, photos, location, and microphone "
            "input."
        ),
        "who_is_affected": (
            "Journalists, activists, and political opposition are the most "
            "frequent targets of commercial spyware. Stalkerware affects a "
            "much broader set of people — typically domestic abuse victims."
        ),
        "attacker_motivation": (
            "Intelligence collection. Buyers of commercial spyware are "
            "usually nation-states; stalkerware is sold to consumers for "
            "covert monitoring."
        ),
        "realistic_impact": (
            "If you might be in the targeting profile, take the article's "
            "indicators seriously — update your OS, reboot regularly, and "
            "consider device replacement for high-risk cases."
        ),
    },
    "scam": {
        "how_it_works": (
            "Attackers build rapport (sometimes over weeks), invent urgency, "
            "and direct the victim to send money or share verification codes "
            "outside any legitimate channel."
        ),
        "who_is_affected": (
            "Everyone — but especially those new to digital banking, crypto, "
            "or online dating. Older relatives are disproportionately "
            "targeted by tech-support and grandparent scams."
        ),
        "attacker_motivation": (
            "Direct financial transfer. Scams are profitable because "
            "they bypass technical defenses entirely — the human is the "
            "vulnerability."
        ),
        "realistic_impact": (
            "Lost savings (often irrecoverable). Shame and isolation often "
            "follow, which makes victims slower to report. Talking openly "
            "about these patterns helps prevent future cases."
        ),
    },
    "botnet": {
        "how_it_works": (
            "Compromised routers, IoT cameras, and home devices get enrolled "
            "into a remote-controlled network. Operators rent it out for "
            "DDoS attacks, traffic proxying, or credential stuffing."
        ),
        "who_is_affected": (
            "Owners of internet-connected devices with default passwords or "
            "unpatched firmware. Most owners never know their device joined "
            "a botnet — performance and bandwidth are the only telltales."
        ),
        "attacker_motivation": (
            "Rental income. Botnet-as-a-service is one of the most stable "
            "underground revenue streams: the customer doesn't need to know "
            "anything about hacking."
        ),
        "realistic_impact": (
            "Sluggish home internet, possible blocklisting of your IP "
            "address, and (rarely) your devices being used to attack "
            "third parties in a way that draws attention from your ISP."
        ),
    },
    "social engineering": {
        "how_it_works": (
            "An attacker plays a role — vendor, IT staff, executive, "
            "delivery driver — and asks for something that bypasses the "
            "victim's usual caution. The trick is plausibility plus time "
            "pressure."
        ),
        "who_is_affected": (
            "Anyone in a customer-facing or finance role. Employees with "
            "the authority to move money, reset credentials, or grant "
            "access are the highest-value targets."
        ),
        "attacker_motivation": (
            "Bypasses the entire technical security stack. Why find a "
            "zero-day when a phone call works?"
        ),
        "realistic_impact": (
            "Successful pretexting often leads to wire fraud, MFA reset, "
            "or unauthorized access. Best defense is a verification step "
            "through a known channel before acting on any urgent request."
        ),
    },
}


# ---- Ukrainian ----------------------------------------------------------

_UK: Mapping[str, DetailContext] = {
    "phishing": {
        "how_it_works": (
            "Фішингове повідомлення — лист, SMS або повідомлення в месенджері — "
            "імітує сервіс, якому ви довіряєте. Посилання веде на схожу сторінку, "
            "яка збирає все, що ви введете: логін, пароль і (за наявності) "
            "одноразовий код з автентифікатора."
        ),
        "who_is_affected": (
            "Будь-хто з електронною поштою або телефоном. Кампанії масштабуються "
            "до мільйонів повідомлень на день; навіть малий відсоток клікнутих "
            "робить атаку прибутковою."
        ),
        "attacker_motivation": (
            "Викрадені логіни швидко продаються. Корпоративні дані використовують "
            "для подальших атак, банківські — виводять у готівку, а соцмережі "
            "перехоплюють для шахрайства проти ваших контактів."
        ),
        "realistic_impact": (
            "Після введення облікових даних — захоплення акаунту протягом хвилин. "
            "Зловмисники зазвичай одразу міняють email відновлення та 2FA, тож ви "
            "втрачаєте контроль ще до того, як помітите."
        ),
    },
    "ransomware": {
        "how_it_works": (
            "Атакуючі отримують початковий доступ (фішинг, незахищений VPN або "
            "RDP) і поширюються по мережі. Спочатку вони викрадають дані, потім "
            "шифрують усе — і погрожують опублікувати викрадене, якщо ви не "
            "заплатите."
        ),
        "who_is_affected": (
            "Будь-яка організація без офлайн-резервних копій та своєчасного "
            "оновлення. Лікарні, школи, малий бізнес, місцеві органи влади — "
            "найчастіші цілі."
        ),
        "attacker_motivation": (
            "Пряме вимагання. Викуп у криптовалюті проходить за години — швидше "
            "за більшість інших способів монетизації, доступних зловмисникам."
        ),
        "realistic_impact": (
            "Дні простою навіть з резервними копіями. Без них — тижні або "
            "місяці. Навіть після оплати розшифрування часткове, а вкрадені "
            "дані все одно можуть з’явитися публічно."
        ),
    },
    "vulnerability": {
        "how_it_works": (
            "Помилка в програмному забезпеченні дозволяє атакуючому зробити те, "
            "чого не повинно бути дозволено — прочитати захищені дані, виконати "
            "код, підвищити права. Виробник випускає патч; до його встановлення "
            "ваша інсталяція вразлива."
        ),
        "who_is_affected": (
            "Усі, хто використовує неоновлену версію продукту. Сервіси, "
            "доступні з інтернету, скануються на відомі вразливості протягом "
            "годин після розкриття."
        ),
        "attacker_motivation": (
            "Вразливості універсальні. Один експлойт працює проти кожної "
            "неоновленої інсталяції — висока віддача за відносно невеликі "
            "зусилля."
        ),
        "realistic_impact": (
            "Залежить від класу помилки. RCE — повний контроль над сервером. "
            "Витік інформації — облікові дані та токени сесій. Bypass "
            "автентифікації — обхід ваших захисних механізмів."
        ),
    },
    "exploit": {
        "how_it_works": (
            "Робочий код, що перетворює відому вразливість на надійний доступ. "
            "Як тільки експлойт стає публічним, ним може скористатися навіть "
            "малокваліфікований атакуючий."
        ),
        "who_is_affected": (
            "Організації, які зволікають із патчуванням. Проміжок між випуском "
            "патча та появою експлойту тепер вимірюється днями, інколи годинами."
        ),
        "attacker_motivation": (
            "Швидкість і надійність. Готовий експлойт — це підсилювач: "
            "атакуючому не потрібно шукати свій шлях усередину."
        ),
        "realistic_impact": (
            "Компроматація за кілька хвилин після сканування, якщо ви досі "
            "не оновили. Першими знайдуть посередники для продажу доступу; "
            "далі зазвичай йдуть оператори ransomware або державні угруповання."
        ),
    },
    "zero-day": {
        "how_it_works": (
            "Вразливість, яку експлуатують ще до випуску патча. Захисникам "
            "доступні лише пом’якшення (конфігурація, мережеві обмеження), доки "
            "виробник не випустить фікс."
        ),
        "who_is_affected": (
            "Спочатку — цінні, цілеспрямовані організації. Після витоку деталей "
            "ціллю стає кожна неоновлена інсталяція."
        ),
        "attacker_motivation": (
            "Максимальна непомітність і охоплення. Zero-day’ї дорогі в розробці "
            "або купівлі, тож їх використовують у важливих кампаніях, доки вони "
            "не стають публічними."
        ),
        "realistic_impact": (
            "Виявлення складне — сигнатур для атаки, якої індустрія ще не "
            "бачила, не існує. Відновлення потребує патча та ретельного "
            "розслідування."
        ),
    },
    "breach": {
        "how_it_works": (
            "Атакуючий дістався сховища даних організації — через викрадені "
            "облікові дані, експлойт або зловживання інсайдером — і вивів "
            "записи. Витік стає публічним, коли компанія розкриває його, дані "
            "з’являються на продаж або регулятори вимагають оголошення."
        ),
        "who_is_affected": (
            "Клієнти, працівники й усі, чиї дані зберігала постраждала компанія. "
            "Вплив триває роками: викрадені ідентифікатори не «застарівають»."
        ),
        "attacker_motivation": (
            "Перепродаж персональних даних, прицільний фішинг і атаки "
            "підбору пароля проти інших сервісів, де жертви використовували "
            "той самий пароль."
        ),
        "realistic_impact": (
            "Вважайте витеклий пароль скомпрометованим. У наступні тижні "
            "очікуйте тематичного фішингу, який посилається на реальні "
            "дані з вашого облікового запису."
        ),
    },
    "data leak": {
        "how_it_works": (
            "Записи стають публічно доступними — інколи через неправильно "
            "налаштоване хмарне сховище, інколи через публікацію після злому. "
            "Як тільки дані публічні, вони назавжди залишаються поза контролем."
        ),
        "who_is_affected": (
            "Усі, чиї записи потрапили у злив. Навіть тривіальні поля "
            "(email, телефон, роботодавець) дозволяють згодом створити "
            "переконливий цільовий фішинг."
        ),
        "attacker_motivation": (
            "Репутаційний удар по компанії, додатковий важіль у поточному "
            "вимаганні, або просто продаж датасету на тіньових майданчиках."
        ),
        "realistic_impact": (
            "Слідкуйте за фішингом, який знає деталі, наявні лише у злитих "
            "даних. Перевірте свою адресу на сервісах відстеження витоків."
        ),
    },
    "malware": {
        "how_it_works": (
            "Програма, що виконує шкідливі дії на пристрої: краде облікові дані, "
            "записує клавіатуру, шифрує файли або тихо майнить криптовалюту. "
            "Доставка — зазвичай шкідливий файл, троянізований інсталятор або "
            "вкладення в листі."
        ),
        "who_is_affected": (
            "Усі, хто встановлює ПЗ з неперевірених джерел або відкриває "
            "вкладення від незнайомих відправників. Частина шкідливих програм "
            "поширюється й через неоновлені мережеві сервіси."
        ),
        "attacker_motivation": (
            "Монетизація: логи стилерів продають на тіньових майданчиках, "
            "заражені хости здають в оренду як проксі або вузли ботнету, "
            "оператори ransomware використовують їх для пошуку жертв."
        ),
        "realistic_impact": (
            "Збережені паролі та cookies в руках зловмисника; фінансове "
            "шахрайство; можливе поширення в межах вашої домашньої мережі. "
            "Часто єдиний шлях — повна переустановка."
        ),
    },
    "spyware": {
        "how_it_works": (
            "Шпигунське ПЗ встановлюється непомітно — інколи через zero-click "
            "експлойт, інколи через соціальну інженерію. Після активації може "
            "читати повідомлення, фото, локацію та звук з мікрофона."
        ),
        "who_is_affected": (
            "Журналісти, активісти й політична опозиція — найчастіші цілі "
            "комерційного шпигунського ПЗ. Stalkerware вражає значно ширше "
            "коло — зазвичай жертв домашнього насильства."
        ),
        "attacker_motivation": (
            "Збір розвідданих. Покупці комерційного спайвера — переважно "
            "державні структури; stalkerware продається споживачам для "
            "прихованого стеження."
        ),
        "realistic_impact": (
            "Якщо ви можете бути в профілі цілей — поставтеся серйозно: "
            "оновлюйте ОС, регулярно перезавантажуйте пристрій, у "
            "високоризикових випадках — замініть пристрій."
        ),
    },
    "scam": {
        "how_it_works": (
            "Шахраї будують довіру (іноді тижнями), створюють терміновість і "
            "змушують жертву переказати гроші або поділитися кодами "
            "підтвердження поза будь-яким легітимним каналом."
        ),
        "who_is_affected": (
            "Усі — але особливо ті, хто новий у банкінгу, крипті або "
            "онлайн-знайомствах. Старші родичі частіше за всіх стають "
            "ціллю «техпідтримки» та схем із «онуком у біді»."
        ),
        "attacker_motivation": (
            "Прямий переказ грошей. Шахрайство прибуткове, бо повністю "
            "обходить технічний захист — людина і є вразливістю."
        ),
        "realistic_impact": (
            "Втрачені заощадження (часто безповоротно). Сором і ізоляція "
            "часто супроводжують — і саме через це жертви довше не "
            "звертаються по допомогу. Відкрита розмова про такі схеми "
            "запобігає новим випадкам."
        ),
    },
    "botnet": {
        "how_it_works": (
            "Скомпрометовані роутери, IoT-камери та домашні пристрої "
            "потрапляють у мережу, керовану дистанційно. Оператори "
            "здають її в оренду для DDoS-атак, проксі-трафіку або "
            "атак підбору паролів."
        ),
        "who_is_affected": (
            "Власники інтернет-пристроїв з дефолтними паролями або "
            "старою прошивкою. Більшість не дізнаються, що пристрій у "
            "ботнеті — повільність і трафік є єдиними ознаками."
        ),
        "attacker_motivation": (
            "Орендна плата. Botnet-as-a-Service — одне зі стабільних "
            "джерел доходу: покупцеві не потрібно нічого знати про злам."
        ),
        "realistic_impact": (
            "Повільний домашній інтернет, можливе блокування вашої IP "
            "у списках, і (зрідка) використання ваших пристроїв для атак "
            "на третіх осіб, що може привернути увагу провайдера."
        ),
    },
    "social engineering": {
        "how_it_works": (
            "Атакуючий вдає роль — постачальник, ІТ-фахівець, керівник, "
            "кур’єр — і просить про дію, яка обходить звичайну обережність. "
            "Сила прийому — у правдоподібності плюс тиск часу."
        ),
        "who_is_affected": (
            "Усі на ролях, де є контакт з клієнтами або фінансами. "
            "Працівники, які можуть переказувати кошти, скидати облікові "
            "дані чи давати доступ — найцінніші цілі."
        ),
        "attacker_motivation": (
            "Обхід усього технічного стеку безпеки. Навіщо шукати "
            "zero-day, якщо телефонний дзвінок працює?"
        ),
        "realistic_impact": (
            "Успішний предтекстинг часто закінчується банківським переказом, "
            "скиданням MFA або несанкціонованим доступом. Найкращий "
            "захист — окрема перевірка через відомий канал перед будь-якою "
            "терміновою дією."
        ),
    },
}


_TABLES: Mapping[str, Mapping[str, DetailContext]] = {"en": _EN, "ua": _UK}


def detail_context_for(category: str, locale: str) -> DetailContext:
    """Return the context block for `category` in `locale`, or {} if unknown.

    Defensive: unknown category or locale → empty dict. Frontend renders the
    sections only when their fields are present, so a missing entry produces
    a slightly thinner detail page rather than a layout glitch.
    """
    table = _TABLES.get(locale, {})
    return table.get(category, {})


__all__ = ["detail_context_for", "DetailContext"]
