/* The admin desk.
 *
 * Two rules run through the whole file. The token lives in a variable and
 * nowhere else, so closing the tab ends the session. And every state the reader
 * sees is a sentence in their language: the exact code is available under
 * "Technical detail", never leading. */

const API = "/api/v1/admin";
const CHUNK_CEILING = 2000;
const POLL_MS = 3000;
/* After this many polls with nothing moving, stop and say so. A spinner that
 * never ends is how an interface lies about a worker that is not running. */
const POLL_PATIENCE = 20;

let token = null;
let bots = [];
let currentBotId = null;
let poll = { timer: null, quiet: 0, signature: "" };
let conversationPage = 0;

const $ = (selector, root = document) => root.querySelector(selector);
const view = { signin: $("#view-signin"), desk: $("#view-desk") };
const workspace = $("#workspace");
const announcer = $("#announce");

/* --- plain language ------------------------------------------------------ */

const STATE_TEXT = {
  pending: "Waiting to be read.",
  processing: "Being read now.",
  ready: "Ready to answer.",
  failed: "Could not be used.",
};

const PROBLEM_TEXT = {
  no_extractable_text:
    "No text could be read from this file. A scanned PDF is a picture of a page, not text — re-upload a version with selectable text.",
  corrupt_document: "This file could not be opened. Re-upload it, or export it again.",
  too_many_pages: "This document has more pages than the limit of 200.",
  too_much_text: "This document is longer than the limit.",
  too_many_chunks: "This document would produce more sections than the limit of 2000.",
  missing_source: "The original file is no longer on disk, so it cannot be read again.",
  provider_auth: "The embedding provider refused the API key. Check it below.",
  provider_rate_limit: "The provider is rate-limiting this instance. It will be retried.",
  provider_timeout: "The provider did not answer in time.",
  provider_unavailable: "The provider could not be reached.",
  provider_config: "The provider settings are not usable. Check the model name below.",
  provider_invalid_response: "The provider returned something unusable.",
  attempts_exhausted: "Tried three times and gave up. Fix the cause, then retry.",
  parse_timeout: "Reading this file took too long and was stopped.",
  internal_error: "Something went wrong on this instance. The logs will say more.",
  file_too_large: "That file is over the 10 MB limit.",
  unsupported_type: "Only PDF, Markdown and plain text can be read.",
  bot_not_found: "That bot no longer exists.",
  embedding_config_locked:
    "This bot already has documents, so the embedding model cannot change. The key can.",
  not_failed: "That document is not in a failed state.",
};

const say = (code, fallback) => PROBLEM_TEXT[code] || fallback || "Something went wrong.";

function announce(message) {
  announcer.textContent = "";
  // Re-setting the text is what makes a repeated message speak again.
  window.setTimeout(() => { announcer.textContent = message; }, 30);
}

function humanBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function humanWhen(value) {
  if (!value) return "";
  // The interface is written in one language; dates must not arrive in another.
  const locale = document.documentElement.lang || undefined;
  return new Date(value).toLocaleString(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function kindOf(mime, filename) {
  if (mime === "application/pdf" || filename.toLowerCase().endsWith(".pdf")) return "PDF";
  if (/\.(md|markdown)$/i.test(filename)) return "Markdown";
  return "Text";
}

/* --- transport ----------------------------------------------------------- */

class ApiError extends Error {
  constructor(status, code) {
    super(code || String(status));
    this.status = status;
    this.code = code;
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  const response = await fetch(`${API}${path}`, { ...options, headers });
  if (response.status === 401) {
    signOut();
    throw new ApiError(401, "signed_out");
  }
  if (!response.ok) {
    let code = null;
    try {
      const body = await response.json();
      code = body?.detail?.code ?? body?.error?.code ?? null;
    } catch { /* an empty or non-JSON body is still a failure we can report */ }
    throw new ApiError(response.status, code);
  }
  return response.status === 204 ? null : response.json();
}

/* --- session ------------------------------------------------------------- */

$("#form-signin").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const problem = $("#signin-problem");
  problem.hidden = true;
  const body = new URLSearchParams({
    username: form.email.value.trim(),
    password: form.password.value,
  });
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/auth/jwt/login", { method: "POST", body });
    if (!response.ok) {
      problem.textContent =
        response.status === 400
          ? "That email and password do not match an active account."
          : "Sign-in is not available right now.";
      problem.hidden = false;
      return;
    }
    token = (await response.json()).access_token;
    form.password.value = "";
    await openDesk();
  } finally {
    button.disabled = false;
  }
});

