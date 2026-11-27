#!/usr/bin/env python3
"""Unit tests for published-release seed resolution in restore_product_seed.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_version import Version  # noqa: E402
import restore_product_seed as rps  # noqa: E402


SAMPLE_API_OUTPUT = "\n".join(
    json.dumps(row)
    for row in [
        {"tag_name": "v0.14.4-draft", "draft": True, "prerelease": False},
        {"tag_name": "v0.14.3-rc.1", "draft": False, "prerelease": True},
        {"tag_name": "v0.14.3", "draft": False, "prerelease": False},
        {"tag_name": "v0.14.2", "draft": False, "prerelease": False},
        {"tag_name": "v0.14.1", "draft": False, "prerelease": False},
        {"tag_name": "v0.14.0", "draft": False, "prerelease": False},
    ]
)


def main() -> int:
    sample = [
        (Version.parse("0.14.1"), "v0.14.1"),
        (Version.parse("0.14.3"), "v0.14.3"),
        (Version.parse("0.14.2"), "v0.14.2"),
        (Version.parse("0.14.0"), "v0.14.0"),
    ]

    assert rps.resolve_seed_tag("0.14.1", "0.14.3", releases=sample) == "v0.14.1"
    assert rps.resolve_seed_tag("", "0.14.3", releases=sample) == "v0.14.2"
    assert rps.resolve_seed_tag("", "0.14.4", releases=sample) == "v0.14.3"
    assert rps.resolve_seed_tag("", "", releases=sample) == "v0.14.3"

    try:
        rps.resolve_seed_tag("", "0.14.0", releases=sample)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when no prior release exists")

    with mock.patch.object(subprocess, "check_output", return_value=SAMPLE_API_OUTPUT):
        published = rps.list_published_releases()
        assert [tag for _, tag in published] == ["v0.14.3", "v0.14.2", "v0.14.1", "v0.14.0"], published
        assert rps.resolve_seed_tag("", "0.14.3") == "v0.14.2"
        assert rps.resolve_seed_tag("", "0.14.4") == "v0.14.3"
        assert rps.resolve_seed_tag("", "") == "v0.14.3"

    print("restore_product_seed unit tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
