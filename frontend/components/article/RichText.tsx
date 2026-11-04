import { Fragment, type ReactNode } from "react";

/**
 * Renders model-written prose safely: text only, never HTML.
 *
 * Supported, because briefs genuinely contain them:
 *   - paragraphs separated by blank lines
 *   - ```fenced``` blocks → <pre><code> (commands, config, IOC lists)
 *   - `inline code` → <code> (paths, hashes, IPs, domains, commands)
 *   - CVE identifiers → links to their NVD record
 *
 * Everything else is plain text. Output is React text nodes, so nothing a
 * model writes can inject markup.
 */
const CVE_RE = /\bCVE-\d{4}-\d{4,7}\b/g;
const INLINE_RE = /(`[^`\n]+`|\bCVE-\d{4}-\d{4,7}\b)/g;

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(text.slice(last, idx));
    const token = m[0];
    if (token.startsWith("`")) {
      out.push(<code key={`c${idx}`}>{token.slice(1, -1)}</code>);
    } else {
      out.push(
        <a
          key={`v${idx}`}
          href={`https://nvd.nist.gov/vuln/detail/${token}`}
          target="_blank"
          rel="noopener noreferrer"
          className="whitespace-nowrap"
        >
          {token}
        </a>,
      );
    }
    last = idx + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function RichText({ text, className }: { text: string | undefined; className?: string }) {
  const body = (text ?? "").trim();
  if (!body) return null;

  // Split out fenced blocks first, then paragraphs within the prose parts.
  const parts = body.split(/```[a-z0-9-]*\n?([\s\S]*?)```/i);
  return (
    <div className={className}>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <pre key={i}>
            <code>{part.replace(/\n$/, "")}</code>
          </pre>
        ) : (
          <Fragment key={i}>
            {part
              .split(/\n{2,}/)
              .map((p) => p.trim())
              .filter(Boolean)
              .map((p, j) => (
                <p key={j}>{renderInline(p)}</p>
              ))}
          </Fragment>
        ),
      )}
    </div>
  );
}

/** Inline-only variant for list items and single sentences. */
export function InlineText({ text }: { text: string }) {
  return <>{renderInline(text)}</>;
}

export { CVE_RE };
