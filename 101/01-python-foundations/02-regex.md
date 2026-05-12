# Regular Expressions

## The problem

You have 6,728 support tickets in `data_2may.csv`. The "Question" column is
free text written by users in three or four different languages, mixed
casing, with stray URLs, screenshot links, room IDs, dates, and bilingual
category labels like `"咨询信息Consulting info"`. You need to count how
many tickets carry a URL, how many mention a ban, how many include a 14-digit
UID, and which prefix to strip from `"咨询信息Consulting info"` to get
just `"Consulting info"`.

`str.contains` and `in` cannot do this. You need patterns. Patterns mean
regular expressions, and the `re` module is the standard library for them.
This lesson walks the regex constants at the top of
`scripts/option2_pipeline.py`.

## Why `re.compile` and why module-level

Look at the comment block that introduces the regex constants:

```python
# Every regex below is compiled ONCE at import time with re.compile(...). That
# matters: re.compile pre-parses the pattern into a state machine; we then
# .search() / .findall() it across all 6,728 tickets without re-parsing.
```

[`scripts/option2_pipeline.py:68-77`](../../scripts/option2_pipeline.py)

Compilation parses the pattern string into a finite-state machine. The cost
is not large for one regex, but doing it 6,728 times per pattern is wasteful,
and there are 15+ patterns in this file. Compiling once at import time lets
the rest of the pipeline call `.search`, `.findall`, and `.sub` against an
already-built object.

A second consequence: putting compiled patterns at module top makes them
shared, named constants. Other modules can `from option2_pipeline import
URL_RE` if they need the same pattern. You stop scattering string literals
through the codebase.

## Raw strings: `r"..."`

Every pattern is wrapped in `r"..."`:

```python
URL_RE = re.compile(r"https?://\S+", re.I)
```

[`scripts/option2_pipeline.py:81`](../../scripts/option2_pipeline.py)

The `r` prefix is a raw string. Inside a raw string, backslashes do not
trigger Python's own escape sequences (`\n`, `\t`, `\\`). That matters
because regex syntax uses backslashes for *its own* escapes (`\b` for word
boundary, `\s` for whitespace, `\d` for digit). Without the `r`, Python
would try to interpret `\b` as the backspace character and your regex would
silently break.

Always write regex patterns with `r"..."`. It is the single biggest source
of "why doesn't my regex match" bugs.

## `re.IGNORECASE` and the `re.I` shorthand

The same line ends with `re.I`. That is a flag passed to `re.compile`. `re.I`
is the short alias for `re.IGNORECASE` and makes `[A-Z]` and `[a-z]` match
each other. With `re.I`, the pattern `"BAN"` matches `"ban"`, `"Ban"`, and
`"BAN"` indifferently.

Flags can be combined with `|`. `re.I | re.M` would be case-insensitive
multiline. The `re.VERBOSE` flag, which lets you write whitespace and `#`
comments inside the pattern for readability, shows up later in the file at
[`scripts/option2_pipeline.py:438-444`](../../scripts/option2_pipeline.py).

## Character classes: `[A-Z]`, `[-/.]`

A character class in square brackets matches one character from a set:

```python
TIMESTAMP_RE = re.compile(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?\b")
```

[`scripts/option2_pipeline.py:92`](../../scripts/option2_pipeline.py)

Read it left to right. `\b` is a word boundary. `20\d{2}` is the year:
literal `20` followed by exactly two digits. `[-/.]` is a character class
matching any one of dash, forward slash, or dot — this dataset has all
three written by users in different locales. `\d{1,2}` is one-or-two
digits for month and day. `[ T]` allows either a literal space or the ISO
`T` between the date and the time.

The class `[a-z0-9]` in `ROOM_ID_RE` works the same way:

```python
ROOM_ID_RE = re.compile(r"\b(?:bg|sg|cg|voice|room|channel|group)[._:-]?[a-z0-9][a-z0-9._:-]{5,}\b", re.I)
```

[`scripts/option2_pipeline.py:100`](../../scripts/option2_pipeline.py)

`[._:-]?` is a character class matching one of the four separator
characters, made optional by the trailing `?`. `[a-z0-9]` matches one
alphanumeric. `[a-z0-9._:-]{5,}` matches five or more of the alphanumeric-
or-separator class. Inside a character class, hyphens that lead or trail
are literal (no need to escape).

## Anchors: `\b`

