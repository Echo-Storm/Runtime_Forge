"""
Background workers for Runtime Forge.

ScanWorker runs every component's presence/version check off the UI thread
(registry reads are cheap but version-resolver calls hit the network, and
32+ components in a row would otherwise freeze the window on launch).

InstallWorker runs the PS1's Install-Component pattern, extended with real
update handling: skip only if already installed AND (no version concept, or
already at the latest version); otherwise run the installer — which for
every versioned component here (PowerShell/Git/Node/CMake/JDK) upgrades in
place when a newer version already exists, exactly what "update available"
in the UI should actually do when acted on. Re-checks presence afterward
either way so "Installed" in the summary always means "verified present,"
never just "the installer's exit code looked fine."
"""

import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum, auto

from PyQt6.QtCore import QThread, pyqtSignal

from core import checks, http_cache, path_backup
from core.definitions import Component, InstallContext, InstalledState
from core.logger import get_logger
from core.paths import get_app_dir, get_data_dir
from core.version_resolvers import version_is_newer

MAX_SCAN_WORKERS = 8


class ScanWorker(QThread):
    component_scanned = pyqtSignal(str, object, object)  # key, InstalledState, LatestInfo|None
    finished_scan = pyqtSignal()

    def __init__(self, components: list[Component], parent=None):
        super().__init__(parent)
        self.components = components

    def run(self):
        # Each component is one independent task: its presence check (a
        # registry/file read, or a short subprocess for tools that must be
        # run to report a version - pwsh, git, node, cmake) and, for
        # versioned ones, its latest-version lookup (a read-only HTTP GET,
        # shared across components via core.http_cache). Nothing here
        # mutates state or contends for a lock the way installers do
        # (Windows Installer's single global mutex), so they all run
        # concurrently. Results are emitted as each finishes; components with
        # no version concept surface immediately.
        log = get_logger()
        # A Rescan should see the machine and the network as they are now.
        checks.invalidate_registry_cache()
        http_cache.clear()

        def scan(component):
            try:
                state = component.is_installed()
            except Exception as e:
                # Logged, not just swallowed - a genuine error here (a
                # permission-denied registry read, a corrupted DLL) would
                # otherwise look exactly like "legitimately not installed"
                # in both the log pane and the tree, with no way to tell
                # the two apart.
                log.status(f"WARNING: {component.name} presence check raised an exception ({e})")
                state = InstalledState(installed=False)
            latest = None
            if component.resolve_latest is not None:
                try:
                    latest = component.resolve_latest()
                except Exception as e:
                    log.status(f"WARNING: {component.name} latest-version check raised an exception ({e})")
            return component.key, state, latest

        worker_count = max(1, min(MAX_SCAN_WORKERS, len(self.components)))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [pool.submit(scan, c) for c in self.components]
            for future in as_completed(futures):
                key, state, latest = future.result()
                self.component_scanned.emit(key, state, latest)

        self.finished_scan.emit()


class ResultStatus(Enum):
    INSTALLED = auto()
    SKIPPED = auto()
    FAILED = auto()


