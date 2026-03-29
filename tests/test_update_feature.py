"""Tests for update check and installer behavior."""

import io
import json
import os
import sys
import zipfile
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import SpanshTools.core as spans_mod
import update_fsd_specs
from SpanshTools import updater as updater_mod
from SpanshTools.updater import RELEASE_ARCHIVE_ROOT, SpanshUpdater
from SpanshTools.core import SpanshTools
from conftest import PLUGIN_VERSION, bump_patch, create_router


def _fsd_specs_payload(specs=None, *, version=1):
    return {
        "version": version,
        "specs": specs or {
            "int_hyperdrive_size5_class5": {
                "class": 5,
                "rating": "A",
                "optimal_mass": 1050.0,
                "max_fuel_per_jump": 5.0,
                "fuel_power": 2.45,
                "fuel_multiplier": 0.012,
                "supercharge_multiplier": 4,
            }
        },
    }


def _write_plugin_tree(
    plugin_dir,
    *,
    load_text="old-load",
    version=PLUGIN_VERSION,
    package_init_text="old-package",
    sheet_init_text="old-sheet",
    fsd_specs=None,
):
    os.makedirs(os.path.join(plugin_dir, "SpanshTools"), exist_ok=True)
    os.makedirs(os.path.join(plugin_dir, "tksheet"), exist_ok=True)
    with open(os.path.join(plugin_dir, "load.py"), "w", encoding="utf-8") as handle:
        handle.write(load_text)
    with open(os.path.join(plugin_dir, "version.json"), "w", encoding="utf-8") as handle:
        json.dump({"version": version}, handle)
    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write(package_init_text)
    with open(os.path.join(plugin_dir, "SpanshTools", "fsd_specs.json"), "w", encoding="utf-8") as handle:
        json.dump(_fsd_specs_payload(fsd_specs), handle)
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write(sheet_init_text)


def _build_release_zip(
    *,
    load_text="new-load",
    version=None,
    package_init_text="new-package",
    sheet_init_text="new-sheet",
    top_level_files=None,
    include_tksheet=True,
):
    version = version or bump_patch(PLUGIN_VERSION)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        prefix = f"{RELEASE_ARCHIVE_ROOT}/"
        archive.writestr(prefix + "load.py", load_text)
        archive.writestr(prefix + "version.json", json.dumps({"version": version}))
        archive.writestr(prefix + "SpanshTools/__init__.py", package_init_text)
        archive.writestr(
            prefix + "SpanshTools/fsd_specs.json",
            json.dumps(_fsd_specs_payload()),
        )
        if include_tksheet:
            archive.writestr(prefix + "tksheet/__init__.py", sheet_init_text)
        for name, content in (top_level_files or {}).items():
            archive.writestr(prefix + name, content)
    return buf.getvalue()


class _Response:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        if self.target:
            self.target(*self.args, **self.kwargs)


def test_parse_coriolis_list_filters_and_normalizes_entries():
    payload = [
        {
            "symbol": "Int_Hyperdrive_Size5_Class5",
            "class": 5,
            "rating": "a",
            "optmass": 1050,
            "maxfuel": 5,
            "fuelpower": 2.45,
            "fuelmul": 0.012,
        },
        {
            "symbol": "int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii",
            "class": 8,
            "rating": "A",
            "optmass": 4670,
            "maxfuel": 6.8,
            "fuelpower": 2.5025,
            "fuelmul": 0.011,
        },
        {
            "symbol": "ignored_preengineered",
            "class": 5,
            "rating": "A",
            "optmass": 1,
            "maxfuel": 1,
            "fuelpower": 1,
            "fuelmul": 1,
            "preEngineered": True,
        },
    ]

    parsed = update_fsd_specs._parse_coriolis_list(payload)

    assert parsed["int_hyperdrive_size5_class5"]["rating"] == "A"
    assert parsed["int_hyperdrive_size5_class5"]["optimal_mass"] == 1050.0
    assert parsed["int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii"]["supercharge_multiplier"] == 6
    assert "ignored_preengineered" not in parsed


