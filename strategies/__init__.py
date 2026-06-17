# -*- coding: utf-8 -*-
"""strategies/ 内の全 .py を自動 import して @register を走らせる。
→ ファイルを置くだけで手法が増え、消すだけで減る。
"""
import importlib
import pkgutil
from pathlib import Path

_pkg_dir = Path(__file__).parent
for _m in pkgutil.iter_modules([str(_pkg_dir)]):
    if _m.name.startswith("_"):
        continue
    importlib.import_module(f"{__name__}.{_m.name}")
