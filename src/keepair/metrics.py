"""Minimal in-process counters with Prometheus text exposition.

Kept dependency-free so every app instance (and every test) owns its registry.
"""

from __future__ import annotations

import threading
from collections import defaultdict

Labels = tuple[tuple[str, str], ...]


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[Labels, int]] = defaultdict(lambda: defaultdict(int))
        self._help: dict[str, str] = {}

    def describe(self, name: str, help_text: str) -> None:
        self._help[name] = help_text

    def inc(self, name: str, **labels: str) -> None:
        key: Labels = tuple(sorted(labels.items()))
        with self._lock:
            self._counters[name][key] += 1

    def value(self, name: str, **labels: str) -> int:
        key: Labels = tuple(sorted(labels.items()))
        with self._lock:
            return self._counters.get(name, {}).get(key, 0)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name in sorted(self._counters):
                if name in self._help:
                    lines.append(f"# HELP {name} {self._help[name]}")
                lines.append(f"# TYPE {name} counter")
                for key, count in sorted(self._counters[name].items()):
                    label_text = ",".join(f'{k}="{_escape(v)}"' for k, v in key)
                    suffix = f"{{{label_text}}}" if label_text else ""
                    lines.append(f"{name}{suffix} {count}")
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
