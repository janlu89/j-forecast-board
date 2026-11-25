# SPDX-License-Identifier: Apache-2.0
"""The front-end ES modules: every import exists, and every shared function a module uses is
imported (a missing import only fails in the browser, when that code runs)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "src" / "j_forecast_board" / "static" / "js"
EXPORT = re.compile(r"^export (?:async function|function|const|let) ([A-Za-z0-9_$]+)", re.M)
IMPORT = re.compile(r'^import \{ ([^}]+) \} from "([^"]+)";', re.M)
MODULES = sorted(WEB.rglob("*.js"))


def exports_of(path: Path) -> set[str]:
    return set(EXPORT.findall(path.read_text(encoding="utf-8")))


ALL_EXPORTS = {name: path for path in MODULES for name in exports_of(path)}


def code_without_strings(source: str) -> str:
    """Drop comments and the text of string literals, keep the code inside ${...}."""
    out, i, n = [], 0, len(source)
    while i < n:
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end < 0 else end
        elif source[i] in "\"'":
            quote, i = source[i], i + 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            i += 1
            out.append('""')
        elif source[i] == "`":
            i += 1
            while i < n and source[i] != "`":
                if source[i] == "\\":
                    i += 2
                elif source.startswith("${", i):
                    depth, j = 1, i + 2
                    while j < n and depth:
                        depth += {"{": 1, "}": -1}.get(source[j], 0)
                        j += 1
                    out.append(" " + code_without_strings(source[i + 2 : j - 1]) + " ")
                    i = j
                else:
                    i += 1
            i += 1
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


@pytest.mark.parametrize("module", MODULES, ids=lambda p: str(p.relative_to(WEB)))
def test_every_import_exists_in_its_module(module):
    for names, target in IMPORT.findall(module.read_text(encoding="utf-8")):
        provided = exports_of((module.parent / target).resolve())
        for name in (n.strip() for n in names.split(",")):
            assert name in provided, f"{target} does not export {name}"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: str(p.relative_to(WEB)))
def test_shared_functions_used_are_imported(module):
    source = module.read_text(encoding="utf-8")
    imported = {n.strip() for names, _ in IMPORT.findall(source) for n in names.split(",")}
    local = exports_of(module) | set(
        re.findall(r"(?:const|let|function)\s+([A-Za-z0-9_$]+)", source)
    )
    for params in re.findall(r"\(([^()]*)\)\s*=>|function\s*[A-Za-z0-9_$]*\s*\(([^()]*)\)", source):
        local |= set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", " ".join(params)))
    code = code_without_strings(
        "\n".join(line for line in source.split("\n") if not line.startswith("import "))
    )
    for name, owner in ALL_EXPORTS.items():
        if owner == module or name in imported or name in local:
            continue
        used = re.search(
            r"(?<![A-Za-z0-9_$])(?<![^.]\.)" + re.escape(name) + r"(?![A-Za-z0-9_$])(?!\s*:(?!:))",
            code,
        )
        assert not used, f"{module.name} uses {name} from {owner.name} without importing it"
