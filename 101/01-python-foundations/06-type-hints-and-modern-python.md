# Type Hints and Modern Python

## The problem

You read `latest_run() -> Path | None` and you immediately know two
things: this function returns either a `Path` or `None`, and the caller
must handle the `None` case before subscripting. Without that hint, you
have to read the whole body to learn what comes back.

You read `def first_existing(df: pd.DataFrame, names: Iterable[str]) ->
str | None:` and you know `names` can be a list, a tuple, a generator —
anything iterable — and the result might be `None`.

This is the value type hints provide: a contract you can read in three
seconds, before you read the body. The codebase does not run a type
checker; nobody is enforcing these annotations. They are still useful,
because the human reader (you) and your IDE both consume them. This
lesson covers the modern Python typing syntax used across the scripts.

## `from __future__ import annotations`

Every script in this codebase starts with the same line:

```python
from __future__ import annotations
```

[`scripts/option2_pipeline.py:48`](../../scripts/option2_pipeline.py)

[`scripts/dashboard/lib.py:38`](../../scripts/dashboard/lib.py)

[`scripts/dashboard/app.py:50`](../../scripts/dashboard/app.py)

What does it do? It changes how Python evaluates type annotations.

Without that import, an annotation like `def f() -> Path | None:` is
evaluated *at function-definition time*, when the module is first
loaded. That means:

- The names you reference (`Path`, `pd.DataFrame`, custom classes) must
  already exist when the file is parsed top-to-bottom.
- Forward references — referring to a class defined later in the same
  file — break.
- The `X | Y` union syntax, which is Python 3.10+ syntax, fails on
  Python 3.9.

With `from __future__ import annotations`, all annotations are stored
as plain strings and never evaluated at runtime. That makes them:

- Free of runtime cost.
- Free of import-order constraints.
- Compatible with newer typing syntax (`int | None`, `list[str]`)
  even on older Python versions, because the parser only checks the
  syntax tree, not the runtime evaluation.

Put it at the top of every Python file you write in 2024+. There is no
downside.

## PEP 604: `int | None` instead of `Optional[int]`

Pre-3.10, you wrote unions through the `typing` module:

```python
from typing import Optional, Union

def latest_run() -> Optional[Path]: ...
def parse_arg(value: Union[int, str]) -> int: ...
```

PEP 604 adds the `|` operator to the type system itself. The new
spelling:

```python
def latest_run() -> Path | None:
```

[`scripts/dashboard/lib.py:92`](../../scripts/dashboard/lib.py)

`Path | None` reads as "either `Path` or `None`." It is the same as
`Optional[Path]`, but shorter and more readable.

The pipeline's `optional_import` returns `Any | None`:

```python
def optional_import(module_name: str) -> Any | None:
```

[`scripts/option2_pipeline.py:193`](../../scripts/option2_pipeline.py)

Here `Any` means "any type" (an escape hatch from the type system) and
the union with `None` makes the explicit "or absent" case visible.

You can chain unions: `int | str | None` is a valid annotation meaning
"int, str, or None." The codebase rarely needs more than two-element
unions, but the syntax composes.

## PEP 585: `list[str]`, `dict[str, Any]`, `tuple[int, int]`

Pre-3.9, you imported generic versions of the builtins from `typing`:

```python
from typing import List, Dict, Tuple

def names() -> List[str]: ...
def labels() -> Dict[int, str]: ...
def coords() -> Tuple[int, int]: ...
```

PEP 585 lets you subscript the builtins directly. The codebase uses the
new spelling everywhere:

```python
def list_runs() -> list[Path]:
```

[`scripts/dashboard/lib.py:63`](../../scripts/dashboard/lib.py)

```python
def list_other_files(run_dir_str: str) -> dict[str, list[str]]:
```

[`scripts/dashboard/lib.py:171`](../../scripts/dashboard/lib.py)

```python
def load_json(run_dir_str: str, name: str) -> dict[str, Any] | None:
```

[`scripts/dashboard/lib.py:256`](../../scripts/dashboard/lib.py)

`list[Path]` is "a list whose elements are `Path` objects." `dict[str,
list[str]]` is "a dict whose keys are strings and whose values are
lists of strings." `dict[str, Any]` is "a dict whose keys are strings
and whose values can be anything" — used when you parse arbitrary JSON.

`tuple` works the same way, but with the catch that tuples can be
fixed-length or variable-length:

- `tuple[int, int]` — exactly two ints (a 2D coordinate).
- `tuple[str, ...]` — any number of strings (the `...` is the special
  ellipsis literal that means "and so on").

The pipeline's `drop_noise_columns` uses a fixed-length tuple in its
return:

```python
def drop_noise_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
```

[`scripts/option2_pipeline.py:447`](../../scripts/option2_pipeline.py)

The reader knows immediately: it returns a `(DataFrame, list of column
names)` pair. Two-element tuples are how you return "and also some
metadata I want to log" without inventing a class.

## `Iterable[str]` and other typing protocols

Sometimes you need a more general type than `list`. The pipeline's
`first_existing` accepts any iterable of strings:

```python
def first_existing(df: pd.DataFrame, names: Iterable[str]) -> str | None:
```

[`scripts/option2_pipeline.py:299-300`](../../scripts/option2_pipeline.py)

Imported as:

```python
from typing import Any, Iterable
```

[`scripts/option2_pipeline.py:60`](../../scripts/option2_pipeline.py)

The teaching comment makes the rationale explicit:

> `Iterable[str]` is from `typing`: any object you can `for` over. We
> don't need a list — a tuple, generator, or set works too.

