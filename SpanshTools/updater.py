import json
import logging
import os
import re
import shutil
import tempfile
import zipfile

import requests

from config import appname
from . import fsd_data

plugin_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
logger = logging.getLogger(f"{appname}.{plugin_name}")

GITHUB_REPO = "wuuthradd/EDMC-SpanshTools"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RAW_FSD_SPECS = f"https://raw.githubusercontent.com/{GITHUB_REPO}/master/SpanshTools/fsd_specs.json"
RELEASE_ARCHIVE_ROOT = "EDMC-SpanshTools"
RUNTIME_PACKAGE_DIRS = ("SpanshTools", "tksheet")
REQUIRED_ARCHIVE_PATHS = (
    "load.py",
    "version.json",
    "SpanshTools/__init__.py",
    "SpanshTools/fsd_specs.json",
    "tksheet/__init__.py",
)
USER_DATA_FILES = {
    "route.csv",
    "offset",
    "route_state.json",
    "exact_settings.json",
    "plotter_settings.json",
    "update.zip",
}


def _coerce_fsd_specs_version(value, default=1):
    try:
        version = int(value)
        if version >= 1:
            return version
    except (TypeError, ValueError):
        pass
    return default


def _normalize_fsd_specs_payload(payload, *, default_version=1):
    if isinstance(payload, dict) and "specs" in payload:
        return {
            "version": _coerce_fsd_specs_version(payload.get("version"), default_version),
            "specs": fsd_data.normalize_specs_map(payload.get("specs")),
        }
    return {
        "version": _coerce_fsd_specs_version(default_version, 1),
        "specs": fsd_data.normalize_specs_map(payload),
    }