function signOut() {
  token = null;
  stopPolling();
  view.desk.hidden = true;
  view.signin.hidden = false;
  $("#signout").hidden = true;
  $("#instance").textContent = "admin";
}

$("#signout").addEventListener("click", signOut);

async function openDesk() {
  view.signin.hidden = true;
  view.desk.hidden = false;
  $("#signout").hidden = false;
  await loadBots();
}

/* --- bots ---------------------------------------------------------------- */

async function loadBots(selectId) {
  const page = await api("/bots?limit=100");
  bots = page.items;
  renderRail();
  const wanted = selectId || currentBotId || (bots[0] && bots[0].id);
  if (wanted) await openBot(wanted);
  else showNewBot();
}

function renderRail() {
  const list = $("#bot-list");
  list.textContent = "";
  for (const bot of bots) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-current", String(bot.id === currentBotId));
    button.append(document.createTextNode(bot.name));
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = bot.embedding_config
      ? bot.embedding_config.model
      : "no embedding model yet";
    button.append(count);
    button.addEventListener("click", () => openBot(bot.id));
    item.append(button);
    list.append(item);
  }
}

$("#bot-new").addEventListener("click", showNewBot);

function showNewBot() {
  stopPolling();
  currentBotId = null;
  renderRail();
  render("#tpl-new-bot");
  const form = $("[data-new-bot-form]", workspace);
  $("[data-cancel]", form).addEventListener("click", () => {
    if (bots.length) openBot(bots[0].id);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const problem = $("[data-new-bot-problem]", form);
    problem.hidden = true;
    const origins = form.origins.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    try {
      const bot = await api("/bots", {
        method: "POST",
        json: { name: form.name.value.trim(), allowed_origins: origins },
      });
      await loadBots(bot.id);
      announce(`Bot ${bot.name} created.`);
    } catch (error) {
      problem.textContent = say(error.code, "The bot could not be created.");
      problem.hidden = false;
    }
  });
}

/* On a phone the reader's first question is whether the documents are ready,
   not how to embed the widget — that is a once-per-bot action. The node moves
   for real rather than through CSS order, so focus order and reading order stay
   the same thing. */
const narrow = window.matchMedia("(max-width: 860px)");

function arrangeSections() {
  const snippet = $('[data-section="snippet"]', workspace);
  const documents = $('[data-section="documents"]', workspace);
  if (!snippet || !documents) return;
  if (narrow.matches) documents.after(snippet);
  else documents.before(snippet);
}

narrow.addEventListener("change", arrangeSections);

function render(templateId) {
  workspace.textContent = "";
  workspace.append($(templateId).content.cloneNode(true));
}

async function openBot(botId) {
  stopPolling();
  currentBotId = botId;
  conversationPage = 0;
  renderRail();
  const bot = bots.find((candidate) => candidate.id === botId);
  if (!bot) return;

  render("#tpl-bot");
  $("[data-bot-name]", workspace).textContent = bot.name;
  $("#instance").textContent = bot.name;
  renderSnippet(bot);
  renderProviderForm(bot);
  wireUpload(bot);
  $("[data-delete-bot]", workspace).addEventListener("click", () => deleteBot(bot));
  arrangeSections();
  await refreshDocuments();
  await loadConversations(true);
}

function renderSnippet(bot) {
  const origin = window.location.origin;
  const snippet =
    `<script src="${origin}/widget/graft.js" data-graft-bot="${bot.widget_key}"></script>`;
  $("[data-snippet]", workspace).textContent = snippet;
  const note = $("[data-origins-note]", workspace);
  note.textContent = bot.allowed_origins.length
    ? `The widget answers on: ${bot.allowed_origins.join(", ")}.`
    : "No origin is allowed yet, so the widget will be refused on every page. Add one to this bot.";
  $("[data-copy]", workspace).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(snippet);
      button.textContent = "Copied";
      announce("Script tag copied.");
      window.setTimeout(() => { button.textContent = "Copy"; }, 1600);
    } catch {
      // Clipboard access can be refused; selecting the text still works.
      const range = document.createRange();
      range.selectNodeContents($("[data-snippet]", workspace));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      button.textContent = "Select and copy";
    }
  });
}

