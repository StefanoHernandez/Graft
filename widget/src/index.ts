/**
 * The embeddable widget: one script tag, one Shadow DOM, no dependencies.
 *
 * Two rules shape the code. Every piece of text from the network is written
 * with `textContent`, never `innerHTML` — the answer quotes documents that
 * strangers uploaded. And the whole UI lives in a shadow root with `all:
 * initial` on the host, because the page it lands on has its own opinions about
 * what a `button` looks like.
 */
import { citationLabel, resolveConfig, type Citation } from "./config.js";
import { createSseParser } from "./sse.js";

const script = document.currentScript as HTMLScriptElement | null;

interface Loaded {
  __graftWidgetLoaded?: boolean;
}

const STYLES = `
:host {
  all: initial;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 2147483000;
}
* { box-sizing: border-box; }
button { font: inherit; cursor: pointer; }
.launcher {
  border: 0; border-radius: 999px; padding: 12px 18px;
  background: #1f2937; color: #fff; box-shadow: 0 6px 20px rgb(0 0 0 / 25%);
}
.panel {
  display: flex; flex-direction: column; width: min(380px, calc(100vw - 32px));
  height: min(520px, calc(100vh - 32px));
  background: #fff; color: #111827; border: 1px solid #d1d5db; border-radius: 12px;
  box-shadow: 0 12px 40px rgb(0 0 0 / 25%); overflow: hidden;
}
.head { display: flex; align-items: center; justify-content: space-between;
        padding: 10px 12px; border-bottom: 1px solid #e5e7eb; }
.head h2 { margin: 0; font-size: 15px; font-weight: 600; }
.close { background: none; border: 0; font-size: 18px; line-height: 1; padding: 4px 8px; }
.log { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.turn { max-width: 90%; padding: 8px 10px; border-radius: 10px; white-space: pre-wrap;
        word-wrap: break-word; font-size: 14px; line-height: 1.45; }
.turn.you { align-self: flex-end; background: #1f2937; color: #fff; }
.turn.bot { align-self: flex-start; background: #f3f4f6; }
.turn.problem { align-self: flex-start; background: #fef2f2; color: #991b1b; }
details { margin-top: 6px; font-size: 12px; }
summary { cursor: pointer; }
.source { margin-top: 6px; padding-left: 8px; border-left: 2px solid #d1d5db; color: #374151; }
.source b { display: block; font-weight: 600; }
form { display: flex; gap: 8px; padding: 10px; border-top: 1px solid #e5e7eb; }
input { flex: 1; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 8px; font: inherit; }
input:disabled { background: #f9fafb; }
.send { border: 0; border-radius: 8px; padding: 8px 14px; background: #1f2937; color: #fff; }
.send:disabled { opacity: .6; cursor: default; }
:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.hidden { display: none; }
`;

