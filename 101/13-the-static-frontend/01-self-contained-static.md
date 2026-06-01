# 01 — Self-contained static: why there is no server

## The constraint

The readout management sees can only be hosted on a **CDN**. A CDN is a file
server and nothing more: it hands out `index.html`, `app.js`, `styles.css`, and
whatever else you upload, over `https://`. It will not run Python, it has no
database, it cannot execute a query. Whatever the page needs, it must already be
*in the files you uploaded*.

That rules out the obvious dashboard shape (a backend that answers requests). It
even complicates the simple shape (a page that reads CSV files), as we'll see.

## The trap: `fetch()` and `file://`

The first version of the dashboard loaded its data the natural way — it fetched
CSV files at startup:

```js
const response = await fetch("./data/longitudinal_user_journeys.csv");
const text = await response.text();
```

This works on a real `https://` CDN. But it has two sharp edges:

1. **It breaks when you open the file directly.** Double-click `index.html` and
   the address bar shows `file:///Users/…/index.html`. Now `fetch("./data/…csv")`
   fails: browsers treat every `file://` page as its own "unique origin" and
   block it from reading sibling files. You get `net::ERR_FILE_NOT_FOUND` and a
   blank page. (We hit exactly this — the app even printed *"Open this readout
   through http://, not file://"* as a guard.)
2. **It depends on the host serving every sibling file correctly** — right paths,
   right MIME types, no redirects. More moving parts that can go wrong on a CDN
   you don't fully control.

The lesson: **`fetch()` of local files is a server feature in disguise.** If you
truly have only static hosting, leaning on it is fragile.

## The fix: bake the data into the page

If the page can't *fetch* its data, **embed** it. There is nothing to load at
runtime — the data ships *inside* the files. Two ways to do it, both used in
this repo:

### A. A `<script>` that defines a global (the dashboard)

`scripts/export_static_readout.py` reads the run's CSV/JSON and writes one
JavaScript file, `data/bundle.js`:

```js
window.WUW_DATA = { "summary": [ {…}, {…} ], "journeys": [ … ], … };
```

`index.html` loads it **before** the app:

```html
<script src="./data/bundle.js"></script>
<script src="./assets/app.js"></script>
```

And `app.js` simply reads the global instead of fetching:

```js
async function loadData() {
  if (!window.WUW_DATA) throw new Error("data/bundle.js is missing");
  state.data = window.WUW_DATA;
}
```

### B. Inline data, single file (the comparison view)

`scripts/build_compare_view.py` goes further: it drops the data *directly into the
HTML* as a `<script>const DATA = {…}</script>`. The result is **one file** with
zero dependencies — the whole comparison view is a single `.html` you can email.

## Why `<script>` works where `fetch()` doesn't

This is the key insight, and it's easy to miss:

> A `<script src>` (or an inline `<script>`) is **not** subject to the
> same-origin restriction that blocks `fetch()` on `file://`. Browsers have always
> let a page load and execute script files alongside it, including from `file://`.
> Only `fetch()`/`XMLHttpRequest` of local files is blocked.

So by moving the data from "something we `fetch()`" to "a script the page loads,"
the page runs **identically** whether it's opened as `file://`, served by
`python -m http.server`, or hosted on the CDN. The `file://` guard could be
deleted — there's no longer anything that breaks there.

## What you gain, what you pay

**Gain:** the deliverable is now *just a folder*. Open `index.html`, or upload the
folder — same behavior everywhere, no server, no CORS, no MIME surprises. You can
hand someone the folder in a zip and it works.

**Pay:** the data is downloaded in one chunk. Our `bundle.js` is ~10 MB (it was
~6 MB as CSVs; JSON is chattier). For an internal tool loaded once that's fine —
and the CDN gzips it to ~1–2 MB over the wire. If it ever mattered, you'd trim
the heaviest columns before baking (`build_data` in `export_static_readout.py`
is where you'd do it).

## The mental model to keep

- **A CDN serves files. So everything the page needs must be a file you uploaded.**
- **`fetch()` of local data is a hidden server dependency.** Embed instead.
- **Script tags load anywhere; `fetch()` of `file://` does not.** That's the whole
  trick.
- The build step's job is therefore not "copy CSVs next to the HTML" — it's
  **"turn the data into a script the page already has."**

Read next: [02 — The design system](02-the-design-system.md) — why the page also
*feels* calm, not just *works* everywhere.
