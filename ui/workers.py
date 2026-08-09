"""
Background workers for AIO Runtime Installer.

ScanWorker runs every component's presence/version check off the UI thread
(registry reads are cheap but version-resolver calls hit the network, and
32+ components in a row would otherwise freeze the window on launch).

InstallWorker runs the PS1's Install-Component pattern faithfully: skip if
already installed, run the installer if not, then re-check presence
afterward so "Installed" in the summary always means "verified present,"
never just "the installer's exit code looked fine."
"""

import shutil
from enum import Enum, auto

from PyQt6.QtCore import QThread, pyqtSignal

from core.definitions import Component, InstallContext, InstalledState
from core.logger import get_logger
from core.paths import get_app_dir


class ScanWorker(QThread):
    component_scanned = pyqtSignal(str, object, object)  # key, InstalledState, LatestInfo|None
    finished_scan = pyqtSignal()

    def __init__(self, components: list[Component], parent=None):
        super().__init__(parent)
        self.components = components

    def run(self):
        for component in self.components:
            try:
                state = component.is_installed()
            except Exception:
                state = InstalledState(installed=False)
            latest = None
            if component.resolve_latest is not None:
                try:
                    latest = component.resolve_latest()
                except Exception:
                    latest = None
            self.component_scanned.emit(component.key, state, latest)
        self.finished_scan.emit()


class ResultStatus(Enum):
    INSTALLED = auto()
    SKIPPED = auto()
    FAILED = auto()


class InstallWorker(QThread):
    component_started = pyqtSignal(str)                       # key
    component_progress = pyqtSignal(str, str, float)           # key, message, 0..1
    component_finished = pyqtSignal(str, object)                # key, ResultStatus
    log_line = pyqtSignal(str)
    all_finished = pyqtSignal(int, int, int)                    # installed, skipped, failed

    def __init__(self, components: list[Component], selected_keys: set[str], dry_run: bool, parent=None):
        super().__init__(parent)
        self.components = [c for c in components if c.key in selected_keys]
        self.dry_run = dry_run
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        log = get_logger()
        log.add_listener(self.log_line.emit)

        app_dir = get_app_dir()
        temp_dir = app_dir / "temp_installers"
        if not self.dry_run:
            temp_dir.mkdir(parents=True, exist_ok=True)

        installed_count = 0
        skipped_count = 0
        failed_count = 0

        for component in self.components:
            if self._cancel_requested:
                break

            self.component_started.emit(component.key)

            try:
                already = component.is_installed().installed
            except Exception:
                already = False

            if already:
                log.skip(f"{component.name} already installed")
                skipped_count += 1
                self.component_finished.emit(component.key, ResultStatus.SKIPPED)
                continue

            def progress_cb(msg, frac, key=component.key):
                self.component_progress.emit(key, msg, frac)

            ctx = InstallContext(temp_dir=temp_dir, dry_run=self.dry_run, progress_cb=progress_cb)

            try:
                ran_ok = component.install(ctx)
            except Exception as e:
                log.fail(f"{component.name} threw an exception: {e}")
                failed_count += 1
                self.component_finished.emit(component.key, ResultStatus.FAILED)
                continue

            if not ran_ok:
                log.fail(f"{component.name} install step failed (download or installer error)")
                failed_count += 1
                self.component_finished.emit(component.key, ResultStatus.FAILED)
                continue

            if self.dry_run:
                log.dry(f"Skipping post-install verification for {component.name} (dry run)")
                installed_count += 1
                self.component_finished.emit(component.key, ResultStatus.INSTALLED)
                continue

            try:
                verified = component.is_installed().installed
            except Exception:
                verified = False

            if verified:
                log.success(f"{component.name} installed")
                installed_count += 1
                self.component_finished.emit(component.key, ResultStatus.INSTALLED)
            else:
                log.fail(f"{component.name} installer exited cleanly but could not be verified afterward (may need a reboot to finish)")
                failed_count += 1
                self.component_finished.emit(component.key, ResultStatus.FAILED)

        if not self.dry_run:
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.status("Removed temp_installers")

        log.status(f"Finished. Installed={installed_count} Skipped={skipped_count} Failed={failed_count}")
        self.all_finished.emit(installed_count, skipped_count, failed_count)
