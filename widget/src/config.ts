/**
 * Where the widget talks to, and on whose behalf.
 *
 * The backend is derived from the script's own URL, so a host page only writes
 * one tag and never repeats the origin. `document.currentScript` is read at
 * load time because it is null once anything async has run.
 */
export interface WidgetConfig {
  backend: string;
  botKey: string;
  title: string;
}

export function resolveConfig(script: HTMLScriptElement | null): WidgetConfig | null {
  if (!script) return null;
  const botKey = script.dataset.graftBot?.trim();
  if (!botKey) return null;
  const explicit = script.dataset.graftBackend?.trim();
  const backend = explicit ? stripTrailingSlash(explicit) : backendFromScript(script.src);
  if (!backend) return null;
  return { backend, botKey, title: script.dataset.graftTitle?.trim() || "Ask about the docs" };
}

function backendFromScript(src: string): string | null {
  try {
    const url = new URL(src, typeof location === "undefined" ? undefined : location.href);
    return `${url.protocol}//${url.host}`;
  } catch {
    return null;
  }
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export interface Citation {
  id: string;
  filename: string;
  page: number | null;
  heading: string | null;
  excerpt: string;
}

/** Human label for a source, e.g. `install.md · page 2`. */
export function citationLabel(citation: Citation): string {
  const parts = [citation.filename];
  if (citation.page !== null && citation.page !== undefined) parts.push(`page ${citation.page}`);
  if (citation.heading) parts.push(citation.heading);
  return parts.join(" · ");
}
