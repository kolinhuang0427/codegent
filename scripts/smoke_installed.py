"""Exercise an installed console script outside the source tree."""
from __future__ import annotations

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
        target = repo / "report.md"
        assert invoke("trace", name, "--markdown", "--output", str(target)) == ""
        assert target.read_text().startswith("# codegent trace")
        for command in checked:
            arguments = [command, base, "HEAD"] if command == "diff" else [command] if command == "hotspots" else [command, name]
            assert invoke(*arguments, "--markdown").startswith(f"# codegent {command}")
            assert invoke(*arguments, "--no-color").strip()
        print(json.dumps({"version": invoke("--version").strip(), "installed_executable": executable,
                          "commands_verified": checked, "formats": ["text", "json", "markdown"],
                          "atomic_file_export": True}, indent=2))


if __name__ == "__main__":
    main()