def test_parse_coriolis_list_skips_entries_rejected_by_bundled_validation():
    payload = [
        {
            "symbol": "int_missing_hyperdrive",
            "class": 0,
            "rating": "Z",
            "optmass": 0,
            "maxfuel": 0,
            "fuelpower": 0,
            "fuelmul": 0,
        },
        {
            "symbol": "Int_Hyperdrive_Size5_Class5",
            "class": 5,
            "rating": "A",
            "optmass": 1050,
            "maxfuel": 5,
            "fuelpower": 2.45,
            "fuelmul": 0.012,
        },
    ]

    parsed = update_fsd_specs._parse_coriolis_list(payload)

    assert "int_missing_hyperdrive" not in parsed
    assert "int_hyperdrive_size5_class5" in parsed


def test_update_fsd_specs_main_increments_bundled_version(monkeypatch):
    monkeypatch.setattr(
        update_fsd_specs,
        "_load_current_payload",
        lambda: _fsd_specs_payload(
            {
                "int_hyperdrive_size5_class5": {
                    "class": 5,
                    "rating": "A",
                    "optimal_mass": 1050.0,
                    "max_fuel_per_jump": 5.0,
                    "fuel_power": 2.45,
                    "fuel_multiplier": 0.012,
                    "supercharge_multiplier": 4,
                }
            },
            version=1,
        ),
    )
    monkeypatch.setattr(
        update_fsd_specs,
        "_load_specs_from_network",
        lambda: {
            "int_hyperdrive_size5_class5": {
                "class": 5,
                "rating": "A",
                "optimal_mass": 1050.0,
                "max_fuel_per_jump": 5.0,
                "fuel_power": 2.45,
                "fuel_multiplier": 0.012,
                "supercharge_multiplier": 4,
            },
            "int_hyperdrive_size6_class5": {
                "class": 6,
                "rating": "A",
                "optimal_mass": 1800.0,
                "max_fuel_per_jump": 8.0,
                "fuel_power": 2.6,
                "fuel_multiplier": 0.012,
                "supercharge_multiplier": 4,
            },
        },
    )
    captured = {}
    monkeypatch.setattr(update_fsd_specs, "_atomic_write_text", lambda _path, text: captured.setdefault("payload", text))
    monkeypatch.setattr(update_fsd_specs.fsd_data, "bundled_data_file_path", lambda: "SpanshTools/fsd_specs.json")

    assert update_fsd_specs.main([]) == 0
    assert json.loads(captured["payload"])["version"] == 2


def test_release_asset_name_matches_versioned_archive_contract():
    assert SpanshUpdater.release_asset_name("4.1.0") == "EDMC-SpanshTools-v4.1.0.zip"


def test_is_newer_version_uses_real_version_ordering():
    newer_version = bump_patch(PLUGIN_VERSION)
    assert SpanshUpdater.is_newer_version(newer_version, PLUGIN_VERSION) is True
    assert SpanshUpdater.is_newer_version(PLUGIN_VERSION, newer_version) is False
    assert SpanshUpdater.is_newer_version(PLUGIN_VERSION, PLUGIN_VERSION) is False
    assert SpanshUpdater.is_newer_version(PLUGIN_VERSION, f"{PLUGIN_VERSION}-beta1") is True
    assert SpanshUpdater.is_newer_version(f"{PLUGIN_VERSION}-beta1", PLUGIN_VERSION) is False


def test_check_latest_uses_release_asset_url(monkeypatch):
    latest_version = bump_patch(PLUGIN_VERSION)
    payload = {
        "tag_name": f"v{latest_version}",
        "body": "changes",
        "assets": [
            {
                "name": SpanshUpdater.release_asset_name(latest_version),
                "browser_download_url": "https://example.invalid/EDMC-SpanshTools.zip",
            }
        ],
    }
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps(payload).encode("utf-8")),
    )

    assert SpanshUpdater.check_latest() == (
        latest_version,
        "https://example.invalid/EDMC-SpanshTools.zip",
        "changes",
    )


