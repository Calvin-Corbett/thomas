from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .ingest import WatcherConfig, ingest_file, is_supported_file, load_watcher_config

NotifyFn = Callable[[str], None]


@dataclass
class WatcherStatus:
    running: bool
    enabled: bool
    recursive: bool
    paths: list[str]
    queue_depth: int
    processed: int
    skipped: int
    failed: int
    last_event_path: str | None
    last_error: str | None
    config: dict

    def to_dict(self) -> dict:
        return asdict(self)


class _ProcessedTTL:
    """
    In-memory TTL de-dupe for event storms (create+modify+move, etc).
    Key: (abs_path, size, mtime_ns). Good enough for "same file spam" filtering.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self.ttl = float(ttl_seconds)
        self._lock = threading.Lock()
        self._d: dict[tuple[str, int, int], float] = {}

    def seen(self, key: tuple[str, int, int]) -> bool:
        now = time.time()
        with self._lock:
            if len(self._d) > 2048:
                self._prune_locked(now)
            ts = self._d.get(key)
            if ts is not None and (now - ts) < self.ttl:
                return True
            self._d[key] = now
            return False

    def _prune_locked(self, now: float) -> None:
        dead = [k for k, ts in self._d.items() if (now - ts) >= self.ttl]
        for k in dead:
            self._d.pop(k, None)


class _Handler(FileSystemEventHandler):
    def __init__(self, enqueue: Callable[[str], None]) -> None:
        super().__init__()
        self._enqueue = enqueue

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event):
        if isinstance(event, FileMovedEvent) and not event.is_directory:
            self._enqueue(event.dest_path)

    def on_modified(self, event):
        # Some apps emit only modified events after a create.
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            self._enqueue(event.src_path)


class WatcherService:
    """
    WatcherService:
      - reads config from thomas.toml
      - watchdog Observer watches directories
      - events enqueue candidate paths
      - dispatcher thread submits ingestion jobs to a thread pool
      - completion callback updates counters + emits notification
    """

    def __init__(
        self,
        notifier: NotifyFn | None = None,
        config_path: str | None = None,
    ) -> None:
        self._config_path = config_path
        self._notifier = notifier or (lambda msg: print(f"[watcher] {msg}", flush=True))

        self._lock = threading.RLock()
        self._observer: Observer | None = None
        self._dispatcher: threading.Thread | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._stop_evt = threading.Event()

        self._q: queue.Queue[str] = queue.Queue(maxsize=4096)

        self._config: WatcherConfig = load_watcher_config(config_path=self._config_path)
        self._paths: list[str] = self._normalize_paths(self._config.paths)
        self._dedup = _ProcessedTTL(ttl_seconds=self._config.dedupe_ttl_seconds)

        self._processed = 0
        self._skipped = 0
        self._failed = 0
        self._last_event_path: str | None = None
        self._last_error: str | None = None

        self._inflight: set[str] = set()  # abs paths being processed (avoid duplicate submits)

    def status(self) -> WatcherStatus:
        with self._lock:
            running = self._observer is not None and self._observer.is_alive()
            return WatcherStatus(
                running=running,
                enabled=bool(self._config.enabled),
                recursive=bool(self._config.recursive),
                paths=list(self._paths),
                queue_depth=self._q.qsize(),
                processed=self._processed,
                skipped=self._skipped,
                failed=self._failed,
                last_event_path=self._last_event_path,
                last_error=self._last_error,
                config=self._config.to_public_dict(),
            )

    def set_notifier(self, notifier: NotifyFn) -> None:
        with self._lock:
            self._notifier = notifier

    def reload_config(self) -> WatcherConfig:
        cfg = load_watcher_config(config_path=self._config_path)
        self.apply_config(cfg)
        return cfg

    def apply_config(self, cfg: WatcherConfig) -> None:
        with self._lock:
            self._config = cfg
            self._paths = self._normalize_paths(cfg.paths)
            self._dedup = _ProcessedTTL(ttl_seconds=cfg.dedupe_ttl_seconds)
            # restart observer to apply recursion/paths
            if self._observer is not None:
                self._restart_observer_locked()
            # restart pool if needed
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = None
            if self._dispatcher is not None and self._dispatcher.is_alive():
                # pool will be recreated on next start if enabled
                pass

    def set_paths(self, paths: Iterable[str]) -> None:
        with self._lock:
            self._paths = self._normalize_paths(paths)
            self._config.paths = list(self._paths)
            if self._observer is not None:
                self._restart_observer_locked()

    def start(self) -> None:
        with self._lock:
            if not self._config.enabled:
                return
            if self._observer is not None and self._observer.is_alive():
                return

            self._stop_evt.clear()
            self._start_pool_and_dispatcher_locked()
            self._start_observer_locked()

    def stop(self) -> None:
        with self._lock:
            self._stop_evt.set()
            if self._observer is not None:
                try:
                    self._observer.stop()
                    self._observer.join(timeout=5)
                finally:
                    self._observer = None

            if self._dispatcher is not None:
                try:
                    self._q.put_nowait("")
                except Exception:  # REVIEWED: broad catch
                    pass
                self._dispatcher.join(timeout=5)
                self._dispatcher = None

            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = None

            self._inflight.clear()

    def _normalize_paths(self, paths: Iterable[str]) -> list[str]:
        uniq: list[str] = []
        seen: set[str] = set()
        for p in paths:
            if not p:
                continue
            ap = str(Path(p).expanduser().resolve())
            if ap not in seen:
                uniq.append(ap)
                seen.add(ap)
        return uniq

    def _restart_observer_locked(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except (OSError, FileNotFoundError):
                pass
            self._observer = None
        self._start_observer_locked()

    def _start_observer_locked(self) -> None:
        obs = Observer()
        handler = _Handler(self._enqueue_path)
        for p in self._paths:
            try:
                if os.path.isdir(p):
                    obs.schedule(handler, p, recursive=bool(self._config.recursive))
            except Exception as e:
                self._last_error = f"Failed to schedule watch for {p}: {e}"
        obs.daemon = True
        obs.start()
        self._observer = obs

    def _start_pool_and_dispatcher_locked(self) -> None:
        if self._dispatcher is not None and self._dispatcher.is_alive():
            return
        self._pool = ThreadPoolExecutor(
            max_workers=int(self._config.worker_threads),
            thread_name_prefix="ThomasWatcherIngest",
        )
        t = threading.Thread(target=self._dispatcher_loop, name="ThomasWatcherDispatcher", daemon=True)
        t.start()
        self._dispatcher = t

    def _should_ignore(self, path: str) -> bool:
        p = Path(path)
        name = p.name
        suf = p.suffix.lower()

        if suf in set(x.lower() for x in self._config.ignore_suffixes):
            return True
        for pref in self._config.ignore_prefixes:
            if pref and name.startswith(pref):
                return True
        for glob_pat in self._config.ignore_globs:
            if glob_pat and p.match(glob_pat):
                return True
        return False

    def _enqueue_path(self, path: str) -> None:
        if not path:
            return
        if self._should_ignore(path):
            return
        if not is_supported_file(path, include_exts=self._config.include_exts):
            return

        # bounded queue with drop-oldest to survive bursts
        try:
            self._q.put_nowait(path)
        except queue.Full:
            try:
                _ = self._q.get_nowait()  # drop oldest
                self._q.put_nowait(path)
            except Exception:  # REVIEWED: broad catch
                with self._lock:
                    self._last_error = "Watcher queue full (dropping events)"

    def _wait_for_stable_file(self, path: str, timeout_s: float = 12.0, poll_s: float = 0.25) -> bool:
        """
        Wait until size+mtime stop changing across two consecutive polls.
        Helps avoid indexing partial downloads/slow writes.
        """
        start = time.time()
        last = None
        stable = 0
        p = Path(path)

        while (time.time() - start) < timeout_s:
            try:
                st = p.stat()
            except FileNotFoundError:
                time.sleep(poll_s)
                continue

            cur = (int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))))
            if last is not None and cur == last:
                stable += 1
                if stable >= 2:
                    return True
            else:
                stable = 0
            last = cur
            time.sleep(poll_s)

        return p.exists()

    def _dispatcher_loop(self) -> None:
        assert self._pool is not None
        while not self._stop_evt.is_set():
            try:
                path = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if not path:
                continue

            p = Path(path)
            if not p.exists() or not p.is_file():
                continue
            if self._should_ignore(path):
                continue

            # stable-write guard
            if not self._wait_for_stable_file(path):
                continue

            # quick stat + size guard + TTL dedupe
            try:
                st = p.stat()
                size = int(st.st_size)
                mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
            except FileNotFoundError:
                continue

            max_bytes = int(self._config.max_file_size_mb * 1024 * 1024)
            if size > max_bytes:
                with self._lock:
                    self._skipped += 1
                    self._last_error = f"Skipped {p.name}: exceeds max_file_size_mb"
                continue

            abs_path = str(p.resolve())
            key = (abs_path, size, mtime_ns)
            if self._config.dedupe and self._dedup.seen(key):
                continue

            with self._lock:
                self._last_event_path = abs_path
                if abs_path in self._inflight:
                    continue
                self._inflight.add(abs_path)

            fut = self._pool.submit(ingest_file, abs_path, self._config_path, self._config)
            fut.add_done_callback(lambda f, ap=abs_path, name=p.name: self._on_ingest_done(f, ap, name))

    def _on_ingest_done(self, fut: Future, abs_path: str, filename: str) -> None:
        try:
            res = fut.result()
            if res.indexed:
                with self._lock:
                    self._processed += 1
                    self._last_error = None
                self._notifier(f"New file detected: {filename} — indexed and ready")
            elif res.skipped:
                with self._lock:
                    self._skipped += 1
                    self._last_error = res.error
            else:
                with self._lock:
                    self._failed += 1
                    self._last_error = res.error or "Unknown ingest failure"
        except Exception as e:
            with self._lock:
                self._failed += 1
                self._last_error = str(e)
        finally:
            with self._lock:
                self._inflight.discard(abs_path)


# Singleton helpers
_singleton: WatcherService | None = None
_singleton_lock = threading.Lock()


def get_watcher_service(notifier: NotifyFn | None = None, config_path: str | None = None) -> WatcherService:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = WatcherService(notifier=notifier, config_path=config_path)
        else:
            if notifier is not None:
                _singleton.set_notifier(notifier)
        return _singleton
