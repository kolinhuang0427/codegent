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

Common output and repository options:

```bash
--repo <path>       # repository path, defaults to current directory
--json             # machine-readable output
--no-color         # disable ANSI colors
--markdown         # portable Markdown report
--csv              # tabular rows and report metadata
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
3.12, then builds a wheel and runs all nineteen installed commands in text, JSON,
Markdown, and CSV outside the checkout. To repeat the installed-package check locally:

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

Net carried-line estimates and origin age are `null` when the necessary complete
baseline is unavailable. Binary transitions also make cumulative line estimates unknown.

`--grep "literal text"` filters history-based reports by commit-message substring,
including message bodies. It combines with date and author filters.

`hotspots --exclude "vendor/*" --exclude "build/*"` removes root-relative
path globs from the ranking. These patterns filter report rows; traced paths remain literal.

`hotspots --current-only` keeps paths present at the selected commit, excluding
deleted historical names. `--ref` controls the tree used for this filter.

`authors --group-by email` combines recorded name variants sharing an email
address. JSON retains the original `identities` in each group. Identity grouping
remains the default; `.mailmap` is still available for explicit alias mappings.

`authors --min-commits 3 --limit 10` focuses a contribution report while retaining
total, matching, displayed, and omitted author counts so filtered rows stay explicit.

`timeline [PATH] --period day|month|year` groups commit activity by UTC author
date, including distinct authors/files and text/binary change counts. History
filters still use their documented Git committer-date semantics.

`cochange FILE --min-shared 2 --limit 10` ranks paths changed in the same commits
as a literal historical filename. Rename entries match either side without treating
the two names as separate companion files. Co-occurrence is not a dependency claim.

`files [PATH] --ref COMMIT --limit 1000` browses a committed tree without
checking it out. Reports include literal paths, modes, object types/IDs, blob sizes,
and explicit entry-count truncation; submodule sizes are unknown rather than zero.

`source FILE --ref COMMIT --lines 10:40 --max-bytes 1048576` previews committed
text without changing the checkout. JSON preserves selected content and line
endings; display formats use numbered, escaped lines. Binary or oversized blobs
are rejected before preview, and the size limit applies before line selection.

`diff BASE TARGET --merge-base` compares the unique common ancestor to TARGET,
matching a branch-review view. Requested refs and effective immutable comparison
commits are recorded separately. Unrelated histories or multiple merge bases fail explicitly.

`diff --find-copies` enables Git copy detection, including unchanged source
files. Copies carry `copied_from`/`copied_to`, distinct from rename metadata.
This optional search uses the configured similarity threshold and can cost more on large trees.

`diff --status added --status deleted` filters comparison rows and summaries
together. `total_changed_files` retains the pre-filter count, and the unfiltered
Git stat is omitted so it cannot contradict the selected rows.

`--newest-first` reverses the presentation of file-history entries in text, JSON,
and Markdown. Origin/latest semantics and chronological line calculations remain
unchanged; JSON records the selected `order`.

`--ascii` replaces terminal drawing glyphs with plain ASCII and disables color.
Unicode filenames and messages remain intact; use a UTF-8 terminal or file export
for non-ASCII repository content.

`--json --compact` emits each complete report on one line, with the same
structured data as indented JSON. It works with stdout and atomic file exports.

`--output report.json --json --no-clobber` atomically creates a new export
without replacing an existing destination, including during concurrent writes.
A file destination is required; temporary export files are cleaned up on failure.

Replacing an existing regular report file preserves its access permission bits.
New reports use restrictive temporary-file permissions; special mode bits are not copied.

`doctor --json` reports Git/Python/package versions, committed HEAD, shallow
state, object format, and worktree cleanliness without changing files. Empty
worktrees are supported. Diagnostics do not expose remote URLs or credentials.

`owners FILE --ignore-revs-file .git-blame-ignore-revs` asks Git blame to ignore
listed mechanical commits. Relative file paths resolve from `--repo`; the selected
file and whitespace mode are recorded in JSON. Reattribution follows Git heuristics.

`owners --detect-moves` enables Git blame within-file block-move detection
(`-M`). JSON records the mode; this remains heuristic attribution, not proof of
semantic authorship. It combines with whitespace and ignored-revision options.

`owners --max-bytes N` checks blob size before reading attribution content or
selecting lines. Ownership and source previews share a 1 MiB default text-blob
bound; directory objects and binary blobs are rejected explicitly.

Markdown exports disclose author grouping and omitted contributors, ranked-path
limits, cochange denominators, and status-filtered comparison counts alongside
the displayed rows.

Explicit historical refs can be analyzed even when the checked-out branch is
unborn. A missing default HEAD still produces a structured invalid-ref error.

`refs --kind branch|tag|remote|all --limit 1000` lists available references and
object IDs, including annotated-tag object and peeled-target metadata. It works
without a current HEAD and does not expose remote URLs.

`commits BASE TARGET --path src --newest-first` lists selected commits reachable
from TARGET but not BASE, with immutable bounds, history filters, and explicit
truncation/selection metadata. Equal bounds produce an empty report.

`patch BASE TARGET --path src --context 3 --max-bytes 1048576` previews a
unified comparison without applying it. The report-size budget is checked after
Git generates the diff; narrow large comparisons. JSON preserves the original
patch, while terminal and Markdown previews escape control characters. Markdown
fences adapt to backticks in patch content. Binary changes use Git summaries.

`timeline --date-basis author|committer` selects the UTC date used for buckets.
History JSON preserves both dates; Git since/until filters retain committer-date
semantics regardless of the display basis.

`timeline --fill-gaps` inserts empty periods only between the first and last selected dates. `--max-periods N` (default 1000) bounds all timeline rows and fails explicitly when exceeded; use date filters or a larger budget.

`files --sort size` ranks by descending blob bytes, then path, with unknown sizes last. Limits apply after sorting. `total_bytes` sums known sizes; `unknown_size_entries` counts entries without a blob size.

`files --kind all|file|executable|symlink|submodule` filters Git tree modes before sorting and limiting; `file` means non-executable regular files. `total_files` precedes the kind filter, while `matching_files`, known `total_bytes`, and `unknown_size_entries` describe the filtered selection before the display limit.

`owners --detect-copies` enables Git blame `-C -C` to look for copied blocks across files, including other files when the target was created. This heuristic can be expensive and is independent of `--detect-moves`; attribution is not a claim of legal ownership.

`owners --group-by commit` separates the surviving lines attributed to each commit, even for the same author. The default remains author grouping. Commit groups include full object IDs and the same selected-line percentage denominator.

### CSV exports

All 19 commands accept `--csv`, including `--output FILE` and `--no-clobber`.
CSV uses standard quoted fields, preserving commas, quotes, Unicode, and embedded
newlines. Lists, objects, booleans, and null values use JSON cells. History views
export commit rows; other commands export their principal table, patch text, or
diagnostic checks. Additional row fields are retained as columns. `report_metadata`
is a JSON object containing all remaining report fields, including resolved refs,
selection, warnings, and totals, repeated on each row. Empty tables emit one row
with `row_present=false`; data rows have `row_present=true`. The empty-table row
is a metadata carrier, not a data observation. Formats are mutually exclusive.

Version 0.4.0 adds `refs`, `commits BASE TARGET`, and `patch BASE TARGET`, along
with timeline date/gap controls, file size/mode controls, and copy/commit blame
attribution. Python requirements remain 3.10+; runtime dependencies remain empty.

Blame reports reset implicitly configured `blame.ignoreRevsFile` entries. Only an explicitly supplied `owners --ignore-revs-file` changes attribution. Git still validates configured ignore files while reading its configuration.

Unified patch previews explicitly use `a/` and `b/` prefixes and repository-root paths, independent of `diff.noprefix`, `diff.mnemonicPrefix`, or relative-display configuration.

Repository-wide history and commit ranges include empty commits and merge commits. A literal file/directory scope still uses Git path-limited traversal and can omit commits that do not change that scope. Merge statistics follow Git's default history presentation.

History `--ignore-case` makes literal `--author` and `--grep` matching case-insensitive. It requires one of these filters and records the setting in selection metadata.

History `--merges` selects commits with multiple parents; `--no-merges` excludes them. Merge selection is recorded separately from first-parent traversal, and scoped Git traversal can still omit merges unrelated to the path.

`commits BASE TARGET --ancestry-path` keeps only commits descending from BASE and reachable from TARGET, excluding side history that forked before BASE. Merge-selection flags remain exclusive even when placed on opposite sides of the command name.

`refs --contains COMMIT` finds local branches, tags, and remote-tracking refs whose commit history contains the resolved revision. Both requested and resolved containment refs are recorded.

`refs --points-at COMMIT` selects labels at the exact resolved commit, including annotated tags. It can be combined with `--contains` and kind filters; it does not fetch remote refs.

`refs --sort name|version|date` selects lexical names, Git version sorting, or newest creator date before limiting. Creator date means tagger date for annotated tags and committer date for commit refs; equal dates use ref names as a stable tie-breaker.

`refs --match "release/*"` filters short ref names with case-sensitive shell globs before the row limit. Repeated patterns are alternatives. `scanned_refs` is the count before name matching; `total_refs` is the matching count. CSV uses the same `peeled_type` field as JSON.

`files --min-bytes N --max-bytes N` uses inclusive known-size bounds, including zero-byte blobs. Unknown-size entries do not match an active size bound. Size filters precede sorting/limiting; totals describe matched entries. The Python inventory API accepts `limit=None` for complete aggregation.

`files --include GLOB --exclude GLOB` matches root-relative tree paths with case-sensitive shell globs. Includes are alternatives; exclusions win. Glob, mode, and byte filters all run before sorting and limits. The positional path remains literal.

`source FILE --lines START:END --context N` expands both sides of the requested range and clamps to the committed blob. Reports preserve the requested `line_range` and record `effective_line_range`, context, and byte budget. Context requires a line selection.

`patch BASE TARGET --merge-base` previews target changes since the unique shared ancestor, using the same merge-base validation as `diff`. Reports retain the input base SHA and effective comparison base.

`patch --find-copies` enables the same copy-detection threshold and unchanged-source search as `diff --find-copies`. Patch headers distinguish copied paths from renames; detection remains a Git similarity heuristic.

`directories [PATH] --depth N --sort churn|commits|path --limit N` aggregates historical activity by root-relative directory. A commit counts once per directory even when it changes multiple files there. Groups report distinct historical paths and authors, line churn, and binary changes. Root files use `.`. History filters and completeness warnings apply; renames use historical destination paths.

`inventory [PATH] --group-by extension|directory --depth N --sort bytes|entries|name --limit N` summarizes the complete committed tree before limiting groups. Extension groups are case-folded; extensionless files use `(none)`. Groups include entry counts, known object bytes, unknown-size entries, and Git modes. Bytes measure Git objects, including symlink contents, rather than checkout disk usage.

`divergence BASE TARGET` reports locally reachable commits unique to each side, shared commits, all merge bases, and whether the tips are equal, ancestors, diverged, or unrelated. It resolves both tips once and does not fetch. Shallow repositories explicitly warn that counts and relationships describe only available history.

`owners --sort lines|author --limit N` ranks and limits author/commit groups after attribution. Percentages retain the full selected-line denominator; reports disclose total/displayed groups and omitted line counts. Without `--limit`, all attribution groups remain visible.

`owners --show-lines` adds inclusive `[start, end]` ranges of final-file line numbers for each attribution group. Ranges respect any selected line window and stay tied to the pinned revision, including after copy/move attribution.

`timeline --period week` buckets normalized UTC dates into Monday-start weeks labeled by the Monday date. Gap filling advances seven days and handles calendar-year boundaries without week-number ambiguity.

`timeline --cumulative` adds running commit, addition, deletion, and binary-change totals in displayed period order. Totals start at the selected history boundary and carry across empty periods; they are selected diff counts, not surviving-line measurements.

Hotspots report distinct authors plus first/last changed UTC committer dates within selected history. `hotspots --sort authors|recent` ranks broad contributor activity or the latest observed change. Historical names stay separate; filters and truncation still bound the evidence.

### Version 0.5.0

All 19 commands support terminal text, JSON, Markdown, and CSV. `--csv-delimiter
comma|tab|semicolon` changes the CSV field separator and requires `--csv`.
Quoting, embedded newlines, nested JSON cells, metadata, and empty-table markers
follow the same contract for all separators. Tab-separated output is available
without changing the report schema. Git objects and the repository stay read-only.

This version adds directory history, complete committed-tree inventory summaries,
and branch divergence, plus the history/ref/file/source/blame/timeline controls
listed above. CI exercises source tests and all 19 installed commands outside
the checkout on Linux/macOS with Python 3.10/3.12. The package remains dependency-free.

Review fixes preserve legacy positional model arguments, normalize platform path syntax and external subtree aliases, reject empty/abbreviated scope options, include untracked files in diagnostics, and preserve existing export permissions when descriptor-based chmod is unavailable.

Git timeout errors clean up the direct process and, on POSIX, its process group so helpers do not survive a timed-out command. Platform timeout overflows become readable Git errors. Independently detached helpers are outside the process-group guarantee.

Human-readable exports retain bloodline summary metrics, ownership line-window scope, binary timeline totals, comparison status counts, binary markers, rename/copy sources, and tree object IDs. Empty CSV tables retain hotspot and requested cumulative columns. ASCII mode converts only drawing glyphs; repository text remains unchanged. Non-default rename thresholds disclose their effect on origin confidence.

Source and blame reject files marked binary by the selected revision's attributes or a configured binary diff driver, in addition to NUL detection. Attribute lookup uses a temporary index and leaves the real index unchanged. Copy-aware comparisons search the complete source pool before restricting output to literal destination scopes; rename source scopes also remain visible. Copy-aware patch filtering retains Git's exact quoted filenames and excludes unrelated changes.
