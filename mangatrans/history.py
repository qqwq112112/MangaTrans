# -*- coding: utf-8 -*-
"""Two independent snapshot histories: translation edits vs view changes.

Why snapshots instead of command objects
----------------------------------------
Every action here is small (a few RegionOps, or a page index + zoom) and every
restore path already exists ("repaint this page", "go to this page at this
zoom"). Snapshot-past/restore is therefore far less bug-prone than writing and
maintaining an inverse for each command.

Two separate stacks is the whole point: undoing a translation must not also
rewind the page you were reading, and vice versa.
"""

from __future__ import annotations

import copy
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class SnapshotHistory(Generic[T]):
    """Past / present / future stack of whole-state snapshots."""

    def __init__(self, capture: Callable[[], T],
                 restore: Callable[[T], None],
                 limit: int = 80):
        self._capture = capture
        self._restore = restore
        self._limit = max(1, limit)
        self._past: list[T] = []
        self._future: list[T] = []
        self._current: T | None = None
        self._has_baseline = False

    # ------------------------------------------------------------------ state

    def reset(self) -> None:
        """Drop all history and take the current state as the baseline."""
        self._past.clear()
        self._future.clear()
        self._current = self._capture()
        self._has_baseline = True

    def mark(self) -> None:
        """Record the current state as an undo point, BEFORE mutating.

        Usage: `history.mark()` -> mutate -> done. The pre-change state goes on
        the past stack, the future is discarded, and `commit()` is called
        automatically on the next `mark()/undo()` so callers do not have to
        pair the calls.
        """
        if not self._has_baseline:
            self.reset()
            return
        before = self._capture()
        self._past.append(before)
        if len(self._past) > self._limit:
            self._past.pop(0)
        self._future.clear()
        self._current = before

    def commit(self) -> None:
        """Record the post-change state as current (optional but tidy)."""
        if not self._has_baseline:
            self.reset()
            return
        self._current = self._capture()

    # ------------------------------------------------------------------ query

    @property
    def can_undo(self) -> bool:
        return bool(self._past)

    @property
    def can_redo(self) -> bool:
        return bool(self._future)

    @property
    def undo_depth(self) -> int:
        return len(self._past)

    @property
    def redo_depth(self) -> int:
        return len(self._future)

    # ------------------------------------------------------------------ actions

    def undo(self) -> bool:
        if not self._past:
            return False
        # The live state is the truth: capture it now rather than trusting a
        # value stashed at mark() time, which is the pre-change state.
        self._future.append(self._capture())
        target = self._past.pop()
        self._current = target
        self._restore(copy.deepcopy(target))
        return True

    def redo(self) -> bool:
        if not self._future:
            return False
        self._past.append(self._capture())
        target = self._future.pop()
        self._current = target
        self._restore(copy.deepcopy(target))
        return True


def deep_snapshot(value):
    """Snapshot helper used by the translation history (ops are mutable)."""
    return copy.deepcopy(value)
