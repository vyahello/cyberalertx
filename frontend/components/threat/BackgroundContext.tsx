import { strings } from "@/lib/i18n";
import type { DetailContext, Locale } from "@/lib/types";

interface Props {
  context: DetailContext | undefined;
  lang: Locale;
}

/**
 * Per-category background: how this family of attack works, who it usually
 * hits, why attackers bother, and what realistically happens.
 *
 * Hand-written and keyed on category rather than on the incident, which is
 * what makes it safe to show on every post — it never asserts anything
 * item-specific that we might not actually know.
 *
 * It exists because roughly a quarter of posts fall back to the rule-based
 * renderer, whose item-specific copy is one templated sentence and whose
 * analysis section is empty. For those, this is the only real explanation
 * the reader gets. For AI-rendered posts it sits below the incident
 * analysis as orientation for someone unfamiliar with the attack class.
 *
 * Rendered last in the narrative for exactly that reason: a reader who
 * already knows what ransomware is never has to scroll through it.
 */
export function BackgroundContext({ context, lang }: Props) {
  if (!context) return null;

  const s = strings(lang);
  const blocks: Array<{ label: string; body: string | undefined }> = [
    { label: s.context_how_it_works, body: context.how_it_works },
    { label: s.context_who_is_affected, body: context.who_is_affected },
    { label: s.context_attacker_motivation, body: context.attacker_motivation },
    { label: s.context_realistic_impact, body: context.realistic_impact },
  ];
  const present = blocks.filter((b) => b.body && b.body.trim());
  if (present.length === 0) return null;

  return (
    <section className="border-t border-border-subtle pt-6">
      <h2 className="text-2xs font-semibold uppercase tracking-wider text-text-tertiary mb-4">
        {s.context_section_heading}
      </h2>
      <div className="space-y-5">
        {present.map(({ label, body }) => (
          <div key={label}>
            <h3 className="text-sm font-semibold text-text-primary mb-1.5">
              {label}
            </h3>
            <p className="text-sm text-text-secondary leading-relaxed measure">
              {body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
