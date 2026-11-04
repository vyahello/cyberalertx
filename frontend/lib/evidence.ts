/**
 * Evidence status for display: what the source reporting establishes,
 * shown apart from severity (potential impact) and action priority.
 *
 * Every row comes from `post.evidence` (backend `pipeline/evidence.py`),
 * which reads only the source title, excerpt and byline. Older API builds
 * without `evidence` fall back to the strict `signals.active_exploitation`
 * flag. Rows that would say nothing useful are omitted, never filled with a
 * guess.
 */
import { strings } from "./i18n";
import type { Locale, LocalizedThreatPost, ThreatEvidence, UnknownCode } from "./types";

export type EvidenceTone = "critical" | "high" | "medium" | "muted";

export interface EvidenceRow {
  key: "exploitation" | "compromise" | "campaign";
  label: string;
  value: string;
  tone: EvidenceTone;
}

/** Categories where "is it exploited?" is the question a reader asks. */
const VULN_CATEGORIES = new Set(["vulnerability", "exploit", "zero-day"]);

export const TONE_CLASS: Record<EvidenceTone, string> = {
  critical: "text-sev-critical",
  high: "text-sev-high",
  medium: "text-sev-medium",
  muted: "text-ink-muted",
};

export function evidenceOf(post: LocalizedThreatPost): ThreatEvidence {
  if (post.evidence) return post.evidence;
  return {
    exploitation: post.signals?.active_exploitation ? "confirmed" : "not_reported",
    campaign: "",
    compromise: "",
    sponsored: false,
    sponsor: "",
    unknowns: [],
  };
}

export function exploitationConfirmed(post: LocalizedThreatPost): boolean {
  return evidenceOf(post).exploitation === "confirmed";
}

export function evidenceRows(post: LocalizedThreatPost, lang: Locale): EvidenceRow[] {
  const s = strings(lang);
  const ev = evidenceOf(post);
  const rows: EvidenceRow[] = [];
  const isVuln = VULN_CATEGORIES.has(post.category);

  if (ev.exploitation === "confirmed") {
    rows.push({ key: "exploitation", label: s.mark_status, value: s.status_exploitation.confirmed, tone: "critical" });
  } else if (ev.exploitation === "attacks_observed") {
    rows.push({ key: "exploitation", label: s.mark_status, value: s.status_exploitation.attacks_observed, tone: "high" });
  } else if (ev.exploitation === "suspected") {
    rows.push({ key: "exploitation", label: s.mark_status, value: s.status_exploitation.suspected, tone: "medium" });
  } else if (isVuln) {
    rows.push({ key: "exploitation", label: s.mark_status, value: s.status_exploitation.not_reported, tone: "muted" });
  }

  if (ev.compromise) {
    rows.push({
      key: "compromise",
      label: s.mark_status,
      value: s.status_compromise[ev.compromise],
      tone: ev.compromise === "confirmed" ? "critical" : "muted",
    });
  }

  if (ev.campaign) {
    rows.push({
      key: "campaign",
      label: s.mark_campaign,
      value: s.status_campaign[ev.campaign],
      tone: ev.campaign === "active" ? "high" : "muted",
    });
  }
  return rows;
}

export function unknownsOf(post: LocalizedThreatPost, lang: Locale): string[] {
  const s = strings(lang);
  const known = new Set<UnknownCode>(Object.keys(s.unknown) as UnknownCode[]);
  return evidenceOf(post)
    .unknowns.filter((u) => known.has(u))
    .map((u) => s.unknown[u]);
}
