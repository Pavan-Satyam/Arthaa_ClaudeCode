"""Alpha registry: AST-scan zoo modules, validate metadata, lazy-import on compute.

Ported from Vibe-Trading's registry layer. Each factor lives in a one-file-per-alpha
layout under ``arthaai/factors/zoo/<zoo_id>/<alpha_id_short>.py`` with a
``__alpha_meta__`` dict literal and a ``compute(panel)`` function.

The registry discovers factors via filesystem scan + AST parsing (no imports
at scan time). Compute is lazy-imported on first call.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_MAX_PY_BYTES = 200_000

_PRICE_COLS = {"open", "high", "low", "close", "volume", "vwap", "amount"}


@dataclass(frozen=True)
class Alpha:
    """Lightweight handle for a registered alpha (registry-owned)."""

    id: str
    zoo: str
    module_path: str
    meta: dict[str, Any] = field(default_factory=dict)


def _validate_columns_required(cols: list[str]) -> None:
    for column in cols:
        if column in _PRICE_COLS:
            continue
        if column.startswith("fund:"):
            continue
        raise ValueError(f"unknown panel column: {column}")


class SkipAlpha(Exception):
    """Raised when an alpha's preconditions (sector, columns) are not met."""


class RegistryError(Exception):
    """Raised on registry-level configuration errors."""


@dataclass(frozen=True)
class _LoadError:
    alpha_id: str
    reason: str


def _validate_id_token(token: str, kind: str) -> None:
    if not _ID_RE.fullmatch(token):
        raise RegistryError(f"invalid {kind} {token!r}: must match {_ID_RE.pattern}")


def load_alpha_meta_from_py(path: Path) -> dict[str, Any]:
    """AST-extract the ``__alpha_meta__`` dict literal from a zoo module.

    No import is performed — purely static parsing. Strips extraction markers
    (section headers with non-ASCII chars) that may leak into factor files.
    """
    size = path.stat().st_size
    if size > _MAX_PY_BYTES:
        raise RegistryError(f"{path.name}: {size}B exceeds {_MAX_PY_BYTES}B cap")

    source = path.read_text(encoding="utf-8")

    # Strip lines with non-ASCII artifacts outside strings/comments that
    # leaked from the extraction markdown (section headers, part markers).
    cleaned: list[str] = []
    in_triple = False
    for line in source.splitlines():
        stripped = line.strip()
        if not in_triple:
            if '"""' in stripped and stripped.count('"""') < 2:
                in_triple = True
            elif "'''" in stripped and stripped.count("'''") < 2:
                in_triple = True
        else:
            if '"""' in stripped or "'''" in stripped:
                in_triple = False
            cleaned.append(line)
            continue
        # Outside strings: skip lines with non-ASCII that aren't code/comments
        if stripped and not stripped.startswith(("#", '"', "'")):
            if any(ord(c) > 127 for c in stripped):
                if not stripped.startswith(("from ", "import ", "def ", "class ", "return ", "    ", "__")):
                    continue
        cleaned.append(line)

    source = "\n".join(cleaned)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RegistryError(f"{path.name}: SyntaxError at line {exc.lineno}: {exc.msg}") from exc

    meta_node: ast.expr | None = None
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
        if any(t.id == "__alpha_meta__" for t in targets):
            meta_node = stmt.value
            break

    if meta_node is None:
        raise RegistryError(f"{path.name}: __alpha_meta__ assignment not found")

    try:
        raw = ast.literal_eval(meta_node)
    except (ValueError, SyntaxError) as exc:
        raise RegistryError(f"{path.name}: __alpha_meta__ not a literal: {exc}") from exc

    if not isinstance(raw, dict):
        raise RegistryError(f"{path.name}: __alpha_meta__ must be dict, got {type(raw).__name__}")

    # Validate required columns
    cols = raw.get("columns_required", [])
    _validate_columns_required(cols)

    return raw


def _zoo_dir_default() -> Path:
    return Path(__file__).parent / "zoo"


