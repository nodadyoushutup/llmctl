from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import chromadb
from watchdog.events import FileSystemEventHandler, FileMovedEvent
from watchdog.observers import Observer

from config import load_config
from ingest import delete_paths, get_collection, index_paths, ingest, _is_excluded


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is required for RAG_MODE=git") from exc
    if result.returncode != 0:
        error = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {error}")
    return result.stdout.strip()


def _ensure_git_repo(config) -> None:
    if not config.git_url:
        raise RuntimeError("RAG_GIT_URL is required when RAG_MODE=git")

    repo_root = config.repo_root
    if repo_root.exists():
        if not (repo_root / ".git").exists():
            raise RuntimeError(
                f"RAG_GIT_DIR exists but is not a git repo: {repo_root}"
            )
        return

    repo_root.parent.mkdir(parents=True, exist_ok=True)
    _run_git(
        [
            "clone",
            "--branch",
            config.git_branch,
            "--single-branch",
            config.git_url,
            str(repo_root),
        ]
    )


def _git_rev_parse(repo_root: Path, ref: str = "HEAD") -> str:
    return _run_git(["rev-parse", ref], cwd=repo_root)


def _git_fetch_and_reset(config) -> None:
    repo_root = config.repo_root
    _run_git(["fetch", "origin", config.git_branch], cwd=repo_root)
    _run_git(
        ["checkout", "-B", config.git_branch, f"origin/{config.git_branch}"],
        cwd=repo_root,
    )
    _run_git(["reset", "--hard", f"origin/{config.git_branch}"], cwd=repo_root)


def _git_diff_paths(repo_root: Path, old: str, new: str) -> tuple[list[Path], list[Path]]:
    raw = subprocess.run(
        ["git", "diff", "--name-status", "-z", old, new],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
    )
    if raw.returncode != 0:
        error = (raw.stderr or raw.stdout).decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"git diff failed: {error}")

    parts = raw.stdout.decode("utf-8", errors="ignore").split("\0")
    changed: list[Path] = []
    deleted: list[Path] = []

    idx = 0
    while idx < len(parts):
        status = parts[idx]
        idx += 1
        if not status:
            continue
        code = status[0]
        if code in {"R", "C"}:
            if idx + 1 >= len(parts):
                break
            old_path = parts[idx]
            new_path = parts[idx + 1]
            idx += 2
            if old_path:
                deleted.append(repo_root / old_path)
            if new_path:
                changed.append(repo_root / new_path)
        else:
            if idx >= len(parts):
                break
            path = parts[idx]
            idx += 1
            if not path:
                continue
            if code == "D":
                deleted.append(repo_root / path)
            else:
                changed.append(repo_root / path)

    return changed, deleted


