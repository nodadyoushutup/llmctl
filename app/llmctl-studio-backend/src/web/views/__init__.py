from __future__ import annotations

import sys
import types

from . import shared as _shared
from . import agents_runs as _agents_runs
from . import chat_nodes as _chat_nodes
from . import plans_milestones as _plans_milestones
from . import flowcharts as _flowcharts
from . import models_mcps as _models_mcps
from . import artifacts_attachments as _artifacts_attachments
from . import settings_providers as _settings_providers
from . import settings_integrations as _settings_integrations
from .shared import *  # noqa: F401,F403

_ROUTE_MODULES = (
    _agents_runs,
    _chat_nodes,
    _plans_milestones,
    _flowcharts,
    _models_mcps,
    _artifacts_attachments,
    _settings_providers,
    _settings_integrations,
)
_MIRROR_MODULES = (_shared, *_ROUTE_MODULES)

for _module in _ROUTE_MODULES:
    for _name in getattr(_module, "__all__", []):
        globals()[_name] = getattr(_module, _name)


class _ViewsPackage(types.ModuleType):
    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        if name.startswith("__"):
            return
        for module in _MIRROR_MODULES:
            if name in module.__dict__:
                module.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        for module in _MIRROR_MODULES:
            module.__dict__.pop(name, None)


sys.modules[__name__].__class__ = _ViewsPackage