async function deleteBot(bot) {
  if (!window.confirm(`Delete ${bot.name}, its documents and its transcripts?`)) return;
  await api(`/bots/${bot.id}`, { method: "DELETE" });
  currentBotId = null;
  announce(`Bot ${bot.name} deleted.`);
  await loadBots();
}

/* --- providers ----------------------------------------------------------- */

function renderProviderForm(bot) {
  const form = $("[data-provider-form]", workspace);
  form.llm_model.value = bot.llm_config ? bot.llm_config.model : "";
  form.embedding_model.value = bot.embedding_config ? bot.embedding_config.model : "";
  setKeyState("llm", bot.llm_config);
  setKeyState("embedding", bot.embedding_config);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const problem = $("[data-provider-problem]", form);
    const result = $("[data-provider-result]", form);
    problem.hidden = true;
    result.hidden = true;
    const payload = {};
    if (form.llm_model.value.trim()) {
      payload.llm_config = providerPayload(form.llm_model, form.llm_api_key, bot.llm_config);
    }
    if (form.embedding_model.value.trim()) {
      payload.embedding_config = providerPayload(
        form.embedding_model, form.embedding_api_key, bot.embedding_config,
      );
    }
    try {
      const updated = await api(`/bots/${bot.id}`, { method: "PATCH", json: payload });
      Object.assign(bot, updated);
      form.llm_api_key.value = "";
      form.embedding_api_key.value = "";
      setKeyState("llm", updated.llm_config);
      setKeyState("embedding", updated.embedding_config);
      renderRail();
      result.textContent = "Saved.";
      result.hidden = false;
      announce("Provider settings saved.");
    } catch (error) {
      problem.textContent = say(error.code, "The settings could not be saved.");
      problem.hidden = false;
    }
  });

  $("[data-test-provider]", form).addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const result = $("[data-provider-result]", form);
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      const report = await api(`/bots/${bot.id}/provider/test`, { method: "POST" });
      result.textContent = [
        report.llm.ok ? "Chat model answered." : `Chat model: ${say(report.llm.code)}`,
        report.embedding.ok
          ? "Embedding model answered."
          : `Embedding model: ${say(report.embedding.code)}`,
      ].join(" ");
      result.className = report.llm.ok && report.embedding.ok ? "notice" : "notice problem";
      result.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = "Test connection";
    }
  });
}

function providerPayload(modelField, keyField, existing) {
  const config = {
    provider: (existing && existing.provider) || "openai_compatible",
    model: modelField.value.trim(),
  };
  if (existing && existing.base_url) config.base_url = existing.base_url;
  // An untouched key field means "keep the stored key"; the API only replaces it
  // when the property is present.
  if (keyField.value) config.api_key = keyField.value;
  return config;
}

function setKeyState(which, config) {
  const hint = workspace.querySelector(`[data-key-state="${which}"]`);
  if (!hint) return;
  hint.textContent = config && config.has_api_key
    ? "A key is stored. Leave empty to keep it."
    : "No key stored yet.";
}

/* --- documents ----------------------------------------------------------- */

function wireUpload(bot) {
  const drop = $("[data-drop]", workspace);
  const input = $("[data-file]", drop);
  input.addEventListener("change", () => {
    upload(bot, Array.from(input.files));
    input.value = "";
  });
  for (const event of ["dragenter", "dragover"]) {
    drop.addEventListener(event, (e) => { e.preventDefault(); drop.classList.add("over"); });
  }
  for (const event of ["dragleave", "drop"]) {
    drop.addEventListener(event, () => drop.classList.remove("over"));
  }
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    upload(bot, Array.from(e.dataTransfer.files));
  });
}

async function upload(bot, files) {
  if (!files.length) return;
  const problem = $("[data-upload-problem]", workspace);
  problem.hidden = true;
  for (const file of files) {
    const body = new FormData();
    body.append("file", file);
    try {
      await api(`/bots/${bot.id}/documents`, { method: "POST", body });
    } catch (error) {
      problem.textContent = `${file.name}: ${say(error.code, "This file was refused.")}`;
      problem.hidden = false;
    }
  }
  announce(`${files.length} file uploaded.`);
  await refreshDocuments();
}