def _git_poll_loop(config, reset: bool, skip_initial: bool) -> int:
    try:
        _ensure_git_repo(config)
        _git_fetch_and_reset(config)
    except Exception as exc:
        print(f"Git repo setup failed: {exc}", file=sys.stderr)
        return 1

    if not skip_initial:
        try:
            ingest(config, reset=reset)
        except Exception as exc:
            print(f"Initial ingest failed: {exc}", file=sys.stderr)
            return 1

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    try:
        collection = get_collection(client, config, reset=False)
    except Exception as exc:
        print(f"Failed to connect to Chroma: {exc}", file=sys.stderr)
        return 1

    last_commit = _git_rev_parse(config.repo_root)
    poll_s = max(1.0, float(config.git_poll_s))
    print(
        f"Polling {config.git_url}@{config.git_branch} every {poll_s:.1f}s into {config.repo_root}."
    )

    try:
        while True:
            time.sleep(poll_s)
            try:
                prev_commit = last_commit
                _git_fetch_and_reset(config)
                last_commit = _git_rev_parse(config.repo_root)
                if last_commit == prev_commit:
                    continue

                changed, deleted = _git_diff_paths(
                    config.repo_root, prev_commit, last_commit
                )
                if deleted:
                    delete_count = delete_paths(collection, config, deleted)
                    if delete_count:
                        print(f"Removed {delete_count} files from RAG index.")

                if changed:
                    file_count, chunk_count = index_paths(
                        collection, config, changed, delete_first=True
                    )
                    if file_count:
                        print(
                            f"Reindexed {chunk_count} chunks from {file_count} files."
                        )
            except Exception as exc:
                print(f"Git poll failed: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        pass

    return 0


class _ChangeBatcher:
    def __init__(self, collection, config, debounce_s: float) -> None:
        self._collection = collection
        self._config = config
        self._debounce_s = max(0.1, debounce_s)
        self._pending: set[Path] = set()
        self._deleted: set[Path] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)

    def add_change(self, path: Path) -> None:
        with self._lock:
            self._pending.add(path)
        self._wake.set()

    def add_delete(self, path: Path) -> None:
        with self._lock:
            self._deleted.add(path)
        self._wake.set()

    def _drain(self) -> tuple[set[Path], set[Path]]:
        with self._lock:
            pending = set(self._pending)
            deleted = set(self._deleted)
            self._pending.clear()
            self._deleted.clear()
        pending -= deleted
        return pending, deleted

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            if self._stop.is_set():
                break

            while True:
                self._wake.clear()
                time.sleep(self._debounce_s)
                if self._stop.is_set() or not self._wake.is_set():
                    break

            if self._stop.is_set():
                break

            changed, deleted = self._drain()
            if not changed and not deleted:
                continue

            if deleted:
                delete_count = delete_paths(
                    self._collection, self._config, list(deleted)
                )
                if delete_count:
                    print(f"Removed {delete_count} files from RAG index.")

            if changed:
                file_count, chunk_count = index_paths(
                    self._collection,
                    self._config,
                    list(changed),
                    delete_first=True,
                )
                if file_count:
                    print(
                        f"Reindexed {chunk_count} chunks from {file_count} files."
                    )


class _WatchHandler(FileSystemEventHandler):
    def __init__(self, batcher: _ChangeBatcher, config) -> None:
        self._batcher = batcher
        self._config = config

    def _should_ignore(self, path: Path) -> bool:
        return _is_excluded(path, self._config)

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_ignore(path):
            return
        self._batcher.add_change(path)

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_ignore(path):
            return
        self._batcher.add_change(path)

    def on_deleted(self, event) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_ignore(path):
            return
        self._batcher.add_delete(path)

    def on_moved(self, event: FileMovedEvent) -> None:
        if event.is_directory:
            return
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)
        if not self._should_ignore(src_path):
            self._batcher.add_delete(src_path)
        if not self._should_ignore(dest_path):
            self._batcher.add_change(dest_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch repo and keep Chroma in sync")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the collection before the initial ingest",
    )
    parser.add_argument(
        "--skip-initial",
        action="store_true",
        help="Skip the initial full ingest and only process changes",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=float(os.getenv("RAG_WATCH_DEBOUNCE_S", "1.0")),
        help="Seconds to wait for quiet period before indexing changes",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    config = load_config()

    if config.rag_mode == "git":
        return _git_poll_loop(config, reset=args.reset, skip_initial=args.skip_initial)

    if not args.skip_initial:
        try:
            ingest(config, reset=args.reset)
        except Exception as exc:
            print(f"Initial ingest failed: {exc}", file=sys.stderr)
            return 1

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    try:
        collection = get_collection(client, config, reset=False)
    except Exception as exc:
        print(f"Failed to connect to Chroma: {exc}", file=sys.stderr)
        return 1

    batcher = _ChangeBatcher(collection, config, args.debounce)
    batcher.start()

    observer = Observer()
    handler = _WatchHandler(batcher, config)
    observer.schedule(handler, str(config.repo_root), recursive=True)
    observer.start()
    print(f"Watching {config.repo_root} for changes.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join(timeout=5)
        batcher.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
