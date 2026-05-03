"""Tests for update check and installer behavior.

Trimmed to ~12 tests covering: version parsing, version comparison,
path-traversal security, two-step staging flow, data preservation,
archive validation, check_latest discovery, and FSD spec sync.
"""

import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import SpanshTools.web_utils as web_utils_mod
from SpanshTools import updater as updater_mod
from SpanshTools.constants import STAGED_ARCHIVE_NAME, STAGED_METADATA_NAME
from SpanshTools.updater import RELEASE_ARCHIVE_ROOT, SpanshUpdater
from conftest import PLUGIN_VERSION, STANDARD_5A_FSD_SPEC, bump_patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fsd_specs_payload(specs=None, *, version=1):
    return {
        "version": version,
        "specs": specs or {"int_hyperdrive_size5_class5": STANDARD_5A_FSD_SPEC},
    }


def _write_plugin_tree(plugin_dir, *, load_text="old-load", version=PLUGIN_VERSION,
                        package_init_text="old-package", sheet_init_text="old-sheet",
                        fsd_specs=None):
    os.makedirs(os.path.join(plugin_dir, "SpanshTools", "data"), exist_ok=True)
    os.makedirs(os.path.join(plugin_dir, "tksheet"), exist_ok=True)
    with open(os.path.join(plugin_dir, "load.py"), "w", encoding="utf-8") as f:
        f.write(load_text)
    with open(os.path.join(plugin_dir, "version.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version}, f)
    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), "w", encoding="utf-8") as f:
        f.write(package_init_text)
    with open(os.path.join(plugin_dir, "SpanshTools", "data", "fsd_specs.json"), "w", encoding="utf-8") as f:
        json.dump(_fsd_specs_payload(fsd_specs), f)
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), "w", encoding="utf-8") as f:
        f.write(sheet_init_text)


def _build_release_zip(*, load_text="new-load", version=None,
                        package_init_text="new-package", sheet_init_text="new-sheet",
                        include_tksheet=True):
    version = version or bump_patch(PLUGIN_VERSION)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        prefix = f"{RELEASE_ARCHIVE_ROOT}/"
        archive.writestr(prefix + "load.py", load_text)
        archive.writestr(prefix + "version.json", json.dumps({"version": version}))
        archive.writestr(prefix + "SpanshTools/__init__.py", package_init_text)
        archive.writestr(prefix + "SpanshTools/data/fsd_specs.json",
                         json.dumps(_fsd_specs_payload()))
        archive.writestr(prefix + "SpanshTools/data/ship_type_names.json",
                         json.dumps({"anaconda": "Anaconda"}))
        if include_tksheet:
            archive.writestr(prefix + "tksheet/__init__.py", sheet_init_text)
    return buf.getvalue()


class _Response:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# 1. _parse_version edge cases (NEW)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (None, None),
    ("", None),
    ("   ", None),
    ("abc", None),
    ("1.2.3", ((1, 2, 3), ())),
    ("v1.0.0", ((1, 0, 0), ())),
    ("1.0.0+build.42", ((1, 0, 0), ())),
    ("1.0.0-beta1", ((1, 0, 0), ((1, "beta1"),))),
], ids=["none", "empty", "whitespace", "non-semver",
        "basic", "v-prefix", "build-metadata-stripped", "prerelease-kept"])
def test_parse_version_edge_cases(raw, expected):
    assert SpanshUpdater._parse_version(raw) == expected


# ---------------------------------------------------------------------------
# 2. Version comparison – single parametrized test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("latest, current, expected", [
    (bump_patch(PLUGIN_VERSION), PLUGIN_VERSION, True),
    (PLUGIN_VERSION, bump_patch(PLUGIN_VERSION), False),
    (PLUGIN_VERSION, PLUGIN_VERSION, False),
    (PLUGIN_VERSION, f"{PLUGIN_VERSION}-beta1", True),
    (f"{PLUGIN_VERSION}-beta1", PLUGIN_VERSION, False),
], ids=["newer-wins", "older-loses", "equal-is-not-newer",
        "release-beats-prerelease", "prerelease-loses-to-release"])
def test_version_comparison(latest, current, expected):
    assert SpanshUpdater.is_newer_version(latest, current) is expected


