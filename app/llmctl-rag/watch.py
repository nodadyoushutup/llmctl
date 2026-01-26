from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import chromadb
from watchdog.events import FileSystemEventHandler, FileMovedEvent
from watchdog.observers import Observer

from config import load_config
from git_sync import (
    ensure_git_repo,
    git_diff_paths,
    git_env,
    git_fetch_and_reset,
    git_rev_parse,
    safe_git_url,
)
from ingest import delete_paths, get_collection, index_paths, ingest, _is_excluded


def _git_poll_loop(config, reset: bool, skip_initial: bool) -> int:
    try:
        ensure_git_repo(config)
        git_fetch_and_reset(config)
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

    env = git_env(config)
    last_commit = git_rev_parse(config.repo_root, env=env)
    poll_s = max(1.0, float(config.git_poll_s))
    print(
        f"Polling {safe_git_url(config.git_url)}@{config.git_branch} every {poll_s:.1f}s into {config.repo_root}."
    )

    try:
        while True:
            time.sleep(poll_s)
            try:
                prev_commit = last_commit
                git_fetch_and_reset(config)
                last_commit = git_rev_parse(config.repo_root, env=env)
                if last_commit == prev_commit:
                    continue

                changed, deleted = git_diff_paths(
                    config.repo_root, prev_commit, last_commit
                )
                if deleted:
                    delete_count = delete_paths(collection, config, deleted)
                    if delete_count:
                        print(f"Removed {delete_count} files from RAG index.")

                if changed:
                    file_count, chunk_count, _, _ = index_paths(
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
                file_count, chunk_count, _, _ = index_paths(
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
        default=None,
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

    if not config.watch_enabled:
        print("Filesystem watchdog is disabled; exiting after initial ingest.")
        return 0

    client = chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    try:
        collection = get_collection(client, config, reset=False)
    except Exception as exc:
        print(f"Failed to connect to Chroma: {exc}", file=sys.stderr)
        return 1

    debounce_s = args.debounce if args.debounce is not None else config.watch_debounce_s
    batcher = _ChangeBatcher(collection, config, debounce_s)
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
