# 06 — Privacy on a static site

## The uncomfortable fact

On a static site, **everything you ship is downloadable.** There is no server to
check who's asking, no per-row permission, no query that returns "just your data."
The `bundle.js` sitting next to `index.html` holds every ticket; *View Source*, or
a single `fetch('/data/bundle.js')`, hands over all of it. A static site has
exactly one access control: **whether someone can reach the URL at all.**

This is the direct flip side of Lesson 01. The same property that makes the readout
trivially hostable — *all the data is right there in the files* — also means you
must treat the entire bundle as **published**.

## What that means for support tickets

This data contains ticket text, UIDs, URLs, and support notes — sensitive. So the
rules are not optional:

1. **Host only on an access-controlled, internal CDN link.** The link *is* the
   security boundary. A public URL is a public data dump. (The app says exactly
   this in its own sidebar: *"Host this only on an internal company CDN or
   access-controlled link."*)
2. **Ship the minimum.** The bake includes only the ten files the views actually
   need (`FILE_TO_KEY`), not the whole run directory.
3. **Redact at build time.** `export_static_readout.py` drops person-attribution
   columns (manager names) before they ever reach the bundle — so even with the
   file in hand, you can't say "manager X handled this ticket" (Lesson 05).

## Static vs server, stated plainly

A *server* could enforce real access control: authenticate the viewer, return only
the rows they're allowed to see, log every access. A *static site* **cannot do any
of that.** That is the price of "runs anywhere with no backend." You pay it by
deciding, up front, that **everything in the bundle is safe for everyone who has
the link** — and then making that true (redaction, minimum data, controlled
hosting).

## A checklist before you upload

- Is this going somewhere only the intended audience can reach? (Not a public bucket.)
- Did the bake strip the columns that shouldn't travel? (Check the manifest's redaction note.)
- Could any single row embarrass or expose a named person if leaked? If yes, it
  shouldn't be in the bundle.
- Do you actually need per-row text, or would **aggregates** do? Aggregates leak far less.

## The takeaway

"Self-contained and runs anywhere" (Lesson 01) and "the link is the only lock"
(this lesson) are two sides of one coin. Design the data for a world where the
whole bundle is public-to-whoever-has-the-URL — strip what shouldn't travel, ship
the minimum, host behind access control — and the readout is then both **safe and
simple.**

---

That's the end of **Module 13 — The static frontend**. You can now build a
dashboard that runs from a file or a CDN with no server, embed its data, style it
to feel calm and trustworthy, generate it from Python, and reason about what's safe
to ship.

Back to the pipeline: [Module 10 — Pipeline design](../10-pipeline-design/README.md).
