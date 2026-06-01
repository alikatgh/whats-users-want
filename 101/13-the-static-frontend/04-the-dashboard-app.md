# 04 — The dashboard app (app.js)

## No framework, on purpose

[static/what_users_want_cdn/assets/app.js](../../static/what_users_want_cdn/assets/app.js)
is ~1,800 lines of plain JavaScript — no React, no Vue, no build step. For a
read-only readout that must run from a bare CDN (and `file://`), a framework would
add a toolchain and a bundle for no benefit. The entire app is one IIFE around a
`state` object.

## Shape

```js
(() => {
  const state = { data: {}, charts: {}, /* … */ };
  document.addEventListener("DOMContentLoaded", init);

  async function init() {
    bindNavigation();
    bindStaticControls();
    await loadData();     // reads window.WUW_DATA (Lesson 01)
    prepareData();
    renderAll();
  }
  // … the rest …
})();
```

## Data in

`loadData()` copies `window.WUW_DATA` into `state.data`. Each key
(`summary`, `journeys`, `trends`, …) is an **array of row-objects** with string
values — the *same shape* the old `parseCsv()` produced. That's why switching from
`fetch()` to the baked bundle changed nothing downstream: the data shape stayed
identical, only its *source* changed.

## Views without a router

The page has six sections (lookup, executive, timeline, no-ban, journeys, method).
There is no router. `showSection(target)` sets `document.body.dataset.view` and
toggles `.is-active` on the matching `.view`; CSS does the showing and hiding:

```js
function showSection(target) {
  document.body.dataset.view = target;
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("is-active", v.id === target));
}
```

A single-page app in three lines.

## Rendering

Every render function builds an HTML string from a `state.data` array and assigns
it to `.innerHTML`, running injected text through `escapeHtml()`. It's deliberately
dumb — data in, HTML out, no diffing. For thousands of rows rendered once per view
switch, that is plenty fast.

## Filtering and search happen in the browser

The UID lookup, the timeline want-selection, the no-ban filters — all run over the
in-memory arrays. This is the quiet superpower of shipping *all* the data: the
"server-side query" becomes `array.filter(...)` on the client. There's no backend
because the backend's data is already in the page.

## Charts

`vendor/echarts.min.js` is bundled **locally**, not pulled from a public CDN at
runtime — the same "everything is a file you shipped" rule from Lesson 01. The
timeline and forecast charts are ECharts option objects built from `state.data`.

## The lesson

A static, read-only dashboard needs surprisingly little machinery: load embedded
data, toggle views with a CSS class, render arrays to `innerHTML`, filter in
memory, draw with a bundled chart lib. The complexity budget goes into the **data**
(Lesson 05) and the **design** (Lesson 02) — not a frontend stack.

Read next: [05 — Baking the bundle](05-baking-the-bundle.md).
