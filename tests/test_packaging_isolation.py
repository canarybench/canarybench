"""Tests verifying strict public vs. private isolation in git and PyPI builds."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_PUBLIC_PACK_DATA: tuple[tuple[str, str], ...] = (
    ("eu_vat_2027", "public_25.jsonl"),
    ("cre_lease", "public_10.jsonl"),
    ("customs_cbam", "public_10.jsonl"),
    ("med_coding", "public_10.jsonl"),
    ("claims_adjudication", "public_10.jsonl"),
)


def test_private_is_gitignored() -> None:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "private/"],
        check=False,
    )
    assert proc.returncode == 0, "private/ MUST be ignored by .gitignore"

    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "private/"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout.strip() == "", "private/ must never be tracked in git"


def test_wheel_and_sdist_exclude_private_and_include_all_5_packs(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )

    wheels = list(tmp_path.glob("*.whl"))
    sdists = list(tmp_path.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        assert not any("private" in name.lower() for name in names), "private leaked into wheel!"
        for pkg_dir, manifest_name in _PUBLIC_PACK_DATA:
            assert any(
                name.endswith(f"canarybench/packs/{pkg_dir}/data/{manifest_name}")
                for name in names
            ), f"Missing {manifest_name} for {pkg_dir} in wheel"
            assert any(
                name.endswith(f"canarybench/packs/{pkg_dir}/data/drop_meta.json")
                for name in names
            ), f"Missing drop_meta.json for {pkg_dir} in wheel"
            assert any(
                f"canarybench/packs/{pkg_dir}/data/artifacts/" in name for name in names
            ), f"Missing artifacts/ for {pkg_dir} in wheel"

    with tarfile.open(sdists[0], "r:gz") as tf:
        members = tf.getnames()
        assert not any("/private" in m or m.startswith("private") for m in members), (
            "private leaked into sdist!"
        )
        for pkg_dir, manifest_name in _PUBLIC_PACK_DATA:
            assert any(
                m.endswith(f"src/canarybench/packs/{pkg_dir}/data/{manifest_name}")
                for m in members
            ), f"Missing {manifest_name} for {pkg_dir} in sdist"
