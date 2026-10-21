# codegent

`codegent` traces the lineage of files through git history. It follows renames, identifies the origin commit, summarizes authorship, and renders terminal-friendly family trees for code.

## Installation

```bash
pip install -e .
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
