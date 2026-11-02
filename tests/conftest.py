"""Shared fixtures. Public Velox EMDs are downloaded to a cache, never vendored."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

CACHE_DIRS = [
    Path(os.environ["OPENVELOX_PUBLIC_EMD"]) if os.environ.get("OPENVELOX_PUBLIC_EMD") else None,
    Path("/tmp/velox_public"),
    Path.home() / ".cache" / "openvelox" / "emd",
]

# RosettaSciIO ships these under GPL — tests fetch them at runtime.
PUBLIC_URLS = {
    "fei_example_tem_stack.emd": (
        "https://github.com/hyperspy/rosettasciio/raw/main/rsciio/tests/data/emd/"
        "fei_example_tem_stack.emd"
    ),
    "fei_example_dpc_titles.emd": (
        "https://github.com/hyperspy/rosettasciio/raw/main/rsciio/tests/data/emd/"
        "fei_example_dpc_titles.emd"
    ),
    "velox_emd_version11.zip": (
        "https://github.com/hyperspy/rosettasciio/raw/main/rsciio/tests/data/emd/"
        "velox_emd_version11.zip"
    ),
    "velox_EELS_EDS.zip": (
        "https://github.com/hyperspy/rosettasciio/raw/main/rsciio/tests/data/emd/"
        "velox_EELS_EDS.zip"
    ),
}


def _existing_cache() -> Path | None:
    for folder in CACHE_DIRS:
        if folder is not None and folder.is_dir():
            return folder
    return None


def _download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "OpenVelox-tests"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
        return dest.is_file() and dest.stat().st_size > 0
    except Exception:
        return False


def public_emd_path(*candidates: str) -> Path | None:
    """Return the first existing candidate under a cache, downloading archives if needed."""
    cache = _existing_cache() or Path("/tmp/velox_public")
    for rel in candidates:
        for folder in [p for p in CACHE_DIRS if p is not None]:
            hit = folder / rel
            if hit.is_file():
                return hit
            for found in folder.rglob(Path(rel).name):
                if found.is_file():
                    return found
    name = Path(candidates[0]).name
    if name in PUBLIC_URLS:
        dest = cache / name
        if not dest.is_file():
            if not _download(PUBLIC_URLS[name], dest):
                return None
        if dest.suffix == ".zip":
            try:
                with zipfile.ZipFile(dest) as zf:
                    zf.extractall(cache / dest.stem)
            except (zipfile.BadZipFile, OSError):
                return None
            for rel in candidates:
                hit = cache / dest.stem / rel
                if hit.is_file():
                    return hit
                for found in (cache / dest.stem).rglob(Path(rel).name):
                    if found.is_file():
                        return found
        return dest if dest.suffix == ".emd" and dest.is_file() else None
    return None


@pytest.fixture(scope="session")
def public_si_emd() -> Path:
    path = public_emd_path("v11/Test SI 16x16 215 kx.emd", "Test SI 16x16 215 kx.emd")
    if path is None:
        pytest.skip("Public Velox SI example not available (offline or download failed)")
    return path


@pytest.fixture(scope="session")
def public_stack_emd() -> Path:
    path = public_emd_path("fei_example_tem_stack.emd")
    if path is None:
        pytest.skip("Public Velox stack example not available")
    return path


@pytest.fixture(scope="session")
def public_dpc_emd() -> Path:
    path = public_emd_path("fei_example_dpc_titles.emd")
    if path is None:
        pytest.skip("Public Velox DPC example not available")
    return path


@pytest.fixture(scope="session")
def public_eels_emd() -> Path:
    path = public_emd_path("eels/example_velox_EELS_EDS.emd", "example_velox_EELS_EDS.emd")
    if path is None:
        pytest.skip("Public Velox EELS+EDS example not available")
    return path
