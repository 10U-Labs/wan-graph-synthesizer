import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable


def load_module_from_path(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_lambda_loader(lambdas_dir: Path) -> Callable[[str, str], ModuleType]:
    def load_lambda_module(filename: str, module_name: str) -> ModuleType:
        handler_path = lambdas_dir / filename
        lambdas_dir_str = str(lambdas_dir)
        if lambdas_dir_str not in sys.path:
            sys.path.insert(0, lambdas_dir_str)
        return load_module_from_path(module_name, handler_path)

    return load_lambda_module