def test_check_latest_rejects_non_matching_zip_assets(monkeypatch):
    latest_version = bump_patch(PLUGIN_VERSION)
    payload = {
        "tag_name": f"v{latest_version}",
        "body": "changes",
        "assets": [
            {
                "name": "something-else.zip",
                "browser_download_url": "https://example.invalid/something-else.zip",
            }
        ],
    }
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps(payload).encode("utf-8")),
    )

    assert SpanshUpdater.check_latest() is None


def test_check_latest_rejects_non_semver_release_tags(monkeypatch):
    payload = {
        "tag_name": "latest",
        "body": "changes",
        "assets": [
            {
                "name": SpanshUpdater.release_asset_name("latest"),
                "browser_download_url": "https://example.invalid/latest.zip",
            }
        ],
    }
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps(payload).encode("utf-8")),
    )

    assert SpanshUpdater.check_latest() is None


def test_install_preserves_route_state_json(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    route_state_path = os.path.join(plugin_dir, "route_state.json")
    with open(route_state_path, "w", encoding="utf-8") as handle:
        handle.write('{"route": [["Sol", 0]]}')

    payload = _build_release_zip()
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(payload),
    )

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install() is True

    with open(route_state_path, "r", encoding="utf-8") as handle:
        assert handle.read() == '{"route": [["Sol", 0]]}'

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "new-package"


def test_install_updates_bundled_runtime_packages(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)

    archive_path = os.path.join(plugin_dir, "update.zip")
    with open(archive_path, "wb") as handle:
        handle.write(_build_release_zip())

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is True

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "new-package"
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "new-sheet"


def test_install_rejects_incomplete_archive(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)

    archive_path = os.path.join(plugin_dir, "update.zip")
    with open(archive_path, "wb") as handle:
        handle.write(_build_release_zip(include_tksheet=False))

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is False

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "old-package"
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "old-sheet"


def test_install_rejects_archive_with_unsafe_paths(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)

    archive_path = os.path.join(plugin_dir, "update.zip")
    with zipfile.ZipFile(archive_path, "w") as archive:
        prefix = f"{RELEASE_ARCHIVE_ROOT}/"
        archive.writestr(prefix + "load.py", "new-load")
        archive.writestr(prefix + "version.json", json.dumps({"version": bump_patch(PLUGIN_VERSION)}))
        archive.writestr(prefix + "SpanshTools/__init__.py", "new-package")
        archive.writestr(prefix + "SpanshTools/fsd_specs.json", json.dumps({}))
        archive.writestr(prefix + "tksheet/__init__.py", "new-sheet")
        archive.writestr(prefix + "../escape.txt", "boom")

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is False

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "old-package"
    assert not os.path.exists(os.path.join(plugin_dir, "escape.txt"))


def test_stage_download_writes_archive_and_metadata(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    payload = _build_release_zip()
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(payload),
    )

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.stage() is True
    assert os.path.exists(os.path.join(plugin_dir, updater.STAGED_ARCHIVE_NAME))
    assert os.path.exists(os.path.join(plugin_dir, updater.STAGED_METADATA_NAME))


def test_install_staged_removes_staged_artifacts_on_success(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    payload = _build_release_zip()
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(payload),
    )

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.stage() is True
    assert updater.install_staged() is True
    assert not os.path.exists(os.path.join(plugin_dir, updater.STAGED_ARCHIVE_NAME))
    assert not os.path.exists(os.path.join(plugin_dir, updater.STAGED_METADATA_NAME))