async function refreshDocuments() {
  if (!currentBotId) return;
  const page = await api(`/bots/${currentBotId}/documents?limit=100`);
  renderDocuments(page.items);
  scheduleNextPoll(page.items);
}

function renderDocuments(documents) {
  const list = $("[data-galleys]", workspace);
  if (!list) return;
  const previous = new Map(
    Array.from(list.children).map((node) => [node.dataset.id, node.dataset.state]),
  );
  list.textContent = "";
  $("[data-galleys-empty]", workspace).hidden = documents.length > 0;

  for (const document_ of documents) {
    const node = $("#tpl-galley").content.cloneNode(true).firstElementChild;
    node.dataset.id = document_.id;
    node.dataset.state = document_.status;
    $("[data-filename]", node).textContent = document_.filename;
    $("[data-meta]", node).textContent =
      `${kindOf(document_.mime_type, document_.filename)} · added ${humanWhen(document_.created_at)}`;

    const state = $("[data-state]", node);
    const headline = document.createElement("strong");
    headline.textContent = STATE_TEXT[document_.status] || document_.status;
    // The one authored moment: a galley marked set, once, when it becomes ready.
    if (document_.status === "ready" && previous.get(document_.id) &&
        previous.get(document_.id) !== "ready") {
      headline.className = "struck";
      // The stroke is visual only; a reader on reduced motion or a screen
      // reader needs the same news.
      announce(`${document_.filename} is ready to answer.`);
    }
    state.append(headline);
    if (document_.status === "failed" && document_.error) {
      state.append(document.createTextNode(` ${say(document_.error)}`));
    }
    if (document_.status === "ready") {
      state.append(
        document.createTextNode(
          document_.chunk_count === 1
            ? " 1 passage can be quoted."
            : ` ${document_.chunk_count} passages can be quoted.`,
        ),
      );
    }

    if (document_.chunk_count > 0) {
      const measure = $("[data-measure]", node);
      measure.hidden = false;
      const share = Math.min(document_.chunk_count / CHUNK_CEILING, 1);
      // A hairline at 3 of 2000 is the honest picture of how much room is left.
      $("[data-fill]", node).style.width = `${Math.max(share * 100, 0.4)}%`;
      $("[data-extent]", node).textContent =
        `${document_.chunk_count} of ${CHUNK_CEILING} passages used`;
    }

    renderDocumentActions(node, document_);
    renderTechnical(node, document_);
    list.append(node);
  }
}

function renderDocumentActions(node, document_) {
  const actions = $("[data-actions]", node);
  if (document_.status === "failed") {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "quiet";
    retry.textContent = "Try again";
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      try {
        await api(`/documents/${document_.id}/retry`, { method: "POST" });
        announce(`${document_.filename} queued again.`);
        await refreshDocuments();
      } catch (error) {
        retry.disabled = false;
        const problem = $("[data-upload-problem]", workspace);
        problem.textContent = say(error.code, "That document could not be retried.");
        problem.hidden = false;
      }
    });
    actions.append(retry);
  }
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "quiet danger";
  remove.textContent = "Remove";
  remove.addEventListener("click", async () => {
    if (!window.confirm(`Remove ${document_.filename} from this bot?`)) return;
    await api(`/documents/${document_.id}`, { method: "DELETE" });
    announce(`${document_.filename} removed.`);
    await refreshDocuments();
  });
  actions.append(remove);
}