class Registry:
    """In-memory registry of all discoverable alphas across zoo subdirectories."""

    def __init__(self, zoo_root: Path | None = None) -> None:
        default_root = _zoo_dir_default()
        self._zoo_root = (zoo_root or default_root).resolve()
        self._use_filesystem_loader = self._zoo_root != default_root.resolve()
        self._py_paths: dict[str, Path] = {}
        self._alphas: dict[str, Alpha] = {}
        self._load_errors: list[_LoadError] = []
        self._scan()

    def _scan(self) -> None:
        if not self._zoo_root.is_dir():
            return
        for zoo_dir in sorted(self._zoo_root.iterdir()):
            if not zoo_dir.is_dir():
                continue
            zoo_id = zoo_dir.name
            if zoo_id.startswith("_") or zoo_id == "__pycache__":
                continue
            try:
                _validate_id_token(zoo_id, "zoo_id")
            except RegistryError as exc:
                self._load_errors.append(_LoadError(zoo_id, str(exc)))
                continue
            for py_file in sorted(zoo_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                self._try_register(zoo_id, py_file)

    def _try_register(self, zoo_id: str, py_file: Path) -> None:
        short_id = py_file.stem
        try:
            _validate_id_token(short_id, "alpha_id_short")
        except RegistryError as exc:
            self._load_errors.append(_LoadError(f"{zoo_id}.{short_id}", str(exc)))
            return

        try:
            meta = load_alpha_meta_from_py(py_file)
        except RegistryError as exc:
            self._load_errors.append(_LoadError(f"{zoo_id}.{short_id}", str(exc)))
            return

        module_path = f"arthaai.factors.zoo.{zoo_id}.{short_id}"
        alpha_id = meta.get("id", f"{zoo_id}_{short_id}")
        alpha = Alpha(id=alpha_id, zoo=zoo_id, module_path=module_path, meta=meta)
        if alpha.id in self._alphas:
            self._load_errors.append(_LoadError(alpha.id, "duplicate alpha id"))
            return
        self._alphas[alpha.id] = alpha
        self._py_paths[alpha.id] = py_file

    def list(
        self,
        zoo: str | None = None,
        theme: str | None = None,
        universe: str | None = None,
    ) -> list[str]:
        """Return alpha IDs matching the (optional) filters."""
        out: list[str] = []
        for a in self._alphas.values():
            if zoo is not None and a.zoo != zoo:
                continue
            if theme is not None and theme not in a.meta.get("theme", []):
                continue
            if universe is not None and universe not in a.meta.get("universe", []):
                continue
            out.append(a.id)
        return sorted(out)

    def get(self, alpha_id: str) -> Alpha:
        if alpha_id not in self._alphas:
            raise KeyError(f"alpha_id {alpha_id!r} not in registry")
        return self._alphas[alpha_id]

    def health(self) -> dict[str, Any]:
        return {
            "loaded": len(self._alphas),
            "failed": len(self._load_errors),
            "errors": [
                {"alpha_id": e.alpha_id, "reason": e.reason} for e in self._load_errors
            ],
        }

    def compute(self, alpha_id: str, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Lazy-import the alpha module and run its ``compute(panel)``."""
        alpha = self.get(alpha_id)
        meta = alpha.meta

        missing = [c for c in meta.get("columns_required", []) if c not in panel]
        if missing:
            raise SkipAlpha(f"{alpha_id}: panel missing required columns {missing}")

        try:
            module = self._load_module(alpha)
        except Exception as exc:
            raise RegistryError(f"{alpha_id}: import failed: {exc}") from exc

        compute_fn = getattr(module, "compute", None)
        if compute_fn is None:
            raise RegistryError(f"{alpha_id}: module has no compute() function")

        try:
            result = compute_fn(panel)
        except Exception as exc:
            raise RegistryError(f"{alpha_id}: compute() raised: {exc}") from exc

        return self._validate_output(alpha_id, result, panel)

    def _load_module(self, alpha: Alpha) -> ModuleType:
        if not self._use_filesystem_loader:
            return importlib.import_module(alpha.module_path)
        py_file = self._py_paths[alpha.id]
        cached = sys.modules.get(alpha.module_path)
        if cached is not None and getattr(cached, "__file__", None) == str(py_file):
            return cached
        spec = importlib.util.spec_from_file_location(alpha.module_path, py_file)
        if spec is None or spec.loader is None:
            raise RegistryError(f"{alpha.id}: could not build import spec for {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[alpha.module_path] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(alpha.module_path, None)
            raise
        return module

    @staticmethod
    def _validate_output(
        alpha_id: str,
        result: Any,
        panel: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        if not isinstance(result, pd.DataFrame):
            raise RegistryError(
                f"{alpha_id}: compute() returned {type(result).__name__}, expected DataFrame"
            )
        ref = panel.get("close")
        if ref is not None and result.shape != ref.shape:
            raise RegistryError(
                f"{alpha_id}: output shape {result.shape} != close shape {ref.shape}"
            )
        arr = result.to_numpy(dtype=np.float64, na_value=np.nan)
        if np.isinf(arr).any():
            raise RegistryError(f"{alpha_id}: output contains +/- inf")
        nan_ratio = float(np.isnan(arr).mean()) if arr.size > 0 else 1.0
        if nan_ratio > 0.95:
            raise RegistryError(f"{alpha_id}: output >95% NaN (nan_ratio={nan_ratio:.3f})")
        return result

    def export_manifest(self) -> dict[str, Any]:
        zoos: dict[str, list[dict[str, Any]]] = {}
        for a in self._alphas.values():
            zoos.setdefault(a.zoo, []).append(
                {"id": a.id, "module_path": a.module_path, "meta": a.meta}
            )
        return {
            "zoos": [
                {"zoo_id": zoo_id, "alphas": sorted(items, key=lambda x: x["id"])}
                for zoo_id, items in sorted(zoos.items())
            ],
            "health": self.health(),
        }


# Process-wide singleton
_registry_cache: "Registry | None" = None
_registry_cache_lock = threading.Lock()


def get_default_registry() -> Registry:
    global _registry_cache
    with _registry_cache_lock:
        if _registry_cache is None:
            _registry_cache = Registry()
        return _registry_cache


def reset_default_registry() -> None:
    global _registry_cache
    with _registry_cache_lock:
        _registry_cache = None