def test_install_staged_clears_bad_archive_and_metadata_on_failure(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    archive_path = os.path.join(plugin_dir, SpanshUpdater.STAGED_ARCHIVE_NAME)
    metadata_path = os.path.join(plugin_dir, SpanshUpdater.STAGED_METADATA_NAME)
    with open(archive_path, "wb") as handle:
        handle.write(b"not-a-zip")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump({"version": bump_patch(PLUGIN_VERSION)}, handle)

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is False
    assert not os.path.exists(archive_path)
    assert not os.path.exists(metadata_path)


def test_install_staged_keeps_valid_archive_on_install_failure(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    archive_path = os.path.join(plugin_dir, SpanshUpdater.STAGED_ARCHIVE_NAME)
    metadata_path = os.path.join(plugin_dir, SpanshUpdater.STAGED_METADATA_NAME)
    with open(archive_path, "wb") as handle:
        handle.write(_build_release_zip())
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump({"version": bump_patch(PLUGIN_VERSION)}, handle)

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    monkeypatch.setattr(updater, "_install_from_zip", lambda _path: False)

    assert updater.install_staged() is False
    assert os.path.exists(archive_path)
    assert os.path.exists(metadata_path)


def test_install_cleanup_failure_keeps_successful_install(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)

    archive_path = os.path.join(plugin_dir, "update.zip")
    with open(archive_path, "wb") as handle:
        handle.write(_build_release_zip(top_level_files={"README.txt": "new-doc"}))

    original_rmtree = updater_mod.shutil.rmtree
    triggered = {"value": False}

    def flaky_rmtree(path, *args, **kwargs):
        if os.path.basename(path).startswith("spansh_update_") and not triggered["value"]:
            triggered["value"] = True
            raise RuntimeError("boom")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(updater_mod.shutil, "rmtree", flaky_rmtree)

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is True

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "new-package"
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), "r", encoding="utf-8") as handle:
        assert handle.read() == "new-sheet"
    with open(os.path.join(plugin_dir, "README.txt"), "r", encoding="utf-8") as handle:
        assert handle.read() == "new-doc"


def test_sync_repo_fsd_specs_updates_local_file_when_remote_differs(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(
        plugin_dir,
        fsd_specs={
            "int_hyperdrive_size5_class5": {
                "class": 5,
                "rating": "A",
                "optimal_mass": 1000.0,
                "max_fuel_per_jump": 5.0,
                "fuel_power": 2.45,
                "fuel_multiplier": 0.012,
                "supercharge_multiplier": 4,
            }
        },
    )
    remote_specs = {
        "int_hyperdrive_size5_class5": {
            "class": 5,
            "rating": "A",
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "supercharge_multiplier": 4,
        }
    }
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps(_fsd_specs_payload(remote_specs, version=2)).encode("utf-8")),
    )
    reload_mock = MagicMock(return_value=True)
    monkeypatch.setattr(updater_mod.fsd_data, "bundled_data_file_path", lambda: os.path.join(plugin_dir, "SpanshTools", "fsd_specs.json"))
    monkeypatch.setattr(updater_mod.fsd_data, "reload_specs_from_bundled_data", reload_mock)

    assert SpanshUpdater.sync_repo_fsd_specs(plugin_dir) is True
    reload_mock.assert_called_once()
    with open(os.path.join(plugin_dir, "SpanshTools", "fsd_specs.json"), "r", encoding="utf-8") as handle:
        assert json.load(handle) == _fsd_specs_payload(remote_specs, version=2)


def test_sync_repo_fsd_specs_returns_false_when_reload_fails(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    remote_specs = {
        "int_hyperdrive_size5_class5": {
            "class": 5,
            "rating": "A",
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "supercharge_multiplier": 4,
        }
    }
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps(_fsd_specs_payload(remote_specs, version=2)).encode("utf-8")),
    )
    monkeypatch.setattr(updater_mod.fsd_data, "bundled_data_file_path", lambda: os.path.join(plugin_dir, "SpanshTools", "fsd_specs.json"))
    monkeypatch.setattr(updater_mod.fsd_data, "reload_specs_from_bundled_data", lambda: False)

    assert SpanshUpdater.sync_repo_fsd_specs(plugin_dir) is False
    with open(os.path.join(plugin_dir, "SpanshTools", "fsd_specs.json"), "r", encoding="utf-8") as handle:
        assert json.load(handle) == _fsd_specs_payload(remote_specs, version=2)