function renderTechnical(node, document_) {
  const details = $("[data-technical]", node);
  const body = $("[data-technical-body]", details);
  const rows = [["status", document_.status], ["passages", String(document_.chunk_count)]];
  if (document_.error) rows.push(["code", document_.error]);
  rows.push(["updated", humanWhen(document_.updated_at)]);
  for (const [key, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = key;
    const dd = document.createElement("dd");
    dd.textContent = value;
    body.append(dt, dd);
  }
  details.hidden = false;
}

/* --- polling ------------------------------------------------------------- */

function scheduleNextPoll(documents) {
  stopPolling();
  const working = documents.filter((d) => d.status === "pending" || d.status === "processing");
  const note = $("[data-worker-note]", workspace);
  if (!working.length) {
    poll.quiet = 0;
    if (note) note.hidden = true;
    return;
  }
  const signature = working.map((d) => `${d.id}:${d.status}`).join("|");
  poll.quiet = signature === poll.signature ? poll.quiet + 1 : 0;
  poll.signature = signature;

  if (poll.quiet >= POLL_PATIENCE) {
    // Stop rather than poll forever: an endless spinner hides a worker that is
    // not running, and the reader deserves to know which one it is.
    if (note) {
      note.textContent =
        "Nothing has moved for a minute. The worker that reads documents may not be running — check it, then look again.";
      note.hidden = false;
      note.append(document.createTextNode(" "));
      const again = document.createElement("button");
      again.type = "button";
      again.className = "quiet";
      again.textContent = "Look again";
      again.addEventListener("click", () => { poll.quiet = 0; refreshDocuments(); });
      note.append(again);
    }
    return;
  }
  if (note) note.hidden = true;
  poll.timer = window.setTimeout(() => {
    // A hidden tab is a tab nobody is reading; resume on the next view.
    if (document.hidden) { poll.timer = null; return; }
    refreshDocuments();
  }, POLL_MS);
}

function stopPolling() {
  if (poll.timer) window.clearTimeout(poll.timer);
  poll.timer = null;
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && token && currentBotId && !poll.timer) refreshDocuments();
});

/* --- conversations ------------------------------------------------------- */

async function loadConversations(reset) {
  if (!currentBotId) return;
  if (reset) conversationPage = 0;
  const list = $("[data-conversations]", workspace);
  if (!list) return;
  const limit = 10;
  const page = await api(
    `/bots/${currentBotId}/conversations?limit=${limit}&offset=${conversationPage * limit}`,
  );
  if (reset) list.textContent = "";
  $("[data-conversations-empty]", workspace).hidden = page.total > 0;
  for (const conversation of page.items) list.append(conversationRow(conversation));

  const pager = $("[data-conversation-pager]", workspace);
  const shown = (conversationPage + 1) * limit;
  pager.hidden = shown >= page.total;
  if (!pager.dataset.wired) {
    pager.dataset.wired = "1";
    $("[data-conversations-more]", pager).addEventListener("click", () => {
      conversationPage += 1;
      loadConversations(false);
    });
  }
}

function conversationRow(conversation) {
  const item = document.createElement("li");
  item.className = "galley";
  const slug = document.createElement("div");
  slug.className = "slug";
  const who = document.createElement("span");
  who.textContent = `Visitor ${conversation.label}`;
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent =
    `${conversation.message_count} messages · last ${humanWhen(conversation.last_activity_at || conversation.started_at)}`;
  slug.append(who, meta);
  item.append(slug);

  const details = document.createElement("details");
  details.className = "technical";
  const summary = document.createElement("summary");
  summary.textContent = "Read this conversation";
  details.append(summary);
  const turns = document.createElement("ul");
  turns.className = "turns";
  details.append(turns);
  details.addEventListener("toggle", async () => {
    if (!details.open || turns.dataset.loaded) return;
    turns.dataset.loaded = "1";
    const transcript = await api(`/conversations/${conversation.id}`);
    for (const message of transcript.messages) turns.append(turnRow(message));
  }, { once: false });
  item.append(details);
  return item;
}

function turnRow(message) {
  const row = document.createElement("li");
  const who = document.createElement("div");
  who.className = "who";
  who.textContent = message.role === "user" ? "Asked" : "Answered";
  const said = document.createElement("p");
  said.className = "said";
  said.textContent = message.content;
  row.append(who, said);
  if (message.citations.length) {
    const cited = document.createElement("div");
    cited.className = "cited";
    cited.textContent = `Sources: ${message.citations
      .map((c) => (c.page ? `${c.filename} p.${c.page}` : c.filename))
      .join(", ")}`;
    row.append(cited);
  }
  if (message.status !== "completed") {
    const note = document.createElement("div");
    note.className = "cited";
    note.textContent = `This attempt ended ${message.status}.`;
    row.append(note);
  }
  return row;
}
