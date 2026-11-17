"""Tests for private weekly Team/Lab batch minting, public teasers, and bare-repo git push."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from private.scripts.mint_weekly_batch import PACK_SLUGS, mint_public_teasers
from private.scripts.mint_weekly_batch import main as mint_main

from canarybench.core.schemas import EngineId


def _init_bare_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    bare_repo = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare_repo)], check=True, capture_output=True)

    drops_repo = tmp_path / "drops_worktree"
    subprocess.run(
        ["git", "clone", str(bare_repo), str(drops_repo)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(drops_repo), "config", "user.email", "ci@canarybench.local"], check=True
    )
    subprocess.run(
        ["git", "-C", str(drops_repo), "config", "user.name", "CanaryBench Bot"], check=True
    )
    subprocess.run(
        ["git", "-C", str(drops_repo), "checkout", "-B", "main"], check=True, capture_output=True
    )
    (drops_repo / "README.md").write_text("# Private Drops\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(drops_repo), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(drops_repo), "commit", "-m", "init"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(drops_repo), "push", "-u", "origin", "main"],
        check=True,
        capture_output=True,
    )
    return bare_repo, drops_repo


def test_weekly_mint_team_tier_and_git_push(tmp_path: Path) -> None:
    bare_repo, drops_repo = _init_bare_and_clone(tmp_path)

    rc = mint_main(
        [
            "--tier",
            "team",
            "--pack",
            "cre-lease",
            "--count",
            "10",
            "--drop-id",
            "2026-W46",
            "--output-root",
            str(drops_repo),
            "--subscriber-id",
            "sub_team_01",
            "--subscriber-seq",
            "42",
            "--push",
            "--remote",
            "origin",
            "--branch",
            "main",
        ]
    )
    assert rc == 0

    drop_dir = drops_repo / "team" / "cre-lease" / "2026-W46"
    assert (drop_dir / "drop.jsonl").exists()
    meta = json.loads((drop_dir / "drop_meta.json").read_text(encoding="utf-8"))
    assert meta["tier"] == "team"
    assert meta["pack_id"] == "cre-lease"
    assert meta["count"] == 10
    assert meta["watermarked"] is True
    assert "canary_id" in meta

    log = subprocess.run(
        ["git", "-C", str(bare_repo), "log", "--oneline", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "team/cre-lease" in log.stdout
    assert "2026-W46" in log.stdout


def test_weekly_mint_lab_tier_covers_all_5_packs_and_4_engines(tmp_path: Path) -> None:
    bare_repo, drops_repo = _init_bare_and_clone(tmp_path)

    rc = mint_main(
        [
            "--tier",
            "lab",
            "--count",
            "50",
            "--drop-id",
            "2026-W46",
            "--output-root",
            str(drops_repo),
            "--subscriber-id",
            "sub_lab_99",
            "--subscriber-seq",
            "99",
            "--push",
            "--remote",
            "origin",
            "--branch",
            "main",
        ]
    )
    assert rc == 0

    lab_dir = drops_repo / "lab" / "2026-W46"
    root_meta = json.loads((lab_dir / "drop_meta.json").read_text(encoding="utf-8"))
    assert root_meta["tier"] == "lab"
    assert root_meta["count"] == 50
    assert root_meta["watermarked"] is True
    assert set(root_meta["packs"].keys()) == set(PACK_SLUGS)
    assert set(root_meta["engines"].keys()) == {e.value for e in EngineId}

    for slug in PACK_SLUGS:
        pack_dir = lab_dir / "packs" / slug
        assert (pack_dir / "drop.jsonl").exists()
        assert (pack_dir / "drop_meta.json").exists()

    log = subprocess.run(
        ["git", "-C", str(bare_repo), "log", "--oneline", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "lab multi-pack batch 2026-W46" in log.stdout


def test_mint_public_teasers_all_5_packs_in_tmp_repo(tmp_path: Path) -> None:
    written = mint_public_teasers(repo_root=tmp_path)
    assert set(written.keys()) == set(PACK_SLUGS)

    for slug, manifest_path in written.items():
        assert manifest_path.exists()
        lines = [ln for ln in manifest_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        expected_count = 25 if slug == "eu-vat-2027" else 10
        assert len(lines) == expected_count
        meta = json.loads((manifest_path.parent / "drop_meta.json").read_text(encoding="utf-8"))
        assert meta["watermarked"] is False
        assert meta["count"] == expected_count
