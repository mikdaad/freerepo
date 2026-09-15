"""cad2ai -- AutoCAD DWG -> structured JSON -> DeepSeek analysis pipeline.

The package is deliberately split along the three pipeline phases so each part
can be used (and tested) on its own::

    Phase 1  cad2ai.parser       lossless DWG read via ezdxf + odafc addon
             cad2ai.aps          Autodesk Platform Services metadata fallback
    Phase 2  cad2ai.structurer   DWG/DXF object model -> CadModel
             cad2ai.payload      CadModel -> minified, token-budgeted JSON
    Phase 3  cad2ai.ai_client    DeepSeek chat-completion client (OpenAI SDK)
             cad2ai.prompts      system prompt / task instructions
             cad2ai.pipeline     end-to-end orchestration + artifacts

Submodules are imported lazily (PEP 562) so that ``import cad2ai`` never pulls
in ``ezdxf``/``openai``/``requests``, and so tooling can still introspect the
package when only part of the dependency set is installed.
"""

from __future__ import annotations

from typing import Any

__version__ = "1.0.0"

# name -> (module, attribute)
_LAZY: dict[str, tuple[str, str]] = {
    "Settings": ("cad2ai.config", "Settings"),
    "CadModel": ("cad2ai.structurer", "CadModel"),
    "Pipeline": ("cad2ai.pipeline", "Pipeline"),
    "PipelineReport": ("cad2ai.pipeline", "PipelineReport"),
    "analyze_file": ("cad2ai.pipeline", "analyze_file"),
    "extract": ("cad2ai.pipeline", "extract"),
    "load_drawing": ("cad2ai.parser", "load_drawing"),
    "build_cad_model": ("cad2ai.structurer", "build_cad_model"),
    "DeepSeekClient": ("cad2ai.ai_client", "DeepSeekClient"),
    "ApsClient": ("cad2ai.aps", "ApsClient"),
    # Exceptions are re-exported for convenience (imported eagerly below).
}

__all__ = [
    "ApsClient",
    "CadModel",
    "DeepSeekClient",
    "Pipeline",
    "PipelineReport",
    "Settings",
    "analyze_file",
    "build_cad_model",
    "extract",
    "load_drawing",
    "__version__",
]


def __getattr__(name: str) -> Any:  # PEP 562
    # NOTE: `importlib.import_module` is used instead of ``from cad2ai import x``
    # because the latter re-enters this function through the import machinery
    # (its hasattr() probe) and recurses while the package is initialising.
    import importlib

    target = _LAZY.get(name)
    module_name = target[0] if target else "cad2ai.errors"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # optional dependency missing (ezdxf/openai/requests)
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r} (lazy import of "
            f"{module_name!r} failed: {exc}; run `pip install -r requirements.txt`)"
        ) from exc
    attribute = target[1] if target else name
    try:
        value = getattr(module, attribute)
    except AttributeError:
        candidates = ", ".join(sorted(_LAZY))
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}; try one of: {candidates}") from None
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    return sorted(set(list(globals()) + list(_LAZY) + ["__version__"]))