function boot(): void {
  const resolved = resolveConfig(script);
  if (!resolved) return;
  // Bound to a const so the narrowing survives into the async handlers below.
  const config = resolved;
  const flags = window as Loaded;
  // Two copies of the tag on one page would otherwise stack two launchers.
  if (flags.__graftWidgetLoaded) return;
  flags.__graftWidgetLoaded = true;

  const host = document.createElement("div");
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = STYLES;
  root.append(style);

  const launcher = el("button", "launcher");
  launcher.type = "button";
  launcher.textContent = config.title;
  launcher.setAttribute("aria-expanded", "false");

  const panel = el("section", "panel hidden");
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", config.title);

  const head = el("div", "head");
  const heading = document.createElement("h2");
  heading.textContent = config.title;
  const close = el("button", "close");
  close.type = "button";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  head.append(heading, close);

  const log = el("div", "log");
  log.setAttribute("role", "log");
  // "polite": an answer arriving token by token must not interrupt the reader.
  log.setAttribute("aria-live", "polite");

  const form = document.createElement("form");
  const label = document.createElement("label");
  label.htmlFor = "graft-input";
  label.textContent = "Your question";
  label.className = "hidden";
  const input = document.createElement("input");
  input.id = "graft-input";
  input.type = "text";
  input.maxLength = 2000;
  input.placeholder = "Ask a question…";
  input.autocomplete = "off";
  const send = el("button", "send");
  send.type = "submit";
  send.textContent = "Send";
  form.append(label, input, send);

  panel.append(head, log, form);
  root.append(launcher, panel);
  document.body.append(host);

  let sessionId: string | null = null; // memory only: never persisted anywhere
  let inFlight: AbortController | null = null;

  function open(): void {
    panel.classList.remove("hidden");
    launcher.classList.add("hidden");
    launcher.setAttribute("aria-expanded", "true");
    input.focus();
  }

  function shut(): void {
    // Closing the panel abandons the request in flight; it does not end the
    // conversation, which lives in `sessionId` until the page goes away.
    inFlight?.abort();
    inFlight = null;
    panel.classList.add("hidden");
    launcher.classList.remove("hidden");
    launcher.setAttribute("aria-expanded", "false");
    launcher.focus();
  }

  launcher.addEventListener("click", open);
  close.addEventListener("click", shut);
  panel.addEventListener("keydown", (event) => {
    if ((event as KeyboardEvent).key === "Escape") shut();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question || inFlight) return;
    input.value = "";
    void ask(question);
  });

  async function ask(question: string): Promise<void> {
    addTurn("you", question);
    const answer = addTurn("bot", "");
    setBusy(true);
    const controller = new AbortController();
    inFlight = controller;
    try {
      const response = await fetch(`${config.backend}/api/v1/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ bot_key: config.botKey, session_id: sessionId, message: question }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        answer.remove();
        addTurn("problem", problemText(await safeCode(response)));
        return;
      }
      await consume(response.body, answer);
    } catch (error) {
      if ((error as DOMException).name === "AbortError") {
        answer.remove();
        return;
      }
      answer.remove();
      addTurn("problem", "The connection to the assistant was lost.");
    } finally {
      inFlight = null;
      setBusy(false);
    }
  }

  async function consume(body: ReadableStream<Uint8Array>, answer: HTMLElement): Promise<void> {
    let failed = false;
    const parser = createSseParser((event) => {
      const payload = parse(event.data);
      if (!payload) return;
      if (event.event === "meta") sessionId = (payload.session_id as string) ?? sessionId;
      else if (event.event === "delta") answer.textContent += (payload.text as string) ?? "";
      else if (event.event === "done") {
        answer.textContent = (payload.answer as string) ?? answer.textContent;
        renderSources(answer, (payload.citations as Citation[]) ?? []);
      } else if (event.event === "error") {
        failed = true;
        answer.remove();
        addTurn("problem", problemText(payload.code as string));
      }
      log.scrollTop = log.scrollHeight;
    });

    const reader = body.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) parser.push(value);
      }
    } finally {
      reader.releaseLock();
    }
    if (!failed && !answer.textContent) {
      answer.remove();
      addTurn("problem", "The assistant did not answer.");
    }
  }

  function renderSources(answer: HTMLElement, citations: Citation[]): void {
    if (citations.length === 0) return;
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = citations.length === 1 ? "1 source" : `${citations.length} sources`;
    details.append(summary);
    for (const citation of citations) {
      const block = el("div", "source");
      const title = document.createElement("b");
      title.textContent = `${citation.id} · ${citationLabel(citation)}`;
      const excerpt = document.createElement("span");
      excerpt.textContent = citation.excerpt;
      block.append(title, excerpt);
      details.append(block);
    }
    answer.append(details);
  }

  function addTurn(kind: "you" | "bot" | "problem", text: string): HTMLElement {
    const turn = el("div", `turn ${kind}`);
    turn.textContent = text;
    log.append(turn);
    log.scrollTop = log.scrollHeight;
    return turn;
  }

  function setBusy(busy: boolean): void {
    input.disabled = busy;
    send.disabled = busy;
    if (!busy) input.focus();
  }
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  return node;
}

function parse(data: string): Record<string, unknown> | null {
  try {
    return JSON.parse(data) as Record<string, unknown>;
  } catch {
    return null;
  }
}

async function safeCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { code?: string } };
    return body.error?.code ?? "";
  } catch {
    return "";
  }
}

/** Codes are stable; the wording is ours, so the visitor never sees an internal message. */
function problemText(code: string): string {
  switch (code) {
    case "rate_limited":
      return "Too many questions right now. Try again in a minute.";
    case "conversation_busy":
      return "The previous question is still being answered.";
    case "invalid_citation":
      return "The answer could not be verified against the documents, so it was discarded.";
    case "origin_not_allowed":
    case "bot_not_found":
      return "This assistant is not available on this page.";
    default:
      return "The assistant is unavailable right now.";
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