def test_sync_repo_fsd_specs_skips_when_remote_matches(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    specs = {
        "int_hyperdrive_size5_class5": {
            "class": 5,
            "rating": "A",
            "optimal_mass": 1050.0,
            "max_fuel_per_jump": 5.0,
            "fuel_power": 2.45,
            "fuel_multiplier": 0.012,
            "supercharge_multiplier": 4,
        }
    }
    _write_plugin_tree(plugin_dir, fsd_specs=specs)
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps(_fsd_specs_payload(specs, version=1)).encode("utf-8")),
    )

    assert SpanshUpdater.sync_repo_fsd_specs(plugin_dir) is False


def test_sync_repo_fsd_specs_rejects_invalid_remote_payload(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    monkeypatch.setattr(
        updater_mod.requests,
        "get",
        lambda *args, **kwargs: _Response(json.dumps({"version": 2, "specs": {"bad": "payload"}}).encode("utf-8")),
    )

    assert SpanshUpdater.sync_repo_fsd_specs(plugin_dir) is False


def test_load_staged_metadata_discards_invalid_staged_archive(tmp_path):
    plugin_dir = str(tmp_path)
    archive_path = os.path.join(plugin_dir, SpanshUpdater.STAGED_ARCHIVE_NAME)
    metadata_path = os.path.join(plugin_dir, SpanshUpdater.STAGED_METADATA_NAME)

    with open(archive_path, "wb") as handle:
        handle.write(b"not-a-zip")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump({"version": bump_patch(PLUGIN_VERSION)}, handle)

    assert SpanshUpdater.load_staged_metadata(plugin_dir) is None
    assert not os.path.exists(archive_path)
    assert not os.path.exists(metadata_path)


def test_check_for_update_skips_fsd_sync_when_plugin_update_exists(monkeypatch, tmp_path):
    router = create_router(SpanshTools)
    router._tmpdir = str(tmp_path)
    router.plugin_dir = str(tmp_path)

    monkeypatch.setattr(spans_mod.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        updater_mod.SpanshUpdater,
        "check_latest",
        staticmethod(lambda: (bump_patch(PLUGIN_VERSION), "https://example.invalid/update.zip", "changes")),
    )
    sync_mock = MagicMock()
    monkeypatch.setattr(
        updater_mod.SpanshUpdater,
        "sync_repo_fsd_specs",
        staticmethod(sync_mock),
    )

    router.check_for_update()

    sync_mock.assert_not_called()


def test_check_for_update_syncs_fsd_specs_when_plugin_is_current(monkeypatch, tmp_path):
    router = create_router(SpanshTools)
    router._tmpdir = str(tmp_path)
    router.plugin_dir = str(tmp_path)

    monkeypatch.setattr(spans_mod.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        updater_mod.SpanshUpdater,
        "check_latest",
        staticmethod(lambda: (PLUGIN_VERSION, "https://example.invalid/update.zip", "changes")),
    )
    sync_mock = MagicMock()
    monkeypatch.setattr(
        updater_mod.SpanshUpdater,
        "sync_repo_fsd_specs",
        staticmethod(sync_mock),
    )

    router.check_for_update()

    sync_mock.assert_called_once_with(str(tmp_path))


def test_check_for_update_logs_worker_failure(monkeypatch, tmp_path):
    router = create_router(SpanshTools)
    router._tmpdir = str(tmp_path)
    router.plugin_dir = str(tmp_path)
    router._log_unexpected = MagicMock()

    monkeypatch.setattr(spans_mod.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(
        updater_mod.SpanshUpdater,
        "check_latest",
        staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    router.check_for_update()

    router._log_unexpected.assert_called_once_with("Failed to check for updates")


def test_stage_update_async_logs_worker_failure(monkeypatch, tmp_path):
    router = create_router(SpanshTools)
    router._tmpdir = str(tmp_path)
    router.plugin_dir = str(tmp_path)
    router._log_unexpected = MagicMock()

    class _BrokenUpdater:
        def is_staged(self):
            return False

        def stage(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(spans_mod.threading, "Thread", _ImmediateThread)
    router.spansh_updater = _BrokenUpdater()

    router._stage_update_async()

    router._log_unexpected.assert_called_once_with("Failed to stage update")
    assert router._staging_update is False