# ---------------------------------------------------------------------------
# 3-4. _safe_extract_path – security boundary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel_path", [
    "../escape.txt",
    "foo/../../escape.txt",
    "SpanshTools/../../../escape.txt",
], ids=["parent-traversal", "nested-traversal", "deep-hidden-traversal"])
def test_safe_extract_path_blocks_traversal(tmp_path, rel_path):
    with pytest.raises(RuntimeError):
        SpanshUpdater._safe_extract_path(str(tmp_path), rel_path)


def test_safe_extract_path_resolves_valid_and_skips_dots(tmp_path):
    staging = str(tmp_path)
    result = SpanshUpdater._safe_extract_path(staging, "SpanshTools/__init__.py")
    assert result == os.path.join(staging, "SpanshTools", "__init__.py")
    # Directory-only entries (dot / empty) return None instead of extracting
    assert SpanshUpdater._safe_extract_path(staging, ".") is None


# ---------------------------------------------------------------------------
# 5. Two-step staging flow: stage() downloads, install_staged() applies
# ---------------------------------------------------------------------------

def test_stage_then_install_staged_applies_update(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    payload = _build_release_zip()
    monkeypatch.setattr(web_utils_mod.requests, "get",
                        lambda *a, **kw: _Response(payload))

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION),
                            "https://example.invalid/update.zip", "", plugin_dir)

    # Stage: downloads archive + writes metadata
    assert updater.stage() is True
    assert os.path.exists(os.path.join(plugin_dir, STAGED_ARCHIVE_NAME))
    assert os.path.exists(os.path.join(plugin_dir, STAGED_METADATA_NAME))

    # Install: applies staged archive, then cleans up staging artifacts
    assert updater.install_staged() is True
    assert not os.path.exists(os.path.join(plugin_dir, STAGED_ARCHIVE_NAME))
    assert not os.path.exists(os.path.join(plugin_dir, STAGED_METADATA_NAME))

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "new-package"
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "new-sheet"


# ---------------------------------------------------------------------------
# 6. Data preservation – non-target files survive install
# ---------------------------------------------------------------------------

def test_install_preserves_user_data_files(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    route_state = os.path.join(plugin_dir, "route_state.json")
    with open(route_state, "w", encoding="utf-8") as f:
        f.write('{"route": [["Sol", 0]]}')

    payload = _build_release_zip()
    monkeypatch.setattr(web_utils_mod.requests, "get",
                        lambda *a, **kw: _Response(payload))

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION),
                            "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.stage() is True
    assert updater.install_staged() is True

    # User data file untouched
    with open(route_state, encoding="utf-8") as f:
        assert f.read() == '{"route": [["Sol", 0]]}'
    # Plugin code updated
    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "new-package"


# ---------------------------------------------------------------------------
# 7. Incomplete archive → install rejected, old code preserved
# ---------------------------------------------------------------------------

def test_install_rejects_incomplete_archive(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)

    with open(os.path.join(plugin_dir, STAGED_ARCHIVE_NAME), "wb") as f:
        f.write(_build_release_zip(include_tksheet=False))

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION),
                            "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is False

    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "old-package"
    with open(os.path.join(plugin_dir, "tksheet", "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "old-sheet"


# ---------------------------------------------------------------------------
# 8. Path traversal in archive → install blocked, no files escape
# ---------------------------------------------------------------------------

def test_install_rejects_unsafe_archive_paths(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)

    with zipfile.ZipFile(os.path.join(plugin_dir, STAGED_ARCHIVE_NAME), "w") as archive:
        prefix = f"{RELEASE_ARCHIVE_ROOT}/"
        archive.writestr(prefix + "load.py", "new-load")
        archive.writestr(prefix + "version.json",
                         json.dumps({"version": bump_patch(PLUGIN_VERSION)}))
        archive.writestr(prefix + "SpanshTools/__init__.py", "new-package")
        archive.writestr(prefix + "SpanshTools/data/fsd_specs.json", json.dumps({}))
        archive.writestr(prefix + "tksheet/__init__.py", "new-sheet")
        archive.writestr(prefix + "../escape.txt", "boom")

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION),
                            "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is False

    # Old code preserved (rollback)
    with open(os.path.join(plugin_dir, "SpanshTools", "__init__.py"), encoding="utf-8") as f:
        assert f.read() == "old-package"
    # Traversal target never created
    assert not os.path.exists(os.path.join(plugin_dir, "escape.txt"))


# ---------------------------------------------------------------------------
# 9. Corrupt staged archive → artifacts cleaned up
# ---------------------------------------------------------------------------

def test_install_staged_discards_corrupt_archive(tmp_path):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir)
    archive_path = os.path.join(plugin_dir, STAGED_ARCHIVE_NAME)
    metadata_path = os.path.join(plugin_dir, STAGED_METADATA_NAME)

    with open(archive_path, "wb") as f:
        f.write(b"not-a-zip")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump({"version": bump_patch(PLUGIN_VERSION)}, f)

    updater = SpanshUpdater(bump_patch(PLUGIN_VERSION),
                            "https://example.invalid/update.zip", "", plugin_dir)
    assert updater.install_staged() is False
    assert not os.path.exists(archive_path)
    assert not os.path.exists(metadata_path)


