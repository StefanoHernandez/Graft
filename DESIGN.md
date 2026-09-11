---
name: Graft
description: A self-hosted chatbot that answers only from your own documents — the admin desk where those documents live.
colors:
  desk: "oklch(0.52 0.098 238)"
  desk-deep: "oklch(0.38 0.082 240)"
  desk-line: "oklch(0.60 0.085 238)"
  desk-ink: "oklch(0.97 0.012 240)"
  desk-label: "oklch(0.955 0.02 240)"
  sheet: "oklch(0.985 0.006 85)"
  sheet-inset: "oklch(0.955 0.011 85)"
  ink: "oklch(0.24 0.012 250)"
  ink-soft: "oklch(0.47 0.014 250)"
  rule: "oklch(0.87 0.008 85)"
  rule-strong: "oklch(0.72 0.012 85)"
  pencil: "oklch(0.52 0.115 243)"
  correction: "oklch(0.50 0.185 27)"
typography:
  display:
    fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "{typography.display.fontFamily}"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "{typography.display.fontFamily}"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "{typography.display.fontFamily}"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "0.12em"
  data:
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  control: "2px"
spacing:
  hair: "0.35rem"
  tight: "0.6rem"
  row: "0.9rem"
  block: "1.5rem"
  sheet: "2.25rem"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.5rem 1rem"
  button-primary-hover:
    backgroundColor: "oklch(0.34 0.02 250)"
    textColor: "{colors.sheet}"
  button-primary-disabled:
    backgroundColor: "{colors.rule-strong}"
    textColor: "{colors.sheet}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    padding: "0.35rem 0"
  button-quiet-destructive:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    padding: "0.35rem 0"
  input-text:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.45rem 0.55rem"
  rail-item:
    backgroundColor: "transparent"
    textColor: "{colors.desk-ink}"
    typography: "{typography.body}"
    padding: "0.55rem 0.6rem"
  rail-item-current:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
  sheet:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    padding: "2rem 2.25rem 2.5rem"
    width: "54rem"
---

# Graft — design system

## Overview

**North star: the copy desk.** Documents are galleys on a working desk, not rows in a
table. A saturated working blue owns the page; documents sit on proof-paper sheets that
carry every piece of copy at full contrast. The arrangement this system exists to refuse
is the SaaS admin — left nav, card grid, coloured status badges — because that
arrangement hides the only thing the reader came for: whether a document has become
answerable, and what to do when it has not.

Two readers share the screen and it is written for the second one: the operator who
installed the instance, and the person responsible for the documents who does not know
what a chunk is. Graft is self-hosted per company, so this screen is the only manual
either of them gets.

Three rules carry more weight than any token below. **State is a sentence in the copy
flow, never a badge.** **One alarm colour exists and only a real failure may use it.**
**Nothing is enclosed** — no cards, no boxes, no dividers as grouping; rules, indentation
and marginal marks group instead.

## Colors

Strategy: **Committed.** The desk blue carries roughly 40% of the desktop viewport
(masthead, rail, and the gutter earned by capping the sheet at 54rem). It is a field, not
an accent scattered over a neutral ground.

| Role | Token | Use |
|---|---|---|
| Ground | `desk` | The desk itself: everything behind the sheets |
| Ground, deeper | `desk-deep` | Masthead strip only |
| Hairline on blue | `desk-line` | Separators inside the rail |
| Text on blue | `desk-ink`, `desk-label` | Bot names; `desk-label` is the 12px sublabel, lightened until it clears 4.5:1 on the desk |
| Paper | `sheet`, `sheet-inset` | The working sheet; the inset carries the embed snippet |
| Text | `ink`, `ink-soft` | Body and secondary copy on paper |
| Rules | `rule`, `rule-strong` | Section and row hairlines; `rule-strong` for control borders |
| Pencil | `pencil` | Marks that guide work and never alarm: caret, focus ring, selection, the measure fill, the disclosure mark |
| Correction | `correction` | **The only alarm.** A failed document's marginal rule and its state headline, and problem notices |

The pencil/correction split is the system's spine. Blue marks guide; the red one says
something broke. A destructive action is not a failure, so *Remove* and *Delete* take a
dashed underline in `ink` rather than the red.

Every rendered element was measured against its real ancestor background: the floor is
4.5:1 (3:1 for large text) and the lowest pair in the shipped build is 4.77:1.

