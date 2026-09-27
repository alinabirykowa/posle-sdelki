"""Сериализация изменений одной попытки без блокировки остальных попыток."""

from contextlib import contextmanager
from threading import Lock, RLock


class SessionLocks:
    def __init__(self):
        self._guard = Lock()
        self._entries = {}

    @contextmanager
    def hold(self, session_id):
        # Count both active users and waiters. A waiting request must retain the
        # same lock even when the previous request releases it.
        with self._guard:
            lock, users = self._entries.get(session_id, (RLock(), 0))
            self._entries[session_id] = (lock, users + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                _, users = self._entries[session_id]
                if users == 1:
                    del self._entries[session_id]
                else:
                    self._entries[session_id] = (lock, users - 1)