# ---------------------------------------------------------------------------
# 10. check_latest – happy path returns (version, url, changelog)
# ---------------------------------------------------------------------------

def test_check_latest_returns_matching_release(monkeypatch):
    latest = bump_patch(PLUGIN_VERSION)
    payload = {
        "tag_name": f"v{latest}",
        "body": "changes",
        "assets": [{
            "name": SpanshUpdater.release_asset_name(latest),
            "browser_download_url": "https://example.invalid/EDMC-SpanshTools.zip",
        }],
    }
    monkeypatch.setattr(web_utils_mod.requests, "get",
                        lambda *a, **kw: _Response(json.dumps(payload).encode()))

    assert SpanshUpdater.check_latest() == (
        latest, "https://example.invalid/EDMC-SpanshTools.zip", "changes",
    )


# ---------------------------------------------------------------------------
# 11. check_latest – rejects bad releases (parametrized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tag, asset_name", [
    (f"v{bump_patch(PLUGIN_VERSION)}", "wrong-name.zip"),
    ("latest", SpanshUpdater.release_asset_name("latest")),
], ids=["non-matching-asset", "non-semver-tag"])
def test_check_latest_rejects_invalid_releases(monkeypatch, tag, asset_name):
    payload = {
        "tag_name": tag,
        "body": "changes",
        "assets": [{
            "name": asset_name,
            "browser_download_url": "https://example.invalid/file.zip",
        }],
    }
    monkeypatch.setattr(web_utils_mod.requests, "get",
                        lambda *a, **kw: _Response(json.dumps(payload).encode()))

    assert SpanshUpdater.check_latest() is None


# ---------------------------------------------------------------------------
# 12. FSD spec sync – remote newer → writes + reloads
# ---------------------------------------------------------------------------

def test_sync_fsd_specs_updates_when_remote_newer(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    _write_plugin_tree(plugin_dir, fsd_specs={
        "int_hyperdrive_size5_class5": {
            "class": 5, "rating": "A", "optimal_mass": 1000.0,
            "max_fuel_per_jump": 5.0, "fuel_power": 2.45,
            "fuel_multiplier": 0.012, "supercharge_multiplier": 4,
        },
    })
    remote_specs = {"int_hyperdrive_size5_class5": STANDARD_5A_FSD_SPEC}
    monkeypatch.setattr(
        web_utils_mod.requests, "get",
        lambda *a, **kw: _Response(
            json.dumps(_fsd_specs_payload(remote_specs, version=2)).encode()),
    )
    monkeypatch.setattr(
        updater_mod.ship_moduling, "bundled_data_file_path",
        lambda: os.path.join(plugin_dir, "SpanshTools", "data", "fsd_specs.json"),
    )
    monkeypatch.setattr(updater_mod.ship_moduling,
                        "reload_specs_from_bundled_data", lambda: True)

    assert SpanshUpdater.sync_repo_fsd_specs(plugin_dir) is True
    with open(os.path.join(plugin_dir, "SpanshTools", "data", "fsd_specs.json"),
              encoding="utf-8") as f:
        assert json.load(f) == _fsd_specs_payload(remote_specs, version=2)


# ---------------------------------------------------------------------------
# 13. FSD spec sync – versions match → no-op
# ---------------------------------------------------------------------------

def test_sync_fsd_specs_skips_when_versions_match(tmp_path, monkeypatch):
    plugin_dir = str(tmp_path)
    specs = {"int_hyperdrive_size5_class5": STANDARD_5A_FSD_SPEC}
    _write_plugin_tree(plugin_dir, fsd_specs=specs)
    monkeypatch.setattr(
        web_utils_mod.requests, "get",
        lambda *a, **kw: _Response(
            json.dumps(_fsd_specs_payload(specs, version=1)).encode()),
    )

    assert SpanshUpdater.sync_repo_fsd_specs(plugin_dir) is False
