# 02 — The design system: why it feels calm

A management readout has one job before it has any other: **be trusted at a
glance.** A page that looks busy, decorated, or "designed-at-you" makes a viewer
suspicious of the numbers. So the entire visual system here is built to get out
of the way. This lesson is the handful of rules that produce that calm — and they
are *rules*, not taste. You can apply them mechanically.

Open [static/what_users_want_cdn/assets/styles.css](../../static/what_users_want_cdn/assets/styles.css)
and [scripts/build_compare_view.py](../../scripts/build_compare_view.py) (its `<style>`
block) alongside this.

## Rule 1 — Flat surfaces, hairline borders. No shadows.

Depth on a screen usually means a drop-shadow. Drop-shadows are noise: they imply
importance the content hasn't earned. We use **none**. Surfaces are separated by a
**1px hairline** in a near-neutral grey and by **whitespace** — nothing else.

```css
:root {
  --bg: #fafafa;        /* near-white, faintly warm — not stark #fff, not blue-grey */
  --surface: #ffffff;
  --line: #e8e8e8;      /* the hairline. one weight, used everywhere */
  --shadow: none;       /* the whole project: zero card shadows */
  --radius: 10px;
}
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
```

This was a real edit. The dashboard *used* to have `--shadow: 0 18px 45px …` and
gradients; re-pointing the tokens (`--shadow: none`, lighter `--line`, neutral
`--bg`) reflowed all ~6,000 lines of CSS at once. That's the payoff of putting the
look in **tokens**: one change cascades. (See Lesson 05's note on the "cascade
first" instinct.)

## Rule 2 — Hierarchy from weight and size, not color.

Look at a card in the comparison view. The labels (`money`, `trust`, the model
name) are **small, muted, sometimes uppercase**. The values are **bold and dark**.
Your eye sorts label-from-value instantly — with no color at all.

```css
.who { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
.kv .k { color: var(--muted); }   /* the label */
.kv b  { /* the value — default weight is the emphasis */ }
```

Why this matters: color is a scarce signal. If you spend it on hierarchy ("make
the heading blue"), you have none left for *meaning*. Which is Rule 3.

## Rule 3 — Color only ever means something.

In the comparison view there are exactly two uses of color, and each is a fact:

- **Blue** marks the *candidate* model's column (vs the baseline). It's an identity, not decoration.
- **A single orange tint** highlights a graded score **only when the two models disagree** on it.

```css
.col.v .who { color: var(--vk); }              /* blue = the candidate */
.d { background: var(--diff); font-weight: 650; } /* orange = "these disagree" */
```

That orange is doing real work: it turns "scan 92 cards looking for differences"
into "scan for the orange." A reader never has to wonder *why* something is
colored — color is reserved for information.

## Rule 4 — Tabular numbers, always.

The readout is full of 1–5 scores and counts. By default, proportional fonts give
digits different widths, so columns of numbers wobble and you can't compare them
vertically. One line fixes it:

```css
.num { font-variant-numeric: tabular-nums; }
```

Now `money 1 · trust 3 · urg 3` lines up perfectly card-to-card, and you can run
your eye straight down a column of scores. Monospace is reserved for *codes*
(source_row, UIDs):

```css
.sr { font-family: ui-monospace, Menlo, monospace; }
```

## Rule 5 — One repeating unit.

Every ticket is the *same* card: source text on top, two equal columns below split
by a hairline. Same padding, same order of fields, every time. Predictable rhythm
is low cognitive load — the reader learns the shape once and then only reads
*content*. Resist the urge to make the "important" cards bigger or boxed
differently; sameness *is* the design.

## Rule 6 — State never changes geometry.

Hover, focus, "active" — these change *color or background tint*, never size,
padding, border-width, or position. If a button grew on hover, the layout would
twitch. Keep motion out of the structure; the page should feel still.

## The checklist

When you add anything to one of these pages, ask:

1. Did I add a shadow or gradient? → remove it; use a hairline + space.
2. Did I use color for hierarchy? → use weight/size instead, save color for meaning.
3. Are there numbers? → `tabular-nums`. Codes? → monospace.
4. Is this a new shape, or the existing one repeated? → prefer repeating.
5. Does any `:hover`/`:focus` change geometry? → make it change only color.

Follow those six and a new view will *feel* like it belongs — because the feeling
was never about taste, it was about these rules. (They're the project's house
style; the global version lives in `~/.claude/UI_DESIGN_RULES.md`.)

Read next: [03 — Generate a page from Python](03-generate-a-page-from-python.md).
