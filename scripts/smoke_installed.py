"""Exercise an installed console script outside the source tree."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    executable = str(Path(sys.argv[1]).resolve())
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary)

        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *args], check=True,
                                  capture_output=True, text=True, env=environment).stdout.strip()

        def invoke(*args: str) -> str:
            return subprocess.run([executable, "--repo", str(repo), *args], cwd=repo,
                                  check=True, capture_output=True, text=True, env=environment).stdout

        def report(*args: str) -> dict:
            return json.loads(invoke(*args, "--json"))

        git("init", "-b", "main")
        git("config", "user.name", "First")
        git("config", "user.email", "first@example.test")
        git("config", "commit.gpgsign", "false")
        (repo / "old.py").write_text("one\ntwo\nthree\n")
        git("add", "-A")
        git("commit", "-m", "initial")
        base = git("rev-parse", "HEAD")
        name = "新 file.py"
        git("mv", "old.py", name)
        (repo / name).write_text("one\ntwo\nthree\nfour\n")
        (repo / "binary.dat").write_bytes(b"\0binary")
        git("config", "user.name", "Second")
        git("config", "user.email", "second@example.test")
        git("add", "-A")
        git("commit", "-m", "rename and extend")

        checked: list[str] = []
        for command in ("trace", "ancestry", "genemap", "bloodline"):
            result = report(command, name)
            assert result["total_commits"] == 2, result
            assert result["migrations"] == [["old.py", name]], result
            checked.append(command)
        assert report("authors", name)["total_authors"] == 2
        checked.append("authors")
        assert report("hotspots")["matching_files"] == 3
        checked.append("hotspots")
        owners = report("owners", name)
        assert owners["selected_lines"] == 4 and len(owners["owners"]) == 2
        checked.append("owners")
        diff = report("diff", base, "HEAD")
        assert diff["summary"]["files"] == 2 and diff["summary"]["binary_files"] == 1
        checked.append("diff")
        timeline = report("timeline")
        assert sum(row["commits"] for row in timeline["periods"]) == 2
        checked.append("timeline")
        companions = report("cochange", name)
        assert companions["target_commits"] == 1 and companions["files"][0]["path"] == "binary.dat"
        checked.append("cochange")
        assert report("files")["total_files"] == 2
        checked.append("files")
        source = report("source", name, "--lines", "2:3")
        assert source["content"] == "two\nthree\n"
        checked.append("source")
        assert report("doctor")["working_tree_clean"]
        checked.append("doctor")
        assert report("refs")["total_refs"] == 1
        checked.append("refs")
        assert report("commits", base, "HEAD")["total_commits"] == 1
        checked.append("commits")
        assert "+four" in report("patch", base, "HEAD")["patch"]
        checked.append("patch")
        assert report("directories")["total_directories"] == 1
        checked.append("directories")
        assert report("inventory")["total_entries"] == 2
        checked.append("inventory")
        assert report("divergence", base, "HEAD")["relationship"] == "base-ancestor"
        checked.append("divergence")
        assert report("owners", name, "--show-lines", "--limit", "1")["omitted_lines"] == 1
        weekly = report("timeline", "--period", "week", "--fill-gaps", "--cumulative")
        assert weekly["periods"][-1]["cumulative_commits"] == 2
        assert report("refs", "--points-at", "HEAD", "--match", "main")["total_refs"] == 1
        assert report("files", "--sort", "size", "--kind", "file")["matching_files"] == 2
        assert report("timeline", "--fill-gaps", "--date-basis", "committer")["fill_gaps"]
        assert report("owners", name, "--group-by", "commit")["group_by"] == "commit"
        assert report("owners", name, "--detect-moves")["selected_lines"] == 4
        compact = invoke("trace", name, "--json", "--compact")
        assert compact.count("\n") == 1 and json.loads(compact)["total_commits"] == 2
        target = repo / "report.md"
        assert invoke("trace", name, "--markdown", "--output", str(target)) == ""
        assert target.read_text().startswith("# codegent trace")
        saved = target.read_text()
        try:
            invoke("trace", name, "--markdown", "--output", str(target), "--no-clobber")
        except subprocess.CalledProcessError as exc:
            assert exc.returncode == 1
        else:
            raise AssertionError("no-clobber replaced an existing export")
        assert target.read_text() == saved
        for command in checked:
            arguments = [command, base, "HEAD"] if command in {"diff", "commits", "patch", "divergence"} else [command] if command in {"hotspots", "timeline", "files", "doctor", "refs", "directories", "inventory"} else [command, name]
            assert invoke(*arguments, "--markdown").startswith(f"# codegent {command}")
            assert invoke(*arguments, "--no-color").strip()
            rows = list(csv.DictReader(io.StringIO(invoke(*arguments, "--csv"))))
            assert rows and "report_metadata" in rows[0]
            json.loads(rows[0]["report_metadata"])
            for option, delimiter in (("tab", "\t"), ("semicolon", ";")):
                separated = list(csv.DictReader(io.StringIO(invoke(*arguments, "--csv", "--csv-delimiter", option)), delimiter=delimiter))
                assert separated and "report_metadata" in separated[0]
        print(json.dumps({"version": invoke("--version").strip(), "installed_executable": executable,
                          "commands_verified": checked, "formats": ["text", "json", "markdown", "csv"],
                          "csv_delimiters": ["comma", "tab", "semicolon"], "atomic_file_export": True}, indent=2))


if __name__ == "__main__":
    main()
