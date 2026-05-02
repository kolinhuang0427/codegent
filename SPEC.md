# codegent — Git Code Genealogist

## Concept & Vision

`codegent` traces the evolutionary lineage of code across git history. It answers questions like: "Where did this function come from?", "Who originally wrote this logic?", "Is this code a copy or a true descendant?". Think of it as a family tree for your functions — a genealogy tool that treats commits as births, renames as adoptions, and deletions as deaths.

The tone is warm, slightly whimsical, and genuinely useful. Output includes ASCII family trees, rich metadata cards per commit, and a summary of the code's "bloodline."

## Core Features

### 1. Trace (Primary Command)
```
codegent trace <path> [commit_hash]
```
Walks git history to find all commits touching a path, following renames. Produces:
- An ASCII family tree showing parent↔child relationships
- Per-commit cards: author, date, message, lines added/deleted
- "Origin commit" detection (first appearance)
- "Heir" detection (who inherited the code after original author left)

### 2. Ancestry Report
```
codegent ancestry <path>
```
Shows the direct lineage chain from first commit to current state. Each entry shows:
- Commit hash (short), author, date
- Relationship type: "origin", "heir", "co-author", "renamed"
- Lines of code carried from this commit

### 3. Gene Map (Visualization)
```
codegent genemap <path>
```
Outputs a text-based visualization of the code's evolution:
- Timeline on Y axis (oldest → newest)
- Branch lines showing parallel evolution
- Annotations for major milestones (rewrites, migrations, forks)

### 4. Bloodline Summary
```
codegent bloodline <path>
```
One-shot summary card:
- Original author + date
- Total commits in lineage
- Number of files the code migrated through
- Longest-living fragment age
- "Genetic diversity" score (how many distinct authors contributed)

### 5. Diff Lineage
```
codegent diff <commit_a> <commit_b>
```
Shows what code was transferred between two arbitrary commits — useful for finding if feature X in repo B came from repo A.

## Technical Approach

### Python + Git Commands
- Pure Python standard library + `git` CLI calls via `subprocess`
- No external Python dependencies (batteries-included)
- Typed for clarity

### Rename Detection
- Uses `git log --follow` to track renames
- `git show` with `--raw` format for diff stats
- Commit graph traversal via `git rev-list --reverse`

### Output
- Rich terminal output with ANSI colors (via `colorama` or manually)
- `--json` flag on all commands for machine-readable output
- ASCII art family trees using box-drawing characters

### Architecture
```
codegent/
├── __init__.py
├── cli.py           # Click-based CLI
├── tracer.py        # Core git history traversal
├── tree.py          # ASCII family tree builder
├── models.py        # CommitNode, CodeGene, Bloodline dataclasses
├── colors.py        # Terminal color helpers
└── main.py          # Entry point
```

## CLI Design

All commands support:
- `--json` — machine-readable JSON output
- `--no-color` — plain text
- `--repo <path>` — specify repo (defaults to CWD)

### Trace Example Output
```
$ codegent trace src/auth.py

  🔍 Tracing lineage for: src/auth.py
  📍 Follows renames: yes

  ╭─────────────────────────────────────────╮
  │ 🪦 Commit 4d3f2a1 — "Remove legacy auth"  │
  │    Author: Sarah Chen <sarah@example.com>│
  │    Date: 2024-03-15 (2 years ago)        │
  │    Role: HEIR (carried 67% of code)      │
  │    +23 -89 lines                        │
  ╰─────────────────────────────────────────╯
                    │
                    ▼
  ╭─────────────────────────────────────────╮
  │ 🌟 Commit a1b2c3d — "OAuth2 migration"  │
  │    Author: Sarah Chen <sarah@example.com>│
  │    Date: 2023-06-01 (3 years ago)       │
  │    Role: ORIGIN (first appearance)      │
  │    +312 -0 lines                        │
  ╰─────────────────────────────────────────╯
                    │
                    ▼
  ╭─────────────────────────────────────────╮
  │ 💀 Commit f5e6d7c — "Stub out auth"      │
  │    Author: Maya Patel <maya@example.com> │
  │    Date: 2022-11-20 (3.5 years ago)     │
  │    Role: CO-AUTHOR (framework)           │
  │    +45 -0 lines                          │
  ╰─────────────────────────────────────────╯

  📊 Bloodline Summary
  ─────────────────────────
  Origin author:    Sarah Chen
  Code age:         3.5 years
  Total commits:    12
  Migration events: 3 (renames/moves)
  Genetic diversity: 4 authors
  Survival rate:    34% (code still present)
```

## Edge Cases
- File never existed → clear error with suggestion
- No rename history → just shows linear commit list
- Binary files → skip diff stats, note "binary"
- Empty repo → graceful empty state
- 10,000+ commits → pagination + `--max-commits` flag

## Installation
```bash
pip install -e .
# or
pip install codegent  (after publishing)
```

## Companion: `git-gent` Alias
```bash
git config --global alias.gent '!codegent'
git gent trace src/auth.py  # as a git subcommand
```