[`scripts/option2_pipeline.py:319-320`](../../scripts/option2_pipeline.py)

The Liskov substitution principle in action: ask for the minimum
capability you actually need, not the most specific type. Callers can
pass `["uid", "UID", "uid_str"]` (a list), `("Date",)` (a one-tuple),
or `(c for c in candidates if c.startswith("status"))` (a generator)
and the function works equally well.

Other protocol-style types you might reach for:

- `Sequence[str]` — supports indexing and `len`. List, tuple, str.
- `Mapping[str, int]` — read-only dict-like.
- `Callable[[int, str], bool]` — a function taking int and str,
  returning bool.

The codebase uses `Iterable` and the concrete builtins. Reach for the
others only when you specifically need their guarantees.

## The `Any` escape hatch

`from typing import Any` gives you a type that disables type checking
for that variable. Use it when you genuinely accept anything — usually
at API boundaries with messy data.

The pipeline's `clean_text` accepts `Any` because pandas hands it
strings, NaN floats, ints, and `None`:

```python
def clean_text(value: Any) -> str:
```

[`scripts/option2_pipeline.py:243`](../../scripts/option2_pipeline.py)

The `safe_int` and `safe_float` helpers do the same:

```python
def safe_int(value: Any, fallback: int = 0) -> int:
```

[`scripts/dashboard/lib.py:467`](../../scripts/dashboard/lib.py)

Inside the function, you handle the diversity. At the boundary, `Any`
signals: "this absorbs anything you throw at me."

`Any` is the typing system's way of saying "I'm being honest that
checking has stopped here." Prefer concrete types when you can name
them; reach for `Any` only at boundaries.

## Annotating local variables

Most type hints decorate function signatures, but you can annotate
local variables too. The taxonomy builder does this for clarity:

```python
tokens: Counter[str] = Counter()
```

[`scripts/build_user_wants_taxonomy.py:430`](../../scripts/build_user_wants_taxonomy.py)

`Counter[str]` is "a Counter whose keys are strings." Without the
annotation, an IDE would have to infer the key type from usage — and
might get it wrong on the first iteration. Spelling it out helps the
reader and gives the IDE a stable hook for autocomplete.

The dashboard's `attach_friendly_titles` uses an explicit dict
annotation for a build-up dict:

```python
out: dict[int, dict[str, str]] = {}
for _, r in df.iterrows():
    try:
        wid = int(r["want_id"])
    except (TypeError, ValueError):
        continue
    out[wid] = {
        "title": str(r.get("human_title", "")).strip(),
        "summary": str(r.get("human_summary", "")).strip() if "human_summary" in df.columns else "",
    }
return out
```

[`scripts/dashboard/lib.py:748-758`](../../scripts/dashboard/lib.py)

`dict[int, dict[str, str]]` is "a dict whose keys are ints and whose
values are dicts of `str` to `str`." That single annotation tells you
the entire shape before you read the loop body.

## Why annotate when you don't run mypy?

This codebase doesn't run a type checker. There is no
`mypy.ini`, no `pyright` invocation in CI. Why bother with the hints?

Three reasons.

**Readers.** When you skim a 2000-line script, signatures with type
hints let you understand each function in three seconds. You don't
need to read the body to learn what it accepts and returns. That is the
biggest win.

**IDEs.** PyCharm, VS Code's Pylance, and the `jedi` language server
all use type hints for autocomplete and inline error checking. With
hints, your IDE warns you about `None` access, suggests valid attributes,
and offers refactor actions that respect type boundaries. Without hints,
it falls back to fuzzy guessing.

**Documentation.** Type hints are the cheapest, most maintainable form
of documentation. A docstring saying "returns a list of paths" can
drift out of sync with the code. A signature `-> list[Path]` cannot —
it lives next to the implementation and changes with it.

The cost is one line per function: a colon for each parameter, an
arrow for the return. Worth it.

## What the hints don't do

Type hints are not enforced at runtime. This works:

```python
def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback

result = safe_int("not a number", fallback="zero")  # passes a string as int
```

Python does not check the call. The function runs, `int("not a
number")` raises `ValueError`, the `except` catches it, and the
function returns `"zero"` — which violates the declared `-> int`
return type. Nobody complains.

If you want enforcement, add `mypy` (static, runs at lint time) or
`pydantic` (dynamic, runs at function-call time). The codebase chooses
neither and relies on the discipline of writing `safe_int` correctly.

## Try it

From the repo root, write a small script with rich type hints that
takes a run directory and returns a `dict[str, int]` mapping each
desire code to its ticket count. Annotate every parameter, every
return, and the local accumulator dict:

```bash
.venv/bin/python -c "
from __future__ import annotations
from collections import Counter
from pathlib import Path
import pandas as pd

def desire_counts(run_dir: Path) -> dict[str, int]:
    csv: Path = run_dir / 'enriched_tickets.csv'
    if not csv.exists():
        return {}
    df: pd.DataFrame = pd.read_csv(csv)
    counts: Counter[str] = Counter(df['primary_desire'].dropna())
    return dict(counts)

runs: list[Path] = sorted(p for p in Path('outputs').glob('option2_*') if p.is_dir())
result: dict[str, int] = desire_counts(runs[-1])
for code, n in sorted(result.items(), key=lambda kv: -kv[1]):
    print(f'{code:<35} {n:>5}')
"
```

Now make a deliberate type mismatch: declare the function to return
`list[str]` but actually return a dict. Run it. Notice that Python
doesn't complain — the hints are advisory. Then install `mypy` (`pip
install mypy`) and run `mypy that_file.py` to see the static checker
flag it.
