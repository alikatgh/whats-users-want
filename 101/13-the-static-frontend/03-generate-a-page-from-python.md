# 03 — Generate a page from Python

## The goal

One `.html` file with the data *inside* it — no build tool, no templating engine,
no `node_modules`. [scripts/build_compare_view.py](../../scripts/build_compare_view.py)
produces the DeepSeek-V4-vs-Mistral comparison view in ~250 lines of Python: a
single, emailable, self-contained page.

## The pattern: a template string with a placeholder

The whole HTML page — CSS, markup, and render code — lives in Python as one big
string with a marker where the data goes:

```python
TEMPLATE = """<!doctype html><html>…<style>…</style>…
<script>const DATA=/*DATA*/;
  /* …render code… */
</script></html>"""
```

To fill it in, serialize the data to JSON and substitute:

```python
payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
html = TEMPLATE.replace("/*DATA*/", payload)
out.write_text(html)
```

### Why a `/*DATA*/` placeholder and not an f-string?

The template is *full* of `{` and `}` — every CSS rule, every JS object literal. A
Python f-string or `str.format()` would try to interpret all of them and choke.
A plain placeholder you `.replace()` sidesteps the entire problem. (This is a
genuinely useful trick any time you generate code-with-braces from Python.)

## Building `data`

`data` is a normal dict assembled with pandas — Module 02 territory:

- `rows`: the two extraction CSVs joined to the ticket text on `source_row`, each
  row carrying `{sr, ticket, m, v, hasDiff}`.
- `summary`: dominance + entropy per graded field (the chips at the top).

Nothing exotic — read CSVs, join, shape into dicts, hand to `json.dumps`.

## The one security line

```python
.replace("</", "<\\/")
```

Ticket text is arbitrary user input. If a ticket literally contained the characters
`</script>`, embedding it raw would **close the script tag early** and break the
page (or open an injection hole). Escaping `</` to `<\/` *inside a JS string* is
invisible to the data and shuts that door. (You only need this when the data is
inline in HTML. The dashboard's `bundle.js` is a separate `.js` file, so it
doesn't — there's no surrounding `</script>` to escape from.)

## The render is plain JS, in the template

The template's `<script>` reads `DATA`, builds DOM with template strings, and runs
every injected string through a tiny `esc()` helper. No virtual DOM, no
reactivity. For a read-only view, one `innerHTML` pass is all it needs.

## Inline vs separate file — when to use which

- **Inline** (this script): ultimate portability — *one file*. Best for a small,
  shareable artifact (the 95 KB comparison view you can drop in a chat).
- **Separate `bundle.js`** (the dashboard — Lesson 05): keeps a big payload out of
  the HTML and lets you rebuild the data without touching the shell. Best for the
  ~10 MB management readout.

Both are "self-contained" in the way that matters (Lesson 01): no `fetch()`, runs
anywhere.

Read next: [04 — The dashboard app](04-the-dashboard-app.md).
