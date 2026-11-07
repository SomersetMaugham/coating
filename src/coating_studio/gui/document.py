"""Document model: the open project, its file path, dirty state and undo stack.

Undo/redo covers only the data model of the layer stack and materials
(snapshots of ``Project.model_state()``).  View state, analysis settings and
optimisation runs are deliberately *not* undoable.
"""

from __future__ import annotations

import json
import os
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from coating_studio.project import Project

_MERGE_ID = 0x0C0A
_MERGE_WINDOW_S = 1.5


class _SnapshotCommand(QUndoCommand):
    def __init__(self, doc, text, before, after, merge_key=None):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after
        self.merge_key = merge_key
        self.stamp = time.monotonic()
        self._first = True

    def id(self):
        return _MERGE_ID if self.merge_key is not None else -1

    def mergeWith(self, other):
        if (other.merge_key != self.merge_key or self.merge_key is None
                or other.stamp - self.stamp > _MERGE_WINDOW_S):
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True

    def redo(self):
        if self._first:
            self._first = False
            return
        self.doc._restore(self.after)

    def undo(self):
        self.doc._restore(self.before)


class Document(QObject):
    #: emitted after any change; argument: "model" (layers/materials) or "settings"
    changed = Signal(str)
    #: emitted when a whole new project was loaded / created
    reset = Signal()
    dirty_changed = Signal(bool)
    path_changed = Signal(str)

    def __init__(self, project: Project | None = None):
        super().__init__()
        self.project = project or Project()
        self.path = ""
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(lambda clean: self.dirty_changed.emit(self.is_dirty))
        self._settings_dirty = False

    # -- state -------------------------------------------------------------
    @property
    def is_dirty(self):
        return self._settings_dirty or not self.undo_stack.isClean()

    @property
    def display_name(self):
        return os.path.basename(self.path) if self.path else self.project.name

    # -- editing -----------------------------------------------------------
    def edit(self, text, mutator, merge_key=None):
        """Apply ``mutator(project)`` as one undoable step.  Exceptions abort the edit."""
        before = self.project.model_state()
        try:
            mutator(self.project)
        except Exception:
            self.project.restore_model_state(before)
            raise
        after = self.project.model_state()
        if json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True):
            return
        self.undo_stack.push(_SnapshotCommand(self, text, before, after, merge_key))
        self.changed.emit("model")

    def edit_settings(self, mutator):
        """Change analysis/optimisation settings (not undoable, but marks the file dirty)."""
        mutator(self.project)
        was = self.is_dirty
        self._settings_dirty = True
        if not was:
            self.dirty_changed.emit(True)
        self.changed.emit("settings")

    def mark_dirty(self):
        """Something saved with the file but outside the model and settings changed (comparison curves)."""
        was = self.is_dirty
        self._settings_dirty = True
        if not was:
            self.dirty_changed.emit(True)

    def _restore(self, state):
        self.project.restore_model_state(state)
        self.changed.emit("model")

    # -- files -------------------------------------------------------------
    def set_project(self, project: Project, path=""):
        self.project = project
        self.path = path
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._settings_dirty = False
        self.path_changed.emit(path)
        self.dirty_changed.emit(False)
        self.reset.emit()

    def save(self, path=None):
        path = path or self.path
        self.project.save(path)
        self.path = path
        self.undo_stack.setClean()
        self._settings_dirty = False
        self.path_changed.emit(path)
        self.dirty_changed.emit(False)
