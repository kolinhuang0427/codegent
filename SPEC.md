# codegent specification

## Purpose

Help maintainers inspect file history and repository activity with a dependency-free
Python CLI. Python 3.10+ and Git 2.37+ are required. The console entry point is
`codegent`; `python -m codegent` and `python -m codegent.main` are equivalent.

## Implemented commands

| Command | Result |
| --- | --- |
| trace | File history with Git rename detection and observed-origin summary |
| ancestry | Chronological entries with historical filenames and estimated net lines |
| genemap | Compact timeline of observed changes |
| bloodline | Observed-origin, author-diversity, and net-line summary |
| diff | File-level comparison, optional path scope, and aggregate status/line counts |
| authors | Commit/churn aggregates by author for a file |
| hotspots | Per-path historical change activity for a repository or directory |
| owners | Surviving committed text-line attribution using Git blame |
| timeline | UTC author/committer-date activity buckets, with optional bounded gap filling |
| cochange | Historical paths changed in the same commits as a target file |
| files | Tracked paths, modes, object IDs/types, and sizes at a selected commit |
| source | Bounded, numbered text preview from a committed blob |
| doctor | Read-only Git/runtime and worktree diagnostics |
| refs | Local branches, remote-tracking refs and tags, with peeled tag metadata |
| commits | Target-reachable commits excluding base ancestry, with immutable resolved bounds |
| patch | Bounded unified diff preview between two commits, optionally scoped to literal paths |
| directories | Historical commits, authors, paths and churn grouped by directory depth |
| inventory | Complete committed-tree object sizes grouped by extension or directory |
| divergence | Shared/unique reachable commit counts, merge bases, and revision relationship |

## History selection

History commands support a single commit/ref, positive commit bound, ISO date
window, literal author/commit-message substrings, first-parent traversal, and optional rename
following. File-history views optionally present newest entries first, without
changing chronological calculations. Reports preserve immutable resolved tips. Rename similarity defaults to 50 percent and is configurable from 1 to
100. Mailmap identity mapping and whitespace-insensitive statistics are optional.
Git processes have a configurable positive finite timeout (30 seconds by default).

Relative file paths resolve against the directory supplied with `--repo`; absolute
paths must belong to the repository. Paths are literal, including Git pathspec
metacharacters. Structured parsing preserves Unicode, tabs, newlines and other
filename characters using NUL-delimited Git output.

## Evidence and limits

History results include selection, truncation and shallow-repository metadata.
`origin` is the earliest observed commit. `origin_confirmed` means that no explicit
filter, commit truncation, or shallow boundary limits the observed Git traversal;
it does not prove semantic code ancestry. Rename matching is Git's heuristic.

History line counts are accumulated net-diff estimates; incomplete or binary
baselines produce null cumulative counts. Incomplete history also leaves origin age
unknown. They do not measure
surviving code, copied-code origin, or author quality. `owners` uses Git blame for
surviving-line attribution at a selected committed ref; it excludes working-tree
edits and rejects binary files. Git blame identities follow its mailmap behavior.

Hotspots count historical names separately across renames and can include deleted
paths. Churn is activity, not a defect or risk score. The history views are linear
presentations of observed commits, not a complete branch graph.

## Output contract

Reports support terminal text, JSON, Markdown, or CSV. JSON retains original strings;
terminal and Markdown renderers escape control and bidi override characters.
Long terminal box fields account for wide and combining characters. Terminal color
obeys explicit no-color flags and plain-terminal environment settings.

File exports use UTF-8 temporary files and atomic replacement. Failed generation
preserves existing reports. Output parent directories must already exist.

## Verification

Run `python -m unittest discover -v`. Integration scenarios create real Git
repositories and invoke the CLI; they cover unusual paths, renames, shallow history,
filters, merges, author aliases, blame attribution, and exports. Build/install
validation must also exercise the installed console script outside the source tree.

CLI argument errors use exit code 2, runtime errors use 1, and successful reports
use 0. JSON mode applies to argument diagnostics as well as runtime diagnostics.
Closed stdout pipes exit cleanly. Unsupported command/option combinations fail
explicitly. Owners reports disclose shallow blame boundaries.

## Additional report controls