class SpanshUpdater:
    STAGED_ARCHIVE_NAME = "update.zip"
    STAGED_METADATA_NAME = "update_pending.json"

    def __init__(self, latest_version, download_url, changelog, plugin_dir):
        self.version = latest_version
        self.download_url = download_url
        self.plugin_dir = plugin_dir
        self.changelog = changelog

    @classmethod
    def load_staged_metadata(cls, plugin_dir):
        metadata_path = os.path.join(plugin_dir, cls.STAGED_METADATA_NAME)
        archive_path = os.path.join(plugin_dir, cls.STAGED_ARCHIVE_NAME)
        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        except Exception:
            logger.warning("Failed to read staged update metadata", exc_info=True)
            return None
        if not isinstance(payload, dict):
            cls._clear_staged_artifacts_for(plugin_dir)
            return None
        if not os.path.exists(archive_path):
            cls._clear_staged_artifacts_for(plugin_dir)
            return None
        if not zipfile.is_zipfile(archive_path):
            logger.warning("Discarding invalid staged update archive")
            cls._clear_staged_artifacts_for(plugin_dir)
            return None
        version = str(payload.get("version", "")).strip()
        if not version:
            cls._clear_staged_artifacts_for(plugin_dir)
            return None
        return {
            "version": version,
            "download_url": str(payload.get("download_url", "")).strip(),
        }

    @staticmethod
    def release_asset_name(version):
        return f"{RELEASE_ARCHIVE_ROOT}-v{version}.zip"

    @staticmethod
    def _fsd_specs_path(plugin_dir):
        return os.path.join(plugin_dir, "SpanshTools", "fsd_specs.json")

    @classmethod
    def _load_local_fsd_specs(cls, plugin_dir):
        try:
            with open(cls._fsd_specs_path(plugin_dir), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        except Exception:
            logger.warning("Failed to read local fsd_specs.json", exc_info=True)
            return None
        normalized = _normalize_fsd_specs_payload(payload)
        return normalized if normalized.get("specs") else None

    @classmethod
    def _save_local_fsd_specs(cls, plugin_dir, payload):
        cls._atomic_write_json(cls._fsd_specs_path(plugin_dir), payload)

    @classmethod
    def _reload_local_fsd_specs(cls, plugin_dir):
        expected_path = os.path.abspath(cls._fsd_specs_path(plugin_dir))
        actual_path = os.path.abspath(fsd_data.bundled_data_file_path())
        if expected_path != actual_path:
            return True
        return fsd_data.reload_specs_from_bundled_data()

    @staticmethod
    def _fetch_repo_fsd_specs():
        try:
            response = requests.get(GITHUB_RAW_FSD_SPECS, timeout=10)
            if response.status_code != 200:
                logger.debug("FSD specs fetch returned %s", response.status_code)
                return None
            payload = json.loads(response.content)
        except Exception as exc:
            logger.debug("FSD specs update check failed: %s", exc)
            return None
        normalized = _normalize_fsd_specs_payload(payload)
        return normalized if normalized.get("specs") else None

    @classmethod
    def sync_repo_fsd_specs(cls, plugin_dir):
        remote_payload = cls._fetch_repo_fsd_specs()
        if remote_payload is None:
            return False

        local_payload = cls._load_local_fsd_specs(plugin_dir)
        local_version = int((local_payload or {}).get("version", 0))
        remote_version = int(remote_payload.get("version", 0))
        if remote_version <= local_version:
            return False

        cls._save_local_fsd_specs(plugin_dir, remote_payload)
        if not cls._reload_local_fsd_specs(plugin_dir):
            logger.warning("Updated bundled fsd_specs.json on disk but failed to reload runtime specs")
            return False
        logger.info("Updated bundled fsd_specs.json from repository")
        return True

    @classmethod
    def _clear_staged_artifacts_for(cls, plugin_dir):
        for name in (cls.STAGED_ARCHIVE_NAME, cls.STAGED_METADATA_NAME):
            path = os.path.join(plugin_dir, name)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning("Failed to remove staged update artifact: %s", path, exc_info=True)

    def _clear_staged_artifacts(self):
        self._clear_staged_artifacts_for(self.plugin_dir)

    def _staged_archive_path(self):
        return os.path.join(self.plugin_dir, self.STAGED_ARCHIVE_NAME)

    def _staged_metadata_path(self):
        return os.path.join(self.plugin_dir, self.STAGED_METADATA_NAME)

    @staticmethod
    def _atomic_write_json(path, payload):
        target_dir = os.path.dirname(path) or "."
        os.makedirs(target_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".spansh_json.",
            suffix=".tmp",
            dir=target_dir,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(temp_path, path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                logger.debug("Failed to clean up temporary JSON file", exc_info=True)

    @staticmethod
    def _safe_extract_path(staging_dir, rel_path):
        normalized = os.path.normpath(rel_path).lstrip("/\\")
        if normalized in ("", "."):
            return None
        if normalized.startswith("..") or os.path.isabs(normalized):
            raise RuntimeError(f"Unsafe archive path: {rel_path}")
        destination = os.path.join(staging_dir, normalized)
        staging_root = os.path.abspath(staging_dir)
        destination_abs = os.path.abspath(destination)
        if os.path.commonpath([staging_root, destination_abs]) != staging_root:
            raise RuntimeError(f"Archive path escapes staging dir: {rel_path}")
        return destination

    def is_staged(self):
        return os.path.exists(self._staged_archive_path())

    def stage(self):
        """Download the update archive to the plugin directory for later install."""
        temp_path = f"{self._staged_archive_path()}.partial"
        try:
            logger.info("Downloading staged SpanshTools %s from %s", self.version, self.download_url)
            response = requests.get(self.download_url, timeout=30)
            if response.status_code != 200:
                logger.warning("Failed to download staged update: HTTP %s", response.status_code)
                return False
            with open(temp_path, "wb") as handle:
                handle.write(response.content)
            if not zipfile.is_zipfile(temp_path):
                logger.warning("Failed to stage update: downloaded artifact is not a valid zip archive")
                return False
            os.replace(temp_path, self._staged_archive_path())
            self._atomic_write_json(
                self._staged_metadata_path(),
                {
                    "version": self.version,
                    "download_url": self.download_url,
                },
            )
            return True
        except Exception:
            logger.warning("Failed to stage update", exc_info=True)
            return False
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def install(self):
        """Download, stage, and install immediately."""
        if not self.stage():
            return False
        return self.install_staged()

    def install_staged(self):
        """Install a previously staged update archive."""
        staged_zip = self._staged_archive_path()
        if not os.path.exists(staged_zip):
            return False
        if not zipfile.is_zipfile(staged_zip):
            self._clear_staged_artifacts()
            return False
        installed = self._install_from_zip(staged_zip)
        if installed:
            self._clear_staged_artifacts()
        return installed

    def _extract_archive(self, zip_path, staging_dir):
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.namelist()
            top_dirs = {member.split("/")[0] for member in members if "/" in member}
            prefix = top_dirs.pop() + "/" if len(top_dirs) == 1 else ""

            extracted_files = set()
            for member in members:
                if member.endswith("/"):
                    continue
                rel_path = member[len(prefix):] if prefix and member.startswith(prefix) else member
                if not rel_path:
                    continue
                dest = self._safe_extract_path(staging_dir, rel_path)
                if dest is None:
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with archive.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted_files.add(rel_path)
        return extracted_files

    def _validate_staging_dir(self, staging_dir):
        missing = [
            path
            for path in REQUIRED_ARCHIVE_PATHS
            if not os.path.exists(os.path.join(staging_dir, path))
        ]
        if missing:
            raise RuntimeError(f"Update archive is missing required files: {missing}")

    def _backup_existing_entries(self, backup_dir, package_dirs, top_level_files):
        os.makedirs(backup_dir, exist_ok=True)
        for entry in package_dirs:
            source = os.path.join(self.plugin_dir, entry)
            if os.path.isdir(source):
                shutil.copytree(source, os.path.join(backup_dir, entry))
        for entry in top_level_files:
            source = os.path.join(self.plugin_dir, entry)
            if os.path.isfile(source):
                shutil.copy2(source, os.path.join(backup_dir, entry))

    def _restore_backup_entries(self, backup_dir, package_dirs, top_level_files):
        for entry in package_dirs:
            dest = os.path.join(self.plugin_dir, entry)
            backup_entry = os.path.join(backup_dir, entry)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            if os.path.isdir(backup_entry):
                shutil.copytree(backup_entry, dest)

        for entry in top_level_files:
            dest = os.path.join(self.plugin_dir, entry)
            if os.path.exists(dest):
                os.remove(dest)
            backup_entry = os.path.join(backup_dir, entry)
            if os.path.isfile(backup_entry):
                shutil.copy2(backup_entry, dest)

    def _install_runtime_packages(self, staging_dir, package_dirs):
        for entry in package_dirs:
            source = os.path.join(staging_dir, entry)
            dest = os.path.join(self.plugin_dir, entry)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.copytree(source, dest)

    def _install_top_level_files(self, staging_dir, top_level_files):
        for entry in top_level_files:
            source = os.path.join(staging_dir, entry)
            dest = os.path.join(self.plugin_dir, entry)
            shutil.copy2(source, dest)

    def _install_from_zip(self, zip_path):
        """Extract and install an already-downloaded archive."""
        temp_root = tempfile.mkdtemp(prefix="spansh_update_", dir=self.plugin_dir)
        staging_dir = os.path.join(temp_root, "staging")
        backup_dir = os.path.join(temp_root, "backup")
        package_dirs = list(RUNTIME_PACKAGE_DIRS)
        install_committed = False
        backup_created = False

        try:
            self._extract_archive(zip_path, staging_dir)
            self._validate_staging_dir(staging_dir)
            top_level_files = sorted(
                entry
                for entry in os.listdir(staging_dir)
                if os.path.isfile(os.path.join(staging_dir, entry)) and entry not in USER_DATA_FILES
            )
            self._backup_existing_entries(backup_dir, package_dirs, top_level_files)
            backup_created = True
            self._install_runtime_packages(staging_dir, package_dirs)
            self._install_top_level_files(staging_dir, top_level_files)
            install_committed = True
            logger.info("SpanshTools %s installed successfully", self.version)
            return True
        except Exception as exc:
            if not install_committed:
                try:
                    if backup_created:
                        self._restore_backup_entries(backup_dir, package_dirs, top_level_files)
                except Exception:
                    logger.warning("Failed to restore plugin files after update error", exc_info=True)
            logger.warning("Failed to install update: %s", exc)
            return False
        finally:
            try:
                if os.path.isdir(temp_root):
                    shutil.rmtree(temp_root)
            except Exception:
                pass

    @classmethod
    def _select_release_asset_url(cls, release_data, version):
        assets = release_data.get("assets", [])
        if not isinstance(assets, list):
            assets = []

        expected_name = cls.release_asset_name(version)
        for asset in assets:
            if asset.get("name") == expected_name:
                url = str(asset.get("browser_download_url", "")).strip()
                if url:
                    return url
        return ""

    @staticmethod
    def check_latest():
        """Query GitHub API for the latest release. Returns (version, download_url, changelog) or None."""
        try:
            response = requests.get(GITHUB_API_LATEST, timeout=5)
            if response.status_code != 200:
                logger.debug("GitHub API returned %s", response.status_code)
                return None

            data = json.loads(response.content)
            tag = data.get("tag_name", "")
            version = tag.lstrip("v")
            changelog = data.get("body", "") or ""
            download_url = SpanshUpdater._select_release_asset_url(data, version)

            if not version or not download_url or SpanshUpdater._parse_version(version) is None:
                return None

            return version, download_url, changelog
        except Exception as exc:
            logger.debug("Update check failed: %s", exc)
            return None

    @staticmethod
    def _parse_version(version):
        normalized = str(version or "").strip().lstrip("vV")
        if not normalized:
            return None

        normalized = normalized.split("+", 1)[0]
        core, sep, prerelease = normalized.partition("-")

        core_parts = []
        for part in core.split("."):
            if not part:
                core_parts.append(0)
                continue
            if part.isdigit():
                core_parts.append(int(part))
                continue
            match = re.match(r"^(\d+)([A-Za-z].*)$", part)
            if not match:
                return None
            core_parts.append(int(match.group(1)))
            tail = match.group(2)
            prerelease = f"{tail}.{prerelease}" if prerelease else tail

        prerelease_parts = None
        if prerelease:
            prerelease_parts = []
            for part in re.split(r"[.\-_]", prerelease):
                if not part:
                    continue
                if part.isdigit():
                    prerelease_parts.append((0, int(part)))
                else:
                    prerelease_parts.append((1, part.lower()))

        return tuple(core_parts), tuple(prerelease_parts or ())

    @staticmethod
    def is_newer_version(latest_version, current_version):
        latest = SpanshUpdater._parse_version(latest_version)
        current = SpanshUpdater._parse_version(current_version)
        if latest is None or current is None:
            return False

        latest_core, latest_pre = latest
        current_core, current_pre = current
        max_len = max(len(latest_core), len(current_core))
        latest_core = latest_core + (0,) * (max_len - len(latest_core))
        current_core = current_core + (0,) * (max_len - len(current_core))
        if latest_core != current_core:
            return latest_core > current_core

        if not latest_pre and current_pre:
            return True
        if latest_pre and not current_pre:
            return False
        if not latest_pre and not current_pre:
            return False

        max_len = max(len(latest_pre), len(current_pre))
        for index in range(max_len):
            if index >= len(latest_pre):
                return False
            if index >= len(current_pre):
                return True
            latest_part = latest_pre[index]
            current_part = current_pre[index]
            if latest_part == current_part:
                continue
            return latest_part > current_part
        return False