## Typography

One family. A system sans carries headings, buttons, labels and body; the mono face is
reserved for **real data** — filenames' metadata, counts, codes, the embed snippet,
citation lists. Mono as a costume for "technical" is not part of this system.

Fixed rem scale, not fluid: `0.75 / 0.8125 / 0.9375 / 1.0625 / 1.3125 / 1.75rem`. The bot
name (`display`, 1.75rem) is the only large type on the screen; below 860px it steps down
to 1.3125rem. `title` (1.0625rem) marks document filenames. `label` is the uppercase
tracked section heading — it *is* the heading, never a kicker above one.

`font-variant-numeric: tabular-nums` is set on `body`: counts and sizes sit in columns.

## Layout

A two-column desk: a 260px rail and the sheet, `gap: 1.5rem`, `padding: 1.5rem`.

**The sheet has edges.** `max-width: 54rem` is what lets the desk read as a field rather
than as the margin left over around a panel; without the cap the blue collapses to trim
and the committed strategy dies.

Prose is capped at 68ch. Data rows and the transcript run wider.

At **≤860px** the desk becomes one column and the rail becomes a single nowrap scrolling
strip with a mask fade at the right edge, items separated by vertical hairlines. The
embed snippet moves *below* the documents at this width — a real DOM move, not CSS
`order`, so focus order and reading order stay the same thing. On a phone the first
question is whether the documents are ready; embedding is a once-per-bot action.

## Elevation & Depth

Nearly flat, and deliberately so. One shadow exists: `0 6px 18px oklch(0.2 0.06 240 / 22%)`
under the sheet — a sheet lying on a desk. Everything else separates by value and by
hairline. Elevation is declared once per element: a border **or** a shadow, never both.

## Shapes

`2px` on controls and nothing else. No pills, no 12px+ cards, no rounded panels: the sheet
and the rail have square corners because paper does. Borders are 1px hairlines; the only
1px coloured accent border in the system is the failed galley's left marginal rule, which
is the marginal mark itself.

## Components

- **Sheet** — the working surface. Square, capped, one shadow, 2rem/2.25rem padding.
- **Rail item** — a plain ruled line. The current bot inverts to paper. Never a box; the
  mobile strip separates items with `border-left`, not borders around them.
- **Galley** — one document. Slug line (filename at `title`, metadata in `data`), the
  state as a sentence, the extent measure, actions, and a `Technical detail` disclosure
  carrying the raw code. A failed galley colours its left marginal rule.
- **Measure** — a 3px rule with a `pencil` fill and `N of 2000 passages used` beside it.
  It ships for every document with passages, with a 0.4% floor so three passages still
  draw a real tick. Capacity is shown before it fails, not as an error afterwards.
- **Primary button** — ink on paper, 2px, for the one action that commits.
- **Quiet button** — text with a 1px underline that darkens on hover. Destructive variant:
  the same, dashed.
- **Disclosure** — the browser triangle is suppressed; a drawn `pencil` rule extends from
  0.5rem to 1rem when open.
- **Snippet** — the embed tag on `sheet-inset` with the copy action at its right edge.

Browser surfaces are part of the system: `::selection` (twice — one tint on the desk, one
on paper), `caret-color`, `scrollbar-color` in both zones, `:focus-visible` at 2px in
`pencil`, `text-underline-offset`.

## Motion

150ms on state transitions, `cubic-bezier(0.16, 1, 0.3, 1)`. One authored moment: when a
document reaches *ready*, its state headline strikes in once via a `clip-path` wipe over
180ms — and only on a real transition, never on first paint. The same branch announces it
to the live region, so the moment reaches a screen reader too.
`prefers-reduced-motion: reduce` collapses every duration to 1ms.

## Do's and Don'ts

- **Do** write state as a sentence a non-technical reader understands, and put the exact
  code one disclosure away.
- **Do** give every failure a terminal state and a next action. Polling stops after a
  minute of no movement and says the worker may not be running.
- **Do** keep destructive actions in ink.
- **Don't** introduce a second alarm colour, or spend `correction` on emphasis, warnings,
  or delete buttons.
- **Don't** enclose. If something needs grouping, reach for a rule, indentation or a
  marginal mark before a container.
- **Don't** add a badge, chip or pill for status. That is the arrangement this system
  exists to refuse.
- **Don't** use mono for anything that is not data.