`\b` is a zero-width assertion that matches the empty position between a
word character (letter, digit, underscore) and a non-word character (or
start / end of string). It is what stops `BAN_REASON_RE` from matching
`"ban"` inside `"Albania"`:

```python
BAN_REASON_RE = re.compile(
    r"\b(?:ban|banned|block|blocked|blacklist|unban|quick unban|insults?|personal attacks?|severe|violation|abuse|scam|fraud|punishment|kick|source|reason)\b",
    re.I,
)
```

[`scripts/option2_pipeline.py:109-112`](../../scripts/option2_pipeline.py)

The `\b` at start and end pins the match between a non-word and a word
character on each side. `"Albania"` has no word boundary right before the
`b`-a-n substring (it is in the middle of a word), so it does not match.

Note also `insults?`. The `?` after `s` makes the `s` optional, matching
both `"insult"` and `"insults"`.

## Alternation: `|`

The `|` operator is "or" in regex. `(?:bg|sg|cg|voice|room|channel|group)`
matches any one of those literal strings. Alternation tries the alternatives
left to right and takes the first match, so longer alternatives that share
a prefix with a shorter one should be listed first. `BAN_REASON_RE` uses
that order: `banned` before `ban`, `blocked` before `block`.

`USER_CLAIM_RE` shows alternation across whole phrases:

```python
USER_CLAIM_RE = re.compile(
    r"\b(?:i did nothing|did absolutely nothing|without reason|no reason|by mistake|mistake|unfair|wrongly|false|i don't know|dont know|do not understand|why was i|why i was|i was banned|i got blocked|not guilty|didn't do|did not do)\b",
    re.I,
)
```

[`scripts/option2_pipeline.py:117-120`](../../scripts/option2_pipeline.py)

Multi-word phrases work because `\b` anchors only at the outer ends; spaces
inside the phrase are literal characters. `dont` (no apostrophe) and
`don't` are both listed because users genuinely write both.

## Non-capturing groups: `(?:...)`

You will see `(?:...)` everywhere in this file. Compare:

- `(...)` is a *capturing* group. The matched text is stored in
  `match.group(1)` and counts against the back-reference numbers (`\1`).
- `(?:...)` is a *non-capturing* group. Same grouping behaviour for
  alternation and quantifiers, but the engine does not save the match.

Non-capturing groups are slightly faster and keep `findall` results clean.
If you only need the group for `|` alternation or for applying a quantifier
to a sub-pattern, use `(?:...)`. Capturing groups are for the cases where
you actually want to extract the inner text.

`IMAGE_RE` uses two of them:

```python
IMAGE_RE = re.compile(r"https?://\S+?\.(?:jpg|jpeg|png|webp|gif)(?:\?\S*)?", re.I)
```

[`scripts/option2_pipeline.py:88`](../../scripts/option2_pipeline.py)

`(?:jpg|jpeg|png|webp|gif)` groups the extension alternation so the dot
before it applies. `(?:\?\S*)?` is an outer non-capturing group made
optional by the trailing `?` — it matches a query string (`?foo=bar`)
*if present*, otherwise contributes nothing.

The inner `\S+?` is a *lazy* quantifier (the `?` after `+`). It matches as
few non-whitespace characters as possible. Without lazy matching the URL
match would extend past the first image extension and grab anything that
follows.

## Long IDs and money: more practice

A few more patterns to wire your eyes to the syntax:

```python
LONG_ID_RE = re.compile(r"\b\d{12,18}\b")
```

[`scripts/option2_pipeline.py:105`](../../scripts/option2_pipeline.py)

`\d{12,18}` is "twelve to eighteen digits." Empirically that is the band
where Bigo UIDs and case IDs live, narrow enough to exclude phone numbers
and quantity counts.

```python
MONEY_RE = re.compile(r"\b(?:money|withdraw|withdrawal|salary|cash|payment|pay|payout|diamonds?|beans?|recharge|top.?up|seller|dealer|reseller|host salary|income|earn)\b", re.I)
```

[`scripts/option2_pipeline.py:124`](../../scripts/option2_pipeline.py)

`top.?up` matches `topup`, `top up`, or `top-up`. `.` is "any single
character" and `?` makes it optional, so `top.?up` is "top, then zero or
one of any character, then up." Real user text contains every variant.

## Lookahead: `(?=...)` and the CJK prefix walkthrough

The most interesting pattern in the file is the one that strips bilingual
prefixes:

