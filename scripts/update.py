#!/usr/bin/env python3
"""Update the source checkout with a fast-forward, then run its new installer."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "spacemouse"))
from processes import fusion_running


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def pull_checkout(repo):
    repo = Path(repo).resolve()
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("The repository has local changes. Commit or back them up before updating.")
    if git(repo, "rev-parse", "--is-shallow-repository") not in ("true", "false"):
        raise ValueError("Invalid Git repository")
    branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    remote = git(repo, "config", f"branch.{branch}.remote")
    if remote == "." or not remote:
        raise ValueError("No remote update source is configured for this branch.")
    old = git(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "-C", str(repo), "fetch", "--prune", remote], check=True)
    # Never reset, stash, change branches, or manufacture a merge commit.
    subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", "--no-edit", upstream], check=True)
    new = git(repo, "rev-parse", "HEAD")
    print(f"Revision: {old[:12]} → {new[:12]}", flush=True)
    return repo


def checkout_for_installation(app):
    state_file = app / "repo-state.json"
    if not state_file.exists():
        raise ValueError("No source repository is linked. Run ./install.sh --update INSTALLATION_FOLDER from a cloned repository.")
    state = json.loads(state_file.read_text())
    source = Path(state["checkout"]) if state.get("checkout") else None
    if source and (source / ".git").exists():
        return source
    # A release archive or removed checkout can still be updated later.
    source = app / "update-source"
    if not source.exists():
        subprocess.run(["git", "clone", "--branch", state["branch"], "--single-branch",
                        "--", state["remote"], str(source)], check=True)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--target", type=Path, default=HERE)
    parser.add_argument("--interactive", action="store_true")
    space = parser.add_mutually_exclusive_group()
    space.add_argument("--with-spacemouse", action="store_true")
    space.add_argument("--without-spacemouse", action="store_true")
    args = parser.parse_args()
    result = 1
    try:
        if fusion_running():
            raise ValueError("Close Fusion before updating.")
        target = args.target.expanduser().resolve()
        if not target.is_dir():
            raise ValueError("The installation to update does not exist.")
        repo = pull_checkout(args.repo or checkout_for_installation(target))
        command = ["bash", str(repo / "install.sh"), "--apply-update", str(target)]
        if args.with_spacemouse:
            command.append("--with-spacemouse")
        elif args.without_spacemouse:
            command.append("--without-spacemouse")
        result = subprocess.run(command).returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Update stopped: {error}", file=sys.stderr)
    if args.interactive and sys.stdin.isatty():
        input("Press Enter to close …")
    return result


if __name__ == "__main__":
    sys.exit(main())
