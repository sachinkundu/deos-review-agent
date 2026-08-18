"""Build deterministic full and filtered diff artifacts for review agents.

The GitHub-returned provider diff is always retained byte-for-byte as text.
Filtering only removes complete file sections from the lower-noise review view;
it never rewrites provider patches or participates in comment-line validation.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Literal

from .diff_validator import parse_unified_diff

PROVIDER_DIFF_NAME = "provider-diff.diff"
REVIEW_DIFF_NAME = "review-diff.diff"
FILTER_MANIFEST_NAME = "diff-filter.json"

LOCKFILE_BASENAMES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
    "mix.lock",
    "flake.lock",
)
VENDORED_SEGMENTS = (
    "vendor",
    "vendors",
    "third_party",
    "third-party",
    "node_modules",
    ".terraform",
)
GENERATED_SEGMENTS = ("generated", "__generated__", "dist", "build", "coverage")
GENERATED_FILENAME_PATTERNS = (
    "*.generated.*",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*_pb2.py",
    "*.pb.go",
)


class DiffFilterError(RuntimeError):
    """The provider diff could not be classified without ambiguity."""


@dataclass(frozen=True)
class DiffSection:
    """One complete provider diff file section and its right-side path."""

    path: str
    text: str


@dataclass(frozen=True)
class DiffExclusion:
    path: str
    category: Literal["lockfile", "vendored", "generated"]
    rule: str


@dataclass(frozen=True)
class DiffArtifacts:
    provider_diff: Path
    review_diff: Path
    filter_manifest: Path
    exclusions: tuple[DiffExclusion, ...]


def split_diff_sections(diff_text: str) -> tuple[DiffSection, ...]:
    """Split a provider diff on file boundaries without rewriting section text."""
    starts = [match.start() for match in re.finditer(r"(?m)^diff --git ", diff_text)]
    if not starts:
        if diff_text:
            raise DiffFilterError("provider diff has content but no 'diff --git' file boundary")
        return ()
    if diff_text[: starts[0]]:
        raise DiffFilterError("provider diff contains unattributable content before first file")

    sections: list[DiffSection] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(diff_text)
        text = diff_text[start:end]
        parsed = parse_unified_diff(text)
        if len(parsed) != 1:
            raise DiffFilterError(
                f"provider diff section {index + 1} resolved to {len(parsed)} right-side paths"
            )
        sections.append(DiffSection(path=next(iter(parsed)), text=text))
    return tuple(sections)


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/")


def classify_metadata(path: str) -> DiffExclusion | None:
    """Apply lockfile, vendored, and generated metadata rules in precedence order."""
    normalized = _normalized_path(path)
    segments = tuple(segment for segment in normalized.split("/") if segment)
    basename = PurePosixPath(normalized).name

    if basename in LOCKFILE_BASENAMES:
        return DiffExclusion(path, "lockfile", f"lockfile-basename:{basename}")
    for segment in VENDORED_SEGMENTS:
        if segment in segments:
            return DiffExclusion(path, "vendored", f"vendored-path-segment:{segment}")
    for segment in GENERATED_SEGMENTS:
        if segment in segments:
            return DiffExclusion(path, "generated", f"generated-path-segment:{segment}")
    for pattern in GENERATED_FILENAME_PATTERNS:
        if fnmatchcase(basename, pattern):
            return DiffExclusion(path, "generated", f"generated-filename:{pattern}")
    return None


def classify_marker(path: str, lines: tuple[bytes, ...] | None) -> DiffExclusion | None:
    """Classify generated markers among at most 20 non-blank right-side lines."""
    if lines is None:
        return None
    for line in lines[:20]:
        lowered = line.lower()
        if b"@generated" in lowered:
            return DiffExclusion(path, "generated", "generated-marker:@generated")
        if b"generated" in lowered and b"do not edit" in lowered:
            return DiffExclusion(path, "generated", "generated-marker:generated+do-not-edit")
    return None


class GitBlobReader:
    """Read a bounded prefix from regular blobs at the checked-out HEAD commit."""

    def __init__(self, repository: Path):
        self.repository = repository

    def first_nonblank_lines(self, path: str, limit: int = 20) -> tuple[bytes, ...] | None:
        tree = subprocess.run(
            ["git", "--literal-pathspecs", "ls-tree", "-z", "HEAD", "--", path],
            cwd=self.repository,
            capture_output=True,
            check=False,
        )
        if tree.returncode != 0:
            raise DiffFilterError(
                f"could not inspect right-side blob metadata for {path!r}: "
                f"{tree.stderr.decode(errors='replace').strip()}"
            )
        if not tree.stdout:
            return None

        record = tree.stdout.rstrip(b"\0")
        metadata, separator, returned_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise DiffFilterError(f"unexpected git tree record for {path!r}")
        mode, object_type, object_id = fields
        if returned_path.decode(errors="surrogateescape") != path:
            raise DiffFilterError(f"git tree lookup for {path!r} returned another path")
        if object_type != b"blob" or mode not in (b"100644", b"100755"):
            return None

        blob = subprocess.run(
            ["git", "cat-file", "blob", object_id.decode("ascii")],
            cwd=self.repository,
            capture_output=True,
            check=False,
        )
        if blob.returncode != 0:
            raise DiffFilterError(
                f"could not read right-side blob for {path!r}: "
                f"{blob.stderr.decode(errors='replace').strip()}"
            )

        nonblank: list[bytes] = []
        for line in blob.stdout.splitlines():
            if not line.strip():
                continue
            nonblank.append(line)
            if len(nonblank) == limit:
                break
        return tuple(nonblank)


def write_diff_artifacts(
    workdir: Path,
    provider_diff: str,
    *,
    blob_reader: GitBlobReader | None = None,
) -> DiffArtifacts:
    """Write the full diff, filtered diff, and deterministic exclusion manifest."""
    reader = blob_reader or GitBlobReader(workdir)
    sections = split_diff_sections(provider_diff)
    retained: list[str] = []
    exclusions: list[DiffExclusion] = []

    for section in sections:
        exclusion = classify_metadata(section.path)
        if exclusion is None:
            exclusion = classify_marker(
                section.path, reader.first_nonblank_lines(section.path, limit=20)
            )
        if exclusion is None:
            retained.append(section.text)
        else:
            exclusions.append(exclusion)

    provider_path = workdir / PROVIDER_DIFF_NAME
    review_path = workdir / REVIEW_DIFF_NAME
    manifest_path = workdir / FILTER_MANIFEST_NAME
    provider_path.write_text(provider_diff, encoding="utf-8")
    review_path.write_text("".join(retained), encoding="utf-8")
    manifest = {"version": 1, "exclusions": [asdict(item) for item in exclusions]}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return DiffArtifacts(
        provider_diff=provider_path,
        review_diff=review_path,
        filter_manifest=manifest_path,
        exclusions=tuple(exclusions),
    )
