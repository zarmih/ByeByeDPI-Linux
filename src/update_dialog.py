from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from update_manager import UpdateError, UpdateManager, UpdatePreview, validate_proxy_url


class PreviewWorker(QThread):
    preview_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, manager: UpdateManager, kind: str, proxy: str | None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.kind = kind
        self.proxy = proxy

    def run(self):
        try:
            preview = self.manager.preview_remote(self.kind, self.proxy)
        except UpdateError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # defensive boundary for the worker thread
            self.failed.emit(f"Unexpected updater error: {exc}")
            return
        self.preview_ready.emit(preview)


class UpdateDialog(QDialog):
    data_updated = Signal(str)

    def __init__(self, data_dir: str | os.PathLike[str], parent=None, *, manager=None):
        super().__init__(parent)
        self.setWindowTitle("Update Strategies and Targets")
        self.resize(760, 560)
        self.settings = QSettings("ByeByeDPI", "ByeByeDPI-Linux")
        self.manager = manager or UpdateManager(data_dir)
        self.current_preview: UpdatePreview | None = None
        self.worker: PreviewWorker | None = None

        layout = QVBoxLayout(self)

        source_label = QLabel(
            "Official source: romanvht/ByeByeDPI. Preview fetches a full commit SHA, "
            "validates the candidate, and shows a content diff. Nothing is executed automatically."
        )
        source_label.setWordWrap(True)
        layout.addWidget(source_label)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Data:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Strategies", "strategies")
        self.kind_combo.addItem("Test targets", "targets")
        controls.addWidget(self.kind_combo)

        controls.addWidget(QLabel("HTTP proxy:"))
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("Optional, e.g. http://127.0.0.1:10808")
        self.proxy_input.setText(self.settings.value("updates/proxy", "", type=str))
        controls.addWidget(self.proxy_input, 1)
        layout.addLayout(controls)

        buttons = QHBoxLayout()
        self.preview_btn = QPushButton("Preview Update")
        self.preview_btn.clicked.connect(self.start_preview)
        buttons.addWidget(self.preview_btn)

        self.apply_btn = QPushButton("Apply Preview")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_preview)
        buttons.addWidget(self.apply_btn)

        self.backup_combo = QComboBox()
        self.backup_combo.setMinimumWidth(250)
        buttons.addWidget(self.backup_combo, 1)

        self.rollback_btn = QPushButton("Rollback Backup")
        self.rollback_btn.clicked.connect(self.rollback_backup)
        buttons.addWidget(self.rollback_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.status_label = QLabel("Choose a data set and request a preview.")
        layout.addWidget(self.status_label)

        self.report_area = QTextEdit()
        self.report_area.setReadOnly(True)
        layout.addWidget(self.report_area, 1)

        self.kind_combo.currentIndexChanged.connect(self.invalidate_preview)
        self.proxy_input.textChanged.connect(self.invalidate_preview)
        self.refresh_backups()

    @staticmethod
    def _interactive() -> bool:
        return os.environ.get("QT_QPA_PLATFORM") != "offscreen"

    def selected_kind(self) -> str:
        return str(self.kind_combo.currentData())

    def invalidate_preview(self, *_):
        self.current_preview = None
        self.apply_btn.setEnabled(False)

    def _set_busy(self, busy: bool):
        self.preview_btn.setEnabled(not busy)
        self.kind_combo.setEnabled(not busy)
        self.proxy_input.setEnabled(not busy)
        self.close_btn.setEnabled(not busy)
        if busy:
            self.apply_btn.setEnabled(False)

    def start_preview(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            proxy = validate_proxy_url(self.proxy_input.text())
        except UpdateError as exc:
            self._show_error(str(exc))
            return

        self.settings.setValue("updates/proxy", proxy or "")
        self.settings.sync()
        self.invalidate_preview()
        self._set_busy(True)
        self.status_label.setText("Fetching commit metadata and validating upstream assets…")
        self.report_area.clear()

        self.worker = PreviewWorker(self.manager, self.selected_kind(), proxy, self)
        self.worker.preview_ready.connect(self._preview_ready)
        self.worker.failed.connect(self._preview_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_finished(self):
        self._set_busy(False)
        self.worker = None

    def _preview_ready(self, preview: UpdatePreview):
        self.current_preview = preview
        self.report_area.setPlainText(preview.report())
        total_changes = sum(
            preview.diff.get(key, 0)
            for key in ("added_count", "removed_count", "changed_count")
        )
        metadata_changed = bool(preview.diff.get("metadata_changed"))
        if total_changes:
            summary = f"{total_changes} content change(s) found."
        elif metadata_changed:
            summary = "Content is unchanged, but the verified upstream revision changed."
        else:
            summary = "No content or source revision changes found."
        self.status_label.setText("Preview validated. " + summary)
        self.apply_btn.setEnabled(total_changes > 0 or metadata_changed)

    def _preview_failed(self, message: str):
        self.current_preview = None
        self.report_area.setPlainText(message)
        self.status_label.setText("Preview failed. No local data was changed.")
        self._show_error(message)

    def apply_preview(self):
        preview = self.current_preview
        if preview is None:
            self._show_error("Run and review Preview Update first.")
            return
        if self._interactive():
            answer = QMessageBox.question(
                self,
                "Apply Validated Update",
                "A backup of the current JSON will be created before the atomic replacement.\n\n"
                "Apply this validated preview?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            backup = self.manager.apply(preview)
        except UpdateError as exc:
            self._show_error(str(exc))
            return
        self.status_label.setText(f"Update applied. Backup: {backup.name}")
        self.report_area.append("\nApplied successfully. New strategy arguments were not executed.")
        self.current_preview = None
        self.apply_btn.setEnabled(False)
        self.refresh_backups(preview.kind)
        self.data_updated.emit(preview.kind)
        if self._interactive():
            QMessageBox.information(self, "Update Applied", "Validated data was installed successfully.")

    def refresh_backups(self, preferred_kind: str | None = None):
        selected_name = self.backup_combo.currentData()
        self.backup_combo.clear()
        backups = self.manager.list_backups()
        for backup in backups:
            kind = "strategies" if backup.name.startswith("strategies_") else "targets"
            label = f"{kind}: {backup.name}"
            self.backup_combo.addItem(label, str(backup))
        if preferred_kind:
            for index in range(self.backup_combo.count()):
                if self.backup_combo.itemText(index).startswith(preferred_kind + ":"):
                    self.backup_combo.setCurrentIndex(index)
                    break
        elif selected_name:
            index = self.backup_combo.findData(selected_name)
            if index >= 0:
                self.backup_combo.setCurrentIndex(index)
        self.rollback_btn.setEnabled(self.backup_combo.count() > 0)

    def rollback_backup(self):
        backup_value = self.backup_combo.currentData()
        if not backup_value:
            self._show_error("No update backup is available.")
            return
        backup = Path(str(backup_value))
        if backup.name.startswith("strategies_"):
            kind = "strategies"
        elif backup.name.startswith("targets_"):
            kind = "targets"
        else:
            self._show_error("Selected backup has an invalid name.")
            return
        if self._interactive():
            answer = QMessageBox.question(
                self,
                "Rollback Data",
                f"Restore {backup.name}? The current JSON will be replaced.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            restored = self.manager.rollback(kind, backup)
        except UpdateError as exc:
            self._show_error(str(exc))
            return
        self.status_label.setText(f"Rollback completed from {restored.name}")
        self.report_area.setPlainText(
            f"Restored {kind} from validated backup:\n{restored.name}"
        )
        self.invalidate_preview()
        self.data_updated.emit(kind)
        if self._interactive():
            QMessageBox.information(self, "Rollback Complete", "The selected backup was restored.")

    def _show_error(self, message: str):
        self.status_label.setText(message)
        if self._interactive():
            QMessageBox.critical(self, "Update Error", message)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Wait for the current preview request to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)
