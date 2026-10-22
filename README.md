# codegent

`codegent` traces the lineage of files through git history. It follows renames, identifies the origin commit, summarizes authorship, and renders terminal-friendly family trees for code.

## Installation

Requires Python 3.10+ and Git with `--since-as-filter` support (Git 2.37+).

```bash
pip install -e .
python -m codegent --version
```

Optional git subcommand alias:

```bash
git config --global alias.gent '!codegent'
git gent trace src/auth.py
```

## Commands

All commands support:

```bash
--repo <path>       # repository path, defaults to current directory
--json             # machine-readable output
--no-color         # disable ANSI colors
--max-commits N    # cap history traversal, defaults to 10000
```

### Trace

```bash
codegent trace src/auth.py
codegent trace src/auth.py HEAD~5 --json
```

Shows a family tree of commits that touched the path, using `git log --follow` for rename detection.

### Ancestry

```bash
codegent ancestry src/auth.py
```

Shows the direct lineage from oldest to newest, including role, author, date, and approximate carried line count.

### Gene Map

```bash
codegent genemap src/auth.py
```

Renders a compact timeline with markers for origin, heirs, co-authors, renames, and large changes.

### Bloodline

```bash
codegent bloodline src/auth.py
```

Prints a one-card summary: origin author, age, total commits, migration count, and author diversity.

### Diff

```bash
codegent diff v1.0.0 HEAD
```

Shows file-level code transfer between two commits using git rename detection.

## Notes

`codegent` is dependency-free Python. It uses only the Python standard library and the local `git` command via `subprocess`.

Binary file changes are detected from git numstat output and are reported without line statistics. Empty repositories and missing paths produce clear errors. Large histories can be bounded with `--max-commits`.

`--max-commits` must be a positive integer; zero and negative limits are rejected.
Paths are literal filenames, including brackets and other Git pathspec metacharacters.
Relative paths resolve from the directory passed to `--repo`. Absolute paths inside
that repository are also accepted, including paths deleted from the current tree.

### Incomplete history

Shallow clones and commit limits are reported explicitly in every history view.
JSON includes `history_complete`, `origin_confirmed`, `shallow`, and `warnings`.
`origin` denotes the earliest observed commit; it is a confirmed origin only when
`origin_confirmed` is true. Net line counts are estimates, not surviving-line attribution.

### Historical tips

All history commands accept `--ref <commit-or-tag>`, for example
`codegent ancestry src/auth.py --ref v1.0.0`. Trace also retains its optional
positional commit argument; conflicting positional and named refs are rejected.

### Date windows

Use `--since 2026-01-01 --until 2026-02-01T23:59:59Z` to select commits by Git's
committer date. Values must be ISO dates or datetimes; omitted timezones mean UTC,
and date-only values mean midnight. Filtered results describe the selection and
do not claim a confirmed origin.

`--author "name or email"` selects a literal, case-sensitive author substring.
It can be combined with date windows and commit limits.

`--no-follow` inspects only the selected filename instead of following its earlier
names. JSON and text reports disclose this restricted history scope.

`--first-parent` follows the integration branch through merges, excluding individual
side-branch commits. These reports describe the selected integration history.

`--rename-threshold 80` sets Git's rename similarity percentage (1-100, default 50)
for both history and diff. Rename detection is heuristic; stricter values can stop
a lineage at a heavily edited rename. JSON records the selected threshold.

`--timeout 10` limits each Git subprocess to a positive, finite number of seconds
(default 30). Timed-out operations return a readable error, including in JSON mode.

`--ignore-whitespace` ignores whitespace when computing textual change statistics
and diffs. History may still list commits with no remaining textual changes.

`--mailmap` canonicalizes history author names and emails using Git's current
mailmap configuration. Without it, history reports preserve recorded identities.

### Author summaries

`codegent authors src/auth.py --sort churn --limit 10 --json` aggregates commit
counts, additions, deletions, binary changes, and first/last author dates per
identity. Sorting supports `commits`, `churn`, and `name`. All history filters apply.
Churn measures changed lines, not quality or current ownership.

### Repository hotspots

`codegent hotspots src --sort churn --min-commits 2 --limit 20 --json` ranks
historical paths by changed lines or commit count. Omit `src` to scan the repository.
History date, author, ref, first-parent, and commit-limit options apply. Binary
changes are counted separately. Historical names remain separate across renames;
churn is a triage signal, not evidence of defects.

### Surviving-line attribution

`codegent owners src/auth.py --ref HEAD --lines 10:40 --json` uses Git blame to
report the authors of surviving text lines, percentages, and contributing commit
IDs. The inclusive line range is optional. It reads committed content, excluding
uncommitted edits. Identities follow Git blame's mailmap behavior. Binary files
are rejected; this is line attribution, not code quality or legal ownership.

`codegent diff v1.0.0 HEAD --path src --path README.md` restricts a comparison to
repeatable literal file/directory paths. Git detects renames within that selected
path set; including both old and new paths preserves cross-directory comparisons.

`diff --summary` emits aggregate file/status counts, text additions/deletions, and
binary-file counts. Full diff JSON also includes the same `summary` object.
Binary changes are counted as files, not invented line counts.

### Saving reports

`--output report.json --json` writes UTF-8 reports via a temporary file and atomic
replacement. Successful exports replace existing files; failed report generation
preserves them. Parent directories must exist. File exports disable ANSI colors.
Omit `--output` or use `--output -` for stdout.

`--markdown --output report.md` exports any report as portable Markdown tables,
including history warnings. Repository text is escaped for HTML and table syntax.
Choose one of `--markdown` and `--json`.

Terminal and Markdown reports escape control characters and bidirectional override
characters in repository-provided text. JSON preserves original strings with JSON
escaping, including unusual filenames.

Trace boxes truncate long fields by terminal cells, accounting for CJK wide and
combining characters. `--no-color`, presence of `NO_COLOR`, and `TERM=dumb`
disable color, including when `CLICOLOR_FORCE` is set.

### Automation and errors

Exit codes: 0 for success (including a consumer closing a stdout pipe), 1 for
Git/runtime/export errors, and 2 for invalid CLI arguments. `--json` also formats
argument errors as JSON on stderr. Flags unsupported by a command are rejected
instead of silently ignored. Global options can appear before or after the command.

Owners reports disclose shallow-clone blame boundaries and support
`--ignore-whitespace`. Git color, signature-display, and log-encoding settings
cannot inject formatting into structured history parsing.

CI exercises the real-repository suite on Linux and macOS with Python 3.10 and
3.12, then builds a wheel and runs all eight installed commands in text, JSON,
and Markdown outside the checkout. To repeat the installed-package check locally:

```bash
python -m pip wheel --no-deps --wheel-dir dist .
python -m venv /tmp/codegent-check
/tmp/codegent-check/bin/python -m pip install --no-deps dist/*.whl
python scripts/smoke_installed.py /tmp/codegent-check/bin/codegent
```

Repository selection ignores inherited `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`,
`GIT_COMMON_DIR`, and `GIT_PREFIX` overrides so `--repo` remains authoritative.

File lineage commands reject directory tips; use `hotspots DIRECTORY` for
repository activity rather than combining several files into a single lineage.

History reports record both the requested ref and its immutable `resolved_ref`
commit ID, making saved results auditable after branches or tags move.

Diff reports, including `--summary`, preserve `resolved_a`, `resolved_b`, and
whitespace/rename settings alongside the requested comparison refs.
