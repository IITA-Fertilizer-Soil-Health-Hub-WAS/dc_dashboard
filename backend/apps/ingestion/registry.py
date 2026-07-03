"""Resolve a project's optional Python plugin from its ``plugin_path``.

Format: "dotted.module:ClassName" (e.g. "plugins.biossa:BioSSAPlugin").
Returns a no-op base plugin when a project declares none, so callers never
branch on whether a plugin exists.
"""
from __future__ import annotations

import importlib
from functools import lru_cache

from apps.common.plugins import BaseUseCasePlugin, UseCasePlugin


@lru_cache(maxsize=64)
def _load(plugin_path: str) -> UseCasePlugin:
    module_name, _, class_name = plugin_path.partition(":")
    if not module_name or not class_name:
        raise ValueError(f"Invalid plugin_path: {plugin_path!r} (expected 'module:Class')")
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls()


def get_plugin(project) -> UseCasePlugin:
    if project.plugin_path:
        return _load(project.plugin_path)
    return BaseUseCasePlugin()