class InstallWorker(QThread):
    component_started = pyqtSignal(str)                        # key
    component_progress = pyqtSignal(str, str, float)            # key, message, 0..1
    component_finished = pyqtSignal(str, object, str)            # key, ResultStatus, warning message ("" if none)
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
        # Captured once into a local, not re-accessed via self.log_line.emit
        # a second time below — PyQt's bound-signal .emit returns a fresh,
        # non-equal wrapper object on every attribute access (confirmed:
        # `obj.sig.emit == obj.sig.emit` is False), unlike a plain Python
        # bound method. remove_listener() uses list.remove(), which needs
        # the exact same object identity/equality it was given at
        # add_listener() time — passing a fresh access here would silently
        # fail to find it, leaving the "removed" listener still registered.
        listener = self.log_line.emit
        log.add_listener(listener)
        try:
            self._run(log)
        finally:
            # Logger is a long-lived module singleton — without this, every
            # Install run leaves its listener registered forever, so a
            # second run in the same session double-emits every log line
            # (once via its own connection, once via the first run's
            # still-registered listener) and the duplication compounds with
            # each further run.
            log.remove_listener(listener)

    def _run(self, log):
        app_dir = get_app_dir()
        temp_dir = app_dir / "temp_installers"
        if not self.dry_run:
            temp_dir.mkdir(parents=True, exist_ok=True)
            # One backup per batch (an "Install Selected" click), not one per
            # component in it — installing 5 things makes 1 backup, not 5.
            # This is a safety net for PATH itself getting mangled, separate
            # from each component's own "set PATH correctly" install flags.
            backup_path = path_backup.create_backup(
                get_data_dir(), f"before installing {len(self.components)} component(s)"
            )
            if backup_path:
                log.status(f"PATH backed up to {backup_path.name}")
            else:
                log.status("Could not read current PATH to back it up - continuing anyway")
        else:
            log.dry("Skipping PATH backup (dry run — nothing will change)")

        installed_count = 0
        skipped_count = 0
        failed_count = 0

        for component in self.components:
            if self._cancel_requested:
                break

            self.component_started.emit(component.key)

            checks.invalidate_registry_cache()
            try:
                state = component.is_installed()
            except Exception as e:
                log.status(f"WARNING: {component.name} presence check raised an exception ({e}) - treating as not installed")
                state = InstalledState(installed=False)

            if state.installed:
                update_available = False
                update_check_failed = False
                if component.resolve_latest is not None:
                    try:
                        latest = component.resolve_latest()
                        update_available = latest is not None and version_is_newer(latest.version, state.version or "")
                    except Exception as e:
                        # A failed update check must not look identical to a
                        # confirmed "already current" - otherwise a transient
                        # network error (or a GitHub rate limit, which this
                        # app hits routinely) silently leaves an outdated
                        # component in place with a log line implying
                        # nothing was wrong.
                        update_check_failed = True
                        log.status(f"WARNING: {component.name} update check failed ({e}) - leaving it as-is rather than guessing")

                if not update_available:
                    skipped_count += 1
                    if update_check_failed:
                        log.skip(f"{component.name} already installed (update check failed - see warning above)")
                        self.component_finished.emit(
                            component.key, ResultStatus.SKIPPED,
                            "update check failed - could not confirm this is the latest version",
                        )
                    else:
                        log.skip(f"{component.name} already installed")
                        self.component_finished.emit(component.key, ResultStatus.SKIPPED, "")
                    continue

                log.status(f"{component.name}: update available ({state.version} -> {latest.version}), installing")

            def progress_cb(msg, frac, key=component.key):
                self.component_progress.emit(key, msg, frac)

            ctx = InstallContext(temp_dir=temp_dir, dry_run=self.dry_run, progress_cb=progress_cb)

            try:
                ran_ok = component.install(ctx)
            except Exception as e:
                log.fail(f"{component.name} threw an exception: {e}")
                failed_count += 1
                self.component_finished.emit(component.key, ResultStatus.FAILED, "")
                continue

            if not ran_ok:
                log.fail(f"{component.name} install step failed (download or installer error)")
                failed_count += 1
                self.component_finished.emit(component.key, ResultStatus.FAILED, "")
                continue

            if self.dry_run:
                log.dry(f"Skipping post-install verification for {component.name} (dry run)")
                installed_count += 1
                self.component_finished.emit(component.key, ResultStatus.INSTALLED, "")
                continue

            checks.invalidate_registry_cache()
            try:
                verified = component.is_installed().installed
            except Exception:
                verified = False

            if not verified:
                log.fail(f"{component.name} installer exited cleanly but could not be verified afterward (may need a reboot to finish)")
                failed_count += 1
                self.component_finished.emit(component.key, ResultStatus.FAILED, "")
                continue

            # The install and its own presence check both succeeded — but
            # that check runs several of these binaries by absolute path,
            # not through PATH resolution, so it would never notice PATH
            # itself failing to update even though every installer here
            # requests it (ADD_PATH=1, PrependPath=1, etc).
            path_warning = ""
            if component.path_entry is not None:
                try:
                    entry = component.path_entry()
                    if entry is not None and not checks.is_dir_on_path(entry):
                        path_warning = f"installed but {entry} is not on PATH"
                        log.status(f"WARNING: {component.name} {path_warning} - you may need to restart your terminal or add it manually")
                except Exception:
                    pass

            log.success(f"{component.name} installed")
            installed_count += 1
            self.component_finished.emit(component.key, ResultStatus.INSTALLED, path_warning)

        if not self.dry_run:
            shutil.rmtree(temp_dir, ignore_errors=True)
            log.status("Removed temp_installers")

        log.status(f"Finished. Installed={installed_count} Skipped={skipped_count} Failed={failed_count}")
        self.all_finished.emit(installed_count, skipped_count, failed_count)


class UninstallWorker(QThread):
    """Runs a single component's uninstall() off the UI thread - real
    uninstall commands (msiexec /x, a vendor uninstaller) can take a while
    and would otherwise freeze the window, same reasoning as InstallWorker."""
    log_line = pyqtSignal(str)
    finished_uninstall = pyqtSignal(str, bool)  # key, success

    def __init__(self, component: Component, dry_run: bool, parent=None):
        super().__init__(parent)
        self.component = component
        self.dry_run = dry_run

    def run(self):
        log = get_logger()
        # Same identity-capture discipline as InstallWorker.run() above —
        # see its comment for why a fresh self.log_line.emit access here
        # would silently break remove_listener().
        listener = self.log_line.emit
        log.add_listener(listener)
        try:
            app_dir = get_app_dir()
            temp_dir = app_dir / "temp_installers"
            if not self.dry_run:
                temp_dir.mkdir(parents=True, exist_ok=True)

            ctx = InstallContext(temp_dir=temp_dir, dry_run=self.dry_run)
            try:
                ok = self.component.uninstall(ctx)
            except Exception as e:
                log.fail(f"{self.component.name} uninstall threw an exception: {e}")
                ok = False

            checks.invalidate_registry_cache()
            self.finished_uninstall.emit(self.component.key, ok)
        finally:
            log.remove_listener(listener)
