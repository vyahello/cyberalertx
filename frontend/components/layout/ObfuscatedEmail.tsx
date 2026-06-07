"use client";

import { useEffect, useState } from "react";
import { Mail } from "lucide-react";

/**
 * Spam-resistant email link. The address is split into local-part + domain
 * and only assembled in the browser after mount, so it never appears as a
 * harvestable `mailto:` / `user@domain` literal in the server-rendered HTML.
 * Most email-scraping bots regex static HTML and don't execute JS, so this
 * defeats the common case while staying fully clickable for real users.
 */
const LOCAL = "vyahello";
const DOMAIN = "gmail.com";

export function ObfuscatedEmail({ className }: { className?: string }) {
  const [addr, setAddr] = useState<string | null>(null);

  useEffect(() => {
    setAddr(`${LOCAL}@${DOMAIN}`);
  }, []);

  // Pre-hydration: render the icon with a neutral label, no address.
  const label = addr ?? "Email";

  return (
    <a
      href={addr ? `mailto:${addr}` : undefined}
      className={className}
      aria-label="Email"
      rel="nofollow"
    >
      <Mail className="w-4 h-4" aria-hidden="true" />
      <span>{label}</span>
    </a>
  );
}
