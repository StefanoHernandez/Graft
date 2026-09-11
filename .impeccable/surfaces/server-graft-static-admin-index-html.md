---
version: 1
slug: "server-graft-static-admin-index-html"
primary_target: "server/graft/static/admin/index.html"
related_targets: ["server/graft/static/admin/app.js","server/graft/static/admin/style.css"]
---

## Direction contract

THESIS: Documents are galleys on a working copy desk, not rows in a table. The screen
refuses the SaaS admin arrangement — left nav, card grid, coloured status badges — because
that arrangement hides the one thing that matters here: whether a document has actually
become answerable, and what to do when it has not.

OWN-WORLD: A saturated working blue owns the page ground and the rail; documents sit on
warm proof-paper sheets that carry every piece of copy at full contrast. Ink near-black for
text, one correction red that exists **only** for a real failure and appears nowhere else,
a blue pencil for marks that guide work but never alarm. No enclosure: no cards, no boxes,
no dividers as grouping — rules, indentation and marginal marks group instead. Type is a
system sans at a fixed rem scale with one mono face reserved for real data (codes, counts,
keys). Recognizable with all content removed by: blue ground, paper sheet, ruled column,
a single red mark.

STORY: The reader arrives asking "did last night's uploads work, and can I put this on the
site yet?" They see each document's state written in the copy flow, not in a badge; they
see chunk extent as a filled measure against the hard limit; they copy one script tag from
a sheet of its own; and when something failed they read a plain sentence naming the problem
and the next action, with the exact code one disclosure away.

FIRST VIEWPORT: Masthead strip in deep blue across the top carrying the instance name and
the sign-out action. Below it, a blue desk. Left, a 260px rail listing bots as plain ruled
lines, the current one inverted to paper. Right, the working sheet: the bot's name as the
only large type on the screen, then the embed snippet in its own inset sheet with a copy
action at its right edge, then the galley column — one block per document with its slug
line, its state printed in the flow, and its extent measure. The primary action, "Aggiungi
documenti", sits at the head of the galley column where the reader's eye already is.

FORM: The Copy Desk (galley proof). Candidate 6 of the ordered grounded list; seed key
a549b7b3. Raised by five named donations from challengers it beat: complete record per row
(sneaker box stacks), exactly one alarm colour (Game Boy four-shade field), no enclosure
(cracktro scroller queue), states printed in the flow rather than as chrome (phosphor
terminal), capacity shown as fill before failure (cassette j-card).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review,
the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Scope

The authenticated admin surface at `/admin/`, Operate mode. Sign in, bots, provider
configuration, document upload and its lifecycle, the embed snippet, conversation reading.

## Audience and job

Two readers, written for the second: the operator who installed the instance, and the
person responsible for the documents who does not know what a chunk is. Self-hosted, so
this screen is the only manual either of them gets.

## Constraints carried from PRODUCT.md

- Vocabulary is translated by default; the exact code is one disclosure away, never hidden.
- Ingestion is asynchronous and fails normally; every failure reaches a terminal state with
  a next action, and nothing spins forever.
- The admin token lives in memory only — a refresh means signing in again.
- Uploaded documents are quoted to anonymous visitors; the upload surface must say so
  before someone uploads the wrong file.
- Changing embedding configuration with documents present is refused (409); rotating the
  key is not.

## Memorable moment

A galley being marked set: when a document reaches "pronta a rispondere", the state line is
struck in once with an ink stroke, under 200ms, and never again. Reduced motion swaps it
for an instant change.

## Unresolved

Empty-instance onboarding (first bot, first document) is designed here but has no live
first-run test yet; the browser pass covers it at desktop and mobile only.
