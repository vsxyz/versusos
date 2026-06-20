"""Make each skill's scripts importable in tests without installing.

Each skill exposes an entrypoint script plus a ``core/`` namespace package.
``core`` module names are unique across skills, so the namespace-package
merge is safe — with one temporary exception: ``geckoterminal`` exists in both
collect-dex and collect-depeg-history until Task 2.5 deletes collect-dex's. The
insertion order keeps collect-depeg-history's version first on sys.path so it
shadows collect-dex's; both skills' tests resolve to that one module and both
pass (the two copies behave identically). The ``collect`` entrypoint module
names collide — the insertion
order below keeps collect-vault first on sys.path so ``import collect`` keeps
resolving to it; tests load collect-dex's and collect-context's entrypoints via
importlib under the aliases ``dex_collect`` / ``context_collect`` (see
tests/test_dex_collect.py, tests/test_context_collect.py). research-audit's
``plan.py`` / ``merge.py`` and score's ``score.py`` have unique names; the
research-audit tests still load them by path as ``audit_plan`` / ``audit_merge``
(see tests/test_audit_entrypoints.py), while ``import score`` needs no alias.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent

# Reverse priority: the LAST insert ends up FIRST on sys.path.
for skill in ("inspect", "recommend", "collect-context", "collect-dex", "score",
              "research-audit",
              "collect-depeg-history",  # shadows collect-dex/core/geckoterminal until Task 2.5
              "collect-vault"):
    sys.path.insert(0, str(ROOT / "skills" / skill / "scripts"))
