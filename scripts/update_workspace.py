#!/usr/bin/env python3
"""Replace a Git workspace with a release tree, preserve runtime history, then commit/push.

Typical usage from an extracted release directory:

    python scripts/update_workspace.py --workspace /workspaces/a-stock-evidence-radar

Or apply a ZIP directly with a copy of this script already present:

    python scripts/update_workspace.py \
      --archive /tmp/a_stock_evidence_radar_m1_clash_fixed.zip \
      --workspace /workspaces/a-stock-evidence-radar

The target repository's `.git` directory is never replaced. Existing `reports/`
and `data/history/` are merged over the release content so locally generated data
wins on path conflicts.
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_MARKERS = (
    Path("pyproject.toml"),
    Path("src/a_stock_radar"),
    Path(".github/workflows"),
)
DEFAULT_MERGE_PATHS = (Path("reports"), Path("data/history"))
DEFAULT_PRESERVE_PATTERNS = (".env", ".env.*")
COPY_IGNORE_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "__pycache__",
    "diagnostics",
    "runtime",
}


class UpdateError(RuntimeError):
    """Raised for a controlled workspace update failure."""


@dataclass(frozen=True)
class UpdateOptions:
    workspace: Path
    source: Path | None
    archive: Path | None
    commit_message: str | None
    remote: str
    allow_dirty: bool
    no_push: bool
    skip_tests: bool
    dry_run: bool
    skip_lint: bool = False


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command))
    return subprocess.run(
        list(command),
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
    )


def git_output(workspace: Path, *args: str) -> str:
    result = run_command(
        ["git", *args],
        cwd=workspace,
        capture=True,
    )
    return result.stdout.strip()


def resolve_git_workspace(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.exists():
        raise UpdateError(f"workspace does not exist: {path}")
    try:
        root = git_output(path, "rev-parse", "--show-toplevel")
    except subprocess.CalledProcessError as exc:
        raise UpdateError(f"not a Git worktree: {path}") from exc
    workspace = Path(root).resolve()
    if workspace == Path(workspace.anchor):
        raise UpdateError("refusing to operate on the filesystem root")
    if not (workspace / ".git").exists():
        raise UpdateError(f"Git metadata was not found at {workspace / '.git'}")
    return workspace


def is_project_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in PROJECT_MARKERS)


def discover_project_root(extracted: Path) -> Path:
    if is_project_root(extracted):
        return extracted

    direct_children = [item for item in extracted.iterdir() if item.is_dir()]
    matching = [item for item in direct_children if is_project_root(item)]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1:
        raise UpdateError(
            "archive contains multiple possible project roots: "
            + ", ".join(str(item) for item in matching)
        )

    nested = [
        item.parent
        for item in extracted.glob("*/*/pyproject.toml")
        if is_project_root(item.parent)
    ]
    if len(nested) == 1:
        return nested[0]
    raise UpdateError("could not locate a valid project root in the release")


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if _zip_member_is_symlink(info):
                raise UpdateError(f"release ZIP contains a symlink: {info.filename}")
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise UpdateError(f"unsafe ZIP member path: {info.filename}") from exc
        bundle.extractall(destination)


def should_ignore(path: Path) -> bool:
    return any(part in COPY_IGNORE_NAMES for part in path.parts)


def copy_tree(source: Path, destination: Path, *, overlay: bool = False) -> None:
    source = source.resolve()
    destination.mkdir(parents=True, exist_ok=True)

    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if should_ignore(relative):
            continue
        target = destination / relative
        if item.is_symlink():
            raise UpdateError(f"release tree contains a symlink: {relative}")
        if item.is_dir():
            if target.is_file() or target.is_symlink():
                target.unlink()
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists() and not overlay:
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def copy_selected(source_root: Path, destination_root: Path, paths: Iterable[Path]) -> None:
    for relative in paths:
        source = source_root / relative
        if not source.exists():
            continue
        destination = destination_root / relative
        if source.is_dir():
            copy_tree(source, destination, overlay=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def preserve_matching_files(source_root: Path, destination_root: Path) -> None:
    for item in source_root.iterdir():
        if not item.is_file():
            continue
        if item.name == ".env.example":
            continue
        if any(fnmatch.fnmatch(item.name, pattern) for pattern in DEFAULT_PRESERVE_PATTERNS):
            destination = destination_root / item.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def clear_workspace(workspace: Path) -> None:
    for item in workspace.iterdir():
        if item.name == ".git":
            continue
        if item.is_symlink() or item.is_file():
            item.unlink()
        else:
            shutil.rmtree(item)


def version_from_release(release_root: Path) -> str:
    pyproject = release_root / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(payload["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def validate_release(release_root: Path) -> None:
    if not is_project_root(release_root):
        missing = [str(marker) for marker in PROJECT_MARKERS if not (release_root / marker).exists()]
        raise UpdateError(f"release is incomplete; missing: {', '.join(missing)}")


def verify_workspace(
    workspace: Path,
    *,
    skip_tests: bool,
    skip_lint: bool,
) -> None:
    run_command(
        [sys.executable, "-m", "compileall", "-q", "src", "scripts"],
        cwd=workspace,
    )
    if skip_tests:
        print("Tests skipped by request.")
    elif importlib.util.find_spec("pytest") is None:
        print("pytest is not installed in this Python environment; test execution skipped.")
    else:
        run_command([sys.executable, "-m", "pytest", "-q"], cwd=workspace)

    if skip_lint:
        print("Ruff lint skipped by request.")
    elif shutil.which("ruff"):
        print("Running Ruff. Any lint details below refer to the replacement release.")
        run_command(["ruff", "check", "src", "tests", "scripts"], cwd=workspace)
    else:
        print("ruff is not installed; lint execution skipped.")


def current_branch(workspace: Path) -> str:
    branch = git_output(workspace, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        raise UpdateError("cannot push from a detached HEAD")
    return branch


def ensure_clean_or_allowed(workspace: Path, allow_dirty: bool) -> None:
    status = git_output(workspace, "status", "--porcelain")
    if status and not allow_dirty:
        raise UpdateError(
            "workspace has uncommitted changes; commit/stash them first or pass --allow-dirty"
        )


def ensure_git_identity(workspace: Path) -> None:
    name = subprocess.run(
        ["git", "config", "--get", "user.name"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    ).stdout.strip()
    email = subprocess.run(
        ["git", "config", "--get", "user.email"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if not name:
        run_command(
            ["git", "config", "user.name", "Radar Release Updater"],
            cwd=workspace,
        )
    if not email:
        run_command(
            ["git", "config", "user.email", "radar-updater@users.noreply.github.com"],
            cwd=workspace,
        )


def commit_and_push(
    workspace: Path,
    *,
    message: str,
    remote: str,
    no_push: bool,
) -> None:
    ensure_git_identity(workspace)
    run_command(["git", "add", "-A"], cwd=workspace)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=workspace,
        check=False,
    )
    if staged.returncode == 0:
        print("No file changes detected; no commit was created.")
        return
    if staged.returncode != 1:
        raise UpdateError("git diff --cached failed")

    run_command(["git", "commit", "-m", message], cwd=workspace)
    if no_push:
        print("Commit created; push skipped by request.")
        return

    branch = current_branch(workspace)
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=workspace,
        check=False,
        text=True,
        capture_output=True,
    )
    if upstream.returncode == 0:
        run_command(["git", "push"], cwd=workspace)
    else:
        run_command(["git", "push", "-u", remote, branch], cwd=workspace)


def restore_workspace(workspace: Path, backup_root: Path) -> None:
    print("Restoring the original workspace after failure...")
    clear_workspace(workspace)
    copy_tree(backup_root, workspace, overlay=True)


def prepare_release_tree(
    *,
    source: Path | None,
    archive: Path | None,
    temp_root: Path,
) -> Path:
    extracted = temp_root / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)

    if archive is not None:
        archive = archive.expanduser().resolve()
        if not archive.is_file():
            raise UpdateError(f"release archive does not exist: {archive}")
        safe_extract_zip(archive, extracted)
        project_root = discover_project_root(extracted)
    else:
        if source is None:
            source = Path(__file__).resolve().parents[1]
        source = source.expanduser().resolve()
        if not source.is_dir():
            raise UpdateError(f"release source directory does not exist: {source}")
        project_root = source

    validate_release(project_root)
    staged_release = temp_root / "release"
    copy_tree(project_root, staged_release, overlay=True)
    validate_release(staged_release)
    return staged_release


def apply_update(options: UpdateOptions) -> None:
    workspace = resolve_git_workspace(options.workspace)
    ensure_clean_or_allowed(workspace, options.allow_dirty)

    with tempfile.TemporaryDirectory(prefix="radar-workspace-update-") as temp_name:
        temp_root = Path(temp_name)
        release_root = prepare_release_tree(
            source=options.source,
            archive=options.archive,
            temp_root=temp_root,
        )
        release_version = version_from_release(release_root)
        print(f"Release version: {release_version}")
        print(f"Target workspace: {workspace}")

        merged_tree = temp_root / "merged"
        copy_tree(release_root, merged_tree, overlay=True)
        # Existing generated output and rolling history are more valuable than
        # demo files shipped in the release, so they win on path conflicts.
        copy_selected(workspace, merged_tree, DEFAULT_MERGE_PATHS)
        preserve_matching_files(workspace, merged_tree)

        if options.dry_run:
            print("Dry run complete. The workspace was not modified.")
            return

        backup_root = temp_root / "backup"
        copy_tree(workspace, backup_root, overlay=True)

        try:
            clear_workspace(workspace)
            copy_tree(merged_tree, workspace, overlay=True)
            verify_workspace(
                workspace,
                skip_tests=options.skip_tests,
                skip_lint=options.skip_lint,
            )
        except Exception:  # noqa: BLE001 - rollback must cover every validation failure
            restore_workspace(workspace, backup_root)
            raise

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        message = options.commit_message or (
            f"chore: apply radar release v{release_version} ({timestamp})"
        )
        commit_and_push(
            workspace,
            message=message,
            remote=options.remote,
            no_push=options.no_push,
        )


def parse_args(argv: Sequence[str] | None = None) -> UpdateOptions:
    parser = argparse.ArgumentParser(
        description=(
            "Replace a Git workspace with this release, merge existing reports/history, "
            "run checks, commit, and push."
        )
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--source",
        type=Path,
        help="extracted release directory; defaults to the project containing this script",
    )
    source_group.add_argument("--archive", type=Path, help="release ZIP to extract and apply")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="target Git worktree or a directory inside it; defaults to the current directory",
    )
    parser.add_argument("--message", dest="commit_message", help="Git commit message")
    parser.add_argument("--remote", default="origin", help="remote used when no upstream exists")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow replacement when the target has uncommitted changes",
    )
    parser.add_argument("--no-push", action="store_true", help="create a commit but do not push")
    parser.add_argument("--skip-tests", action="store_true", help="skip pytest checks")
    parser.add_argument("--skip-lint", action="store_true", help="skip Ruff lint checks")
    parser.add_argument("--dry-run", action="store_true", help="validate and stage without modifying")
    args = parser.parse_args(argv)
    return UpdateOptions(
        workspace=args.workspace,
        source=args.source,
        archive=args.archive,
        commit_message=args.commit_message,
        remote=args.remote,
        allow_dirty=args.allow_dirty,
        no_push=args.no_push,
        skip_tests=args.skip_tests,
        skip_lint=args.skip_lint,
        dry_run=args.dry_run,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        apply_update(parse_args(argv))
        return 0
    except (UpdateError, subprocess.CalledProcessError, OSError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