```python
CJK_DUP_PREFIX_RE = re.compile(r"^[一-鿿　-〿&\s]+(?=[A-Za-z])")
```

[`scripts/option2_pipeline.py:390`](../../scripts/option2_pipeline.py)

Walk it slowly.

`^` anchors the match to the start of the string. The pattern can only
match at position zero.

`[一-鿿　-〿&\s]+` is a character class with two Unicode ranges and two
single characters.

- `一-鿿` is the CJK Unified Ideographs block (`U+4E00` through `U+9FFF`),
  which covers most modern Chinese characters.
- `　-〿` is the CJK Symbols and Punctuation block, including the
  ideographic space `　` and other fullwidth marks.
- `&` is a literal ampersand, which appears between the Chinese and
  English in strings like `"解封&封禁 Unblocking & Banning"`.
- `\s` is the whitespace shorthand: spaces, tabs, newlines.

`+` makes the whole class repeat one or more times. So far the regex
matches "a leading run of CJK chars, CJK punctuation, ampersands, and
whitespace."

Then `(?=[A-Za-z])`. That is a *lookahead*. A lookahead is a zero-width
assertion: the engine checks that what follows matches the inner pattern,
but consumes no characters. Here the assertion is "the next character must
be an ASCII letter."

Why zero-width matters: the function uses `.sub("", value)` to strip the
matched prefix. If the lookahead consumed the Latin letter, that letter
would also be stripped, and `"咨询信息Consulting info"` would become
`"onsulting info"`. Because the lookahead is zero-width, only the CJK
run gets removed and the `C` survives.

The strip function itself is short:

```python
def strip_cjk_dup_prefix(value: Any) -> str:
    if not isinstance(value, str):
        return value if value is not None else ""
    return CJK_DUP_PREFIX_RE.sub("", value).strip()
```

[`scripts/option2_pipeline.py:393-430`](../../scripts/option2_pipeline.py)

`CJK_DUP_PREFIX_RE.sub("", value)` replaces every match (here at most one,
because the pattern is anchored at `^`) with an empty string. The lookahead
also makes the regex safe for purely Chinese values like `"已解决"`: with
no Latin letter anywhere, the lookahead can never be satisfied, the regex
does not match, and `.sub` returns the original string unchanged.

The full set of behaviours:

- `"咨询信息Consulting info"` → match `"咨询信息"` → result `"Consulting info"`.
- `"解封&封禁 Unblocking & Banning"` → match `"解封&封禁 "` → result `"Unblocking & Banning"`.
- `"已解决"` → no match (no Latin letter) → result `"已解决"` unchanged.
- `"Consulting info"` → no match (no leading CJK) → unchanged.

One regex covers all four cases.

## When to use `re.IGNORECASE`, `findall`, `search`, and `sub`

Reach for the right method:

- `pattern.search(text)` — does any match exist anywhere? Returns a match
  object or `None`. This is what powers boolean flags like
  `has_url = URL_RE.search(text) is not None`.
- `pattern.findall(text)` — every non-overlapping match as a list. The
  pipeline uses `URGENCY_RE.findall(s)` to *count* urgency cues in
  [`scripts/option2_pipeline.py:147`](../../scripts/option2_pipeline.py).
- `pattern.sub(replacement, text)` — replace every match. The CJK strip
  uses this.
- `pattern.fullmatch(text)` — does the entire string match? Used in
  `drop_noise_columns` at
  [`scripts/option2_pipeline.py:493`](../../scripts/option2_pipeline.py)
  to detect numeric-only tally columns.

## Try it

From the repo root, copy a small sample of the dataset and extract every
room ID and long UID:

```bash
.venv/bin/python -c "
import re, pandas as pd
ROOM_ID_RE = re.compile(r'\b(?:bg|sg|cg|voice|room|channel|group)[._:-]?[a-z0-9][a-z0-9._:-]{5,}\b', re.I)
LONG_ID_RE = re.compile(r'\b\d{12,18}\b')
df = pd.read_csv('data_2may.csv', dtype=str, keep_default_na=False).head(200)
text = ' '.join(df['Question'].fillna('').tolist())
print('room IDs found:', ROOM_ID_RE.findall(text)[:10])
print('long UIDs found:', LONG_ID_RE.findall(text)[:10])
"
```

Then add a third pattern of your own that finds every email address in the
sample (`r'[\w.+-]+@[\w-]+\.[\w.-]+'` is a starting point) and verify the
matches are sensible.
