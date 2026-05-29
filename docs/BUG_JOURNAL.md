# Bug Journal

**Read this before debugging.** Every fix here taught a generalizable lesson.
The top section is the cheat-sheet; the chronological log has the receipts.

When you fix a bug, append an entry. **Same commit as the fix.** Five lines
max per entry. No drift.

Global rules: `~/.claude/CLAUDE.md`.

---

## Patterns to scan for FIRST

Before reproducing, grep this list for the shape of your bug.

<!-- Add bullets as you discover patterns. Examples to cannibalize:

1. **String-literal drift across files.** Same string in 2+ places that
   must agree but no enforcement. Examples: cache version, JS payload
   schema vs route schema, dict key names emitted by producer vs read by
   template, `url_for('blueprint.X')` vs the actual view function's name.
   Fix at root: one constant, importable.

2. **Field-name drift between producer and consumer.** Producer dict has
   `activity_date`, template reads `activity.created_at`. Hunt every
   `{{ obj.X }}` — confirm `X` is a real key/attribute in the producer.

3. **Ruff between sequential edits.** Adding an import in edit 1 that
   will only be referenced after edit 2 lands. Ruff prunes it as unused
   between the edits. Mitigation: write the usage first, OR multi-line
   the import tuple with another already-used name.

4. **Early-return gates that catch too much.** `if !X return` skips
   features unrelated to X. Mitigation: gate the specific call, not the
   whole init.

5. **`render_template()` test ≠ route call.** Template can render green
   while the route 500s on a NameError/BuildError before render is
   reached. Drive the actual route handler.

6. **`cache.set(..., timeout=0)` means forever** in Flask-Caching, not
   "use default". Always pass an explicit positive TTL.

-->

---

## Reusable tools

Add entries here for any reusable harness you build in `scripts/`. Format:
script name → one-line "what bug it was built to catch".

<!-- Examples:
- `scripts/render_dashboard.py` — drives the real `main.dashboard` view
  via `test_request_context + login_user`. Catches route-level NameError
  /BuildError that `render_template()` alone misses.
-->

---

## Chronological log

Newest first. Five lines max per entry. File:line citations beat prose.

<!-- Template:

### YYYY-MM-DD · Short title
Symptom: one line.
Cause: one line.
Fix: file:line — what changed. Commit `SHA`.
**Lesson:** pattern # from above, or new generalization.

-->

---

## Update protocol

1. Fix the bug.
2. Append a 5-line entry under "Chronological log" (newest first).
3. If the lesson is new, add a "Patterns to scan for FIRST" bullet.
4. Commit the fix + the journal entry **together**. Same SHA.

Skip step 2 and the journal decays. Don't.
