# -*- coding: utf-8 -*-
"""Small background workers so OCR / network calls never freeze the UI."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from . import lmstudio, ocr
from .config import AppConfig


# QObject instances need a live owner. A bare `_Signals()` with no parent gets
# destroyed together with the QRunnable's Python wrapper once the pool finishes,
# which produced "RuntimeError: Signal source has been deleted" when the slot
# ran late. Registering each emitter with a module-level list keeps the C++
# object alive for the lifetime of the process.
_EMITTERS: list = []


def _emitter() -> "_Signals":
    sig = _Signals()
    _EMITTERS.append(sig)
    # Cap growth: these are tiny objects and old ones are already disconnected.
    if len(_EMITTERS) > 200:
        del _EMITTERS[:100]
    return sig


class _Signals(QObject):
    finished = Signal(object)   # payload
    progress = Signal(object)   # streaming updates (dict)


class OCRTask(QRunnable):
    def __init__(self, image, backend: str, language: str):
        super().__init__()
        self.signals = _emitter()
        self._image = image
        self._backend = backend
        self._language = language

    @Slot()
    def run(self) -> None:
        try:
            result = ocr.run_ocr(self._image, self._backend, self._language)
        except Exception as exc:      # never let a worker crash the pool
            result = ocr.OCRResult(error=str(exc))
        self.signals.finished.emit(result)


class TranslateTask(QRunnable):
    """Translate one region while streaming progress to the dialog.

    Emits `progress` dicts so the status strip can show the live provider,
    model, generation speed and first-token latency. Finished payload is
    (ok, text_or_error, metrics_dict).
    """

    def __init__(self, text: str, config: AppConfig, model: str = ""):
        super().__init__()
        self.signals = _emitter()
        self._text = text
        self._config = config
        self._model = model
        self.result = None
        self.done = False

    def _emit(self, payload: dict) -> None:
        try:
            self.signals.progress.emit(payload)
        except Exception:
            pass

    @Slot()
    def run(self) -> None:
        metrics: dict = {}
        try:
            if self._model:
                # An explicit override (e.g. a model picked by hand) applies to
                # whatever provider is currently configured.
                opts = lmstudio.provider_settings(self._config)
                text = lmstudio.translate_text(
                    self._text, opts["base_url"], self._model,
                    opts["temperature"], api_key=opts["api_key"],
                    service=opts["service"], api_style=opts["api_style"])
                metrics = {"provider": opts["service"], "model": self._model}
            else:
                outcome = lmstudio.translate_with_metrics(
                    self._text, self._config, on_event=self._emit)
                text = outcome.text
                metrics = {
                    "provider": outcome.provider,
                    "model": outcome.model,
                    "ttft": outcome.ttft,
                    "speed": outcome.speed,
                    "tokens": outcome.tokens,
                    "estimated": outcome.estimated,
                    "summary": outcome.summary(),
                }
            self.result = (True, text, metrics)
        except Exception as exc:
            self.result = (False, str(exc), metrics)
        self.done = True
        try:
            self.signals.finished.emit(self.result)
        except Exception:
            pass


class ModelDownloadTask(QRunnable):
    """Download the manga-ocr weights in the background."""

    def __init__(self, use_mirror: bool = True):
        super().__init__()
        self.signals = _emitter()
        self._use_mirror = use_mirror
        self.result: tuple[bool, str] | None = None
        self.done = False

    @Slot()
    def run(self) -> None:
        def report(done: int, total: int, label: str) -> None:
            try:
                self.signals.progress.emit({"kind": "download", "done": done,
                                            "total": total, "label": label})
            except Exception:
                pass

        try:
            ok, message = ocr.download_model(progress=report,
                                             use_mirror=self._use_mirror)
        except Exception as exc:
            ok, message = False, str(exc)
        self.result = (ok, message)
        self.done = True
        try:
            self.signals.finished.emit(self.result)
        except Exception:
            pass


class ModelLabelTask(QRunnable):
    """Resolve the active model name off the UI thread.

    Deliberately uses a plain attribute + polling instead of a signal: the
    signal emission from this short-lived task proved unreliable when the
    owning dialog was only shown (not inside exec()), producing
    "Signal source has been deleted".
    """

    def __init__(self, config):
        super().__init__()
        self.signals = _emitter()
        self._config = config
        # Polled by the caller; None means "still running".
        self.result: str | None = None
        self.done = False

    @Slot()
    def run(self) -> None:
        try:
            label = lmstudio.active_model_label(self._config)
        except Exception:
            label = ""
        self.result = label
        self.done = True
        try:
            self.signals.finished.emit(label)
        except Exception:
            # The signal may already be gone; the polled value still works.
            pass


class ProviderProbeTask(QRunnable):
    """Test the configured translation provider (local or cloud)."""

    def __init__(self, config):
        super().__init__()
        self.signals = _emitter()
        self._config = config

    @Slot()
    def run(self) -> None:
        try:
            ok, message, models = lmstudio.test_provider(self._config)
        except Exception as exc:
            ok, message, models = False, str(exc), []
        self.signals.finished.emit((ok, message, models))


class ModelProbeTask(QRunnable):
    def __init__(self, base_url: str):
        super().__init__()
        self.signals = _emitter()
        self._base_url = base_url

    @Slot()
    def run(self) -> None:
        ok, message, models = lmstudio.test_connection(self._base_url)
        self.signals.finished.emit((ok, message, models))


def _pool() -> QThreadPool:
    return QThreadPool.globalInstance()


# PySide6 does not keep a Python reference to a started QRunnable, so the task
# (and its signal object) can be collected while it is still running, which
# produces "RuntimeError: Signal source has been deleted" and drops the result.
# Hold every started task until it reports back.
#
# The release is deliberately conservative: entries are dropped only after a
# short delay on the UI thread, so the emission has certainly finished by then.
_ACTIVE: dict[int, object] = {}
_SEQ = [0]


def start_task(task: QRunnable, pool: QThreadPool | None = None) -> None:
    task.setAutoDelete(False)
    _SEQ[0] += 1
    token = _SEQ[0]
    _ACTIVE[token] = task

    def _release(*_args) -> None:
        QTimer.singleShot(500, lambda: _ACTIVE.pop(token, None))

    task.signals.finished.connect(_release)
    (pool or _pool()).start(task)
