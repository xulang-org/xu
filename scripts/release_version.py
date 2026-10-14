"""Parse release identities and compare SemVer prerelease precedence."""
from __future__ import annotations

import re

VERSION_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
PATTERN = re.compile(VERSION_PATTERN)


class Version(tuple):
    """Three numeric components with a preserved prerelease identity.

    Stable identities remain compatible with historical three-element tuples.
    All ordering operations include prerelease precedence, including numeric
    identifiers; callers must never compare only the numeric components.
    Release tags intentionally omit build metadata; Git hashes live in provenance.
    """

    def __new__(cls, core, prerelease=()):
        value = super().__new__(cls, core)
        value.prerelease = tuple(prerelease)
        return value

    @classmethod
    def parse(cls, text: str):
        match = PATTERN.fullmatch(text)
        if not match:
            raise ValueError("version must be major.minor.patch with an optional prerelease")
        pre = tuple(match[4].split(".")) if match[4] else ()
        if any(part.isdigit() and len(part) > 1 and part[0] == "0" for part in pre):
            raise ValueError("numeric prerelease identifiers must not have leading zeroes")
        return cls(tuple(int(match[i]) for i in (1, 2, 3)), pre)

    def __str__(self):
        core = ".".join(map(str, tuple(self)))
        return core + ("-" + ".".join(self.prerelease) if self.prerelease else "")

    @staticmethod
    def _key(value):
        if not isinstance(value, tuple) or len(value) != 3:
            return NotImplemented
        pre = getattr(value, "prerelease", ())
        identifiers = tuple((0, int(part)) if part.isdigit() else (1, part) for part in pre)
        return tuple(value), not pre, identifiers

    def __eq__(self, other):
        key = self._key(other)
        return NotImplemented if key is NotImplemented else self._key(self) == key

    def __ne__(self, other):
        result = self.__eq__(other)
        return NotImplemented if result is NotImplemented else not result

    def __lt__(self, other):
        key = self._key(other)
        return NotImplemented if key is NotImplemented else self._key(self) < key

    def __le__(self, other):
        key = self._key(other)
        return NotImplemented if key is NotImplemented else self._key(self) <= key

    def __gt__(self, other):
        key = self._key(other)
        return NotImplemented if key is NotImplemented else self._key(self) > key

    def __ge__(self, other):
        key = self._key(other)
        return NotImplemented if key is NotImplemented else self._key(self) >= key

    def __hash__(self):
        return hash(tuple(self)) if not self.prerelease else hash((tuple(self), self.prerelease))

    def next_prerelease(self):
        pre = self.prerelease
        if len(pre) != 2 or pre[0] not in ("dev", "rc") or not pre[1].isdigit() or int(pre[1]) < 1:
            raise ValueError("expected dev.N or rc.N; start a new development cycle first")
        return Version(tuple(self), (pre[0], str(int(pre[1]) + 1)))

    def promote(self, channel):
        if not self.prerelease:
            raise ValueError("the current version is already a final version")
        if channel == "stable":
            return Version(tuple(self))
        if self.prerelease[0] != "dev":
            raise ValueError("only dev versions can advance to rc; use --next-prerelease for another rc")
        return Version(tuple(self), ("rc", "1"))
