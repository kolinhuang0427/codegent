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
| timeline | UTC author-date activity buckets for a path scope |
| cochange | Historical paths changed in the same commits as a target file |
| files | Tracked paths, modes, object IDs/types, and sizes at a selected commit |
| source | Bounded, numbered text preview from a committed blob |
| doctor | Read-only Git/runtime and worktree diagnostics |

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

Reports support terminal text, JSON, or Markdown. JSON retains original strings;
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
inputs remain literal. Timeline buckets use UTC author dates; Git date selection
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

The installed-wheel smoke check exercises all thirteen commands in text, JSON,
and Markdown. CI repeats source and installed checks on Linux/macOS Python
3.10/3.12, cancelling superseded runs for the same ref.