Author summaries support identity/email grouping and minimum-commit thresholds;
counts distinguish all, matching, displayed, and omitted groups. Hotspots support
root-relative exclusion globs and paths present at the selected tip. Other path
inputs remain literal. Timeline buckets use configurable UTC author or committer dates; Git date selection
continues to use committer dates. Cochange counts are co-occurrence, not evidence
of dependency or causality. Historical filenames are not silently unified.

Comparisons may use a unique merge base, explicit copy detection, and selected
change statuses. Effective refs and comparison settings are preserved. Summary
counts match selected rows; unfiltered Git stats are omitted when filtering.
Copy and rename provenance use distinct fields.

Source previews enforce a pre-selection blob-size limit (default 1 MiB), reject
binary data, and preserve exact selected content in JSON. Files listings disclose
entry truncation. Blame supports ignored revisions and within-file move detection,
with heuristic attribution and shallow boundaries disclosed.

Exports optionally use compact single-line JSON or plain ASCII terminal graphics.
No-clobber file creation is atomic, and replacing a regular file preserves its
access permission bits. Special mode bits are not copied. Diagnostics omit remote
URLs and account credentials. Unsupported command/option combinations fail.

The installed-wheel smoke check exercises all nineteen commands in text, JSON,
Markdown, and CSV. CI repeats source and installed checks on Linux/macOS Python
3.10/3.12, cancelling superseded runs for the same ref.

## Version 0.4 controls and CSV contract

`refs` can select local branches, tags or remote-tracking refs with a row limit.
Annotated tags preserve both tag-object and peeled-target metadata; refs are not
fetched from a remote. Commit ranges mean commits reachable from target but not
base, not an assumed linear interval. Range results record effective bounds and
selection completeness. Patch previews use rename detection, optional literal
paths, configurable nonnegative context and a post-generation byte budget; this
budget is an export cap, not a Git subprocess memory limit. Raw patches are
preserved in JSON and CSV; terminal and Markdown previews escape controls.

Timeline gap filling spans only selected observed periods; a positive maximum
period count (default 1000) bounds all timeline output. File mode filters precede
path/size sorting and limiting. File totals distinguish the unfiltered inventory
from matched entries; known byte totals and unknown-size counts describe matches.
Blame bounds blob size before reading content, supports optional cross-file copy
heuristics, and can group surviving lines by author or commit.

CSV exports principal table rows, all their fields, and remaining report metadata
in a JSON `report_metadata` column. Nested row values and nulls use JSON cells;
strings and numbers remain native cells. Empty tables preserve metadata in one
row with `row_present=false`; this is not an observation. Data rows use true.
CSV quoting preserves raw values including newlines. JSON, CSV and Markdown
formats are mutually exclusive. File output uses the same atomic/no-clobber path.

## Version 0.5 controls

Repository-wide history includes empty commits and merges; literal path scopes use
Git path-limited traversal. History supports merge/non-merge selection and
case-insensitive literal author/message filters. Commit ranges optionally keep
only ancestry paths descending from the base. All active filters are disclosed.

Ref inventories support containment, exact commit labels, version/creator-date
sorting, and OR-ed short-name globs before limits. Tree listings support inclusive
known-byte bounds and include/exclude path globs before sorting/limiting. Source
context expands a valid requested range within the blob; the byte cap still
applies before selecting lines. Patches support merge bases and copy detection,
with explicit a/b prefixes independent of diff display configuration.

Ownership resets implicitly configured ignored revisions, though Git validates
configured ignore files when loading configuration. Explicit ignored-revision
files remain supported. Ownership ranking/limits preserve the selected-line
percentage denominator and disclose omitted lines. Optional inclusive line ranges
refer to final-file numbers at the pinned revision.

Directory activity counts a commit once per historical destination directory.
Inventory aggregates a complete tree, preserving unknown sizes, before limiting
groups; bytes are Git object sizes, not filesystem usage. Divergence compares
pinned tips without fetching and discloses shallow-boundary limits.

Weekly timelines start on Monday in UTC and use Monday-date labels. Cumulative
commit/diff counts start within the selected history and carry through empty
periods. Hotspots add distinct author counts and observed first/last UTC committer
dates; authors/recent sorting remains bounded by the selected history.

CSV accepts comma, tab, or semicolon separators using standard CRLF quoting for
embedded newlines. The alternate separator option requires CSV output and retains
the same metadata, nested-cell, and empty-table contract. All nineteen commands
have installed-package checks in text, JSON, Markdown, and CSV; CSV is exercised
with all three separators. Development version is 0.5.0.
