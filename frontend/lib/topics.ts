/**
 * Topic sections — the site's navigation.
 *
 * Each topic is a family of the pipeline's categories. Only families with a
 * steady flow of stories in both editions are listed (checked against the
 * live cache when they were introduced), so no section opens empty.
 */
import type { Category } from "./types";

export type TopicSlug = "vulnerabilities" | "malware" | "breaches" | "phishing";

export const TOPIC_SLUGS: readonly TopicSlug[] = [
  "vulnerabilities",
  "malware",
  "breaches",
  "phishing",
] as const;

export const TOPIC_CATEGORIES: Record<TopicSlug, readonly Category[]> = {
  vulnerabilities: ["vulnerability", "exploit", "zero-day"],
  malware: ["ransomware", "malware", "spyware", "botnet"],
  breaches: ["breach", "data leak"],
  phishing: ["phishing", "scam", "social engineering"],
};

export function isTopic(x: string | undefined): x is TopicSlug {
  return !!x && (TOPIC_SLUGS as readonly string[]).includes(x);
}

/** The topic a category belongs to, if any (used for breadcrumbs). */
export function topicForCategory(category: string): TopicSlug | null {
  for (const slug of TOPIC_SLUGS) {
    if ((TOPIC_CATEGORIES[slug] as readonly string[]).includes(category)) return slug;
  }
  return null;
}
