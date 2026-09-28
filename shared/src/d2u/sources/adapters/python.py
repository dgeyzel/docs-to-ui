"""Python adapter: public API extraction with `ast` only.

User code is parsed, never imported or executed.
"""

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from d2u.schemas.docpage import ApiSurface, Operation, Param, SourceLocation
from d2u.sources.bundle import SourceBundle, SourceFile
from d2u.sources.exceptions import InputError

MAX_REEXPORT_DEPTH = 5


@dataclass(slots=True)
class _Module:
    name: str
    path: str
    tree: ast.Module
    is_package: bool
    all_names: list[str] | None
    definitions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)


class PythonAdapter:
    """Adapter for Python source code."""

    name: str = "python"
    display_name: str = "Python"
    file_extensions: tuple[str, ...] = (".py",)
    default_excludes: tuple[str, ...] = (
        "**/tests/**",
        "**/test_*.py",
        "**/.venv/**",
        "**/venv/**",
        "**/__pycache__/**",
        "**/build/**",
        "**/dist/**",
        "**/site-packages/**",
    )
    example_languages: tuple[str, ...] = ("python",)

    def includes(self, path: str) -> bool:
        """Whether the path is a `.py` file."""
        return path.lower().endswith(".py")

    def sniff(self, bundle: SourceBundle) -> float:
        """0.9 if a file defines something public, 0.3 if Python parses, else 0.05."""
        files = [file for file in bundle.files if self.includes(file.path)]
        if not files:
            return 0.0
        score = 0.05
        for file in files:
            try:
                tree = ast.parse(file.text)
            except SyntaxError, ValueError:
                continue
            if any(_is_public_definition(node) for node in tree.body):
                return 0.9
            score = 0.3
        return score

    def extract(self, bundle: SourceBundle) -> ApiSurface:
        """List public functions, classes and methods with their signatures.

        Raises:
            InputError: A file doesn't parse, or nothing public was found.
        """
        files = [file for file in bundle.files if self.includes(file.path)]
        if not files:
            raise InputError(
                path="", line=None, message="No Python (.py) files were found."
            )
        root = package_root([file.path for file in files])
        modules = {
            module.name: module for module in (_parse(file, root) for file in files)
        }

        operations: list[Operation] = []
        reexported: set[tuple[str, str]] = set()
        for module in sorted(modules.values(), key=lambda module: module.path):
            if not module.is_package or module.all_names is None:
                continue
            for public_name in module.all_names:
                if public_name in module.definitions:
                    continue
                target = _resolve_reexport(modules, module, public_name)
                if target is None:
                    continue
                target_module, node = target
                reexported.add((target_module.name, node.name))
                operations.extend(
                    _operations_for(
                        node,
                        public_path=f"{module.name}.{public_name}",
                        module_path=module.name,
                        location_path=target_module.path,
                    )
                )

        for module in sorted(modules.values(), key=lambda module: module.path):
            for name in _public_names(module):
                if (module.name, name) in reexported:
                    continue
                operations.extend(
                    _operations_for(
                        module.definitions[name],
                        public_path=f"{module.name}.{name}" if module.name else name,
                        module_path=module.name,
                        location_path=module.path,
                    )
                )

        if not operations:
            raise InputError(
                path="", line=None, message="No public functions or classes were found."
            )
        return ApiSurface(
            title=_title(modules), language="python", operations=operations
        )

    def group_key(self, op: Operation) -> str:
        """Module for functions; the class for classes and their methods."""
        return op.group_hint


def package_root(paths: list[str]) -> str:
    """The directory module paths are derived from ("" for the bundle root).

    A `src/` layout wins. Otherwise it is the parent of the shallowest
    directories that contain an `__init__.py`.
    """
    if any(path.startswith("src/") for path in paths):
        return "src/"
    package_dirs = [
        PurePosixPath(path).parent
        for path in paths
        if PurePosixPath(path).name == "__init__.py"
    ]
    if not package_dirs:
        return ""
    shallowest = min(len(directory.parts) for directory in package_dirs)
    parents = {
        str(directory.parent)
        for directory in package_dirs
        if len(directory.parts) == shallowest
    }
    parent = min(parents)
    return "" if parent == "." else f"{parent}/"


def module_name(path: str, root: str) -> tuple[str, bool]:
    """Dotted module name for a file, and whether it is a package `__init__`.

    Files outside the root are named from their path in the bundle.
    """
    relative = path[len(root) :] if root and path.startswith(root) else path
    parts = list(PurePosixPath(relative).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _parse(file: SourceFile, root: str) -> _Module:
    try:
        tree = ast.parse(file.text, filename=file.path)
    except SyntaxError as exc:
        raise InputError(
            path=file.path, line=exc.lineno, message=f"Syntax error: {exc.msg}."
        ) from exc
    except ValueError as exc:
        raise InputError(path=file.path, line=None, message=str(exc)) from exc

    name, is_package = module_name(file.path, root)
    module = _Module(
        name=name,
        path=file.path,
        tree=tree,
        is_package=is_package,
        all_names=_dunder_all(tree),
        definitions={
            node.name: node
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        },
    )
    package = name if is_package else name.rpartition(".")[0]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            source = _absolute_module(node, package)
            for alias in node.names:
                module.imports[alias.asname or alias.name] = (source, alias.name)
    return module


def _absolute_module(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    base = package.split(".") if package else []
    if node.level > 1:
        base = base[: len(base) - (node.level - 1)]
    if node.module:
        base = [*base, *node.module.split(".")]
    return ".".join(base)


def _dunder_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        targets: Sequence[ast.expr] = ()
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        if isinstance(value, ast.List | ast.Tuple):
            return [
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
    return None


def _is_public_definition(node: ast.stmt) -> bool:
    return isinstance(
        node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) and not node.name.startswith("_")


def _public_names(module: _Module) -> list[str]:
    if module.all_names is not None:
        return [name for name in module.all_names if name in module.definitions]
    return [name for name in module.definitions if not name.startswith("_")]


def _resolve_reexport(
    modules: dict[str, _Module], module: _Module, name: str
) -> tuple[_Module, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] | None:
    current, current_name = module, name
    for _ in range(MAX_REEXPORT_DEPTH):
        imported = current.imports.get(current_name)
        if imported is None:
            return None
        source_name, original = imported
        source = modules.get(source_name)
        if source is None:
            return None
        node = source.definitions.get(original)
        if node is not None:
            return source, node
        current, current_name = source, original
    return None


def _operations_for(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    *,
    public_path: str,
    module_path: str,
    location_path: str,
) -> list[Operation]:
    if isinstance(node, ast.ClassDef):
        return _class_operations(
            node, public_path=public_path, location_path=location_path
        )
    return [
        _function_operation(
            node,
            op_id=public_path,
            kind="function",
            group=module_path or public_path,
            location_path=location_path,
            skip_first=False,
        )
    ]


def _class_operations(
    node: ast.ClassDef, *, public_path: str, location_path: str
) -> list[Operation]:
    init = next(
        (
            child
            for child in node.body
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            and child.name == "__init__"
        ),
        None,
    )
    bases = ", ".join(ast.unparse(base) for base in node.bases)
    params = _params(init, op_id=public_path, skip_first=True) if init else []
    arguments = ", ".join(_param_text(param) for param in params)
    signature = f"class {node.name}({bases})" if bases else f"class {node.name}"
    if init:
        signature = f"{signature}: {node.name}({arguments})"
    operations = [
        Operation(
            id=public_path,
            kind="class",
            signature=signature,
            group_hint=public_path,
            params=params,
            source_description=ast.get_docstring(node),
            location=SourceLocation(path=location_path, line=node.lineno),
        )
    ]
    for child in node.body:
        if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if child.name.startswith("_"):
            continue
        decorators = {_decorator_name(decorator) for decorator in child.decorator_list}
        operations.append(
            _function_operation(
                child,
                op_id=f"{public_path}.{child.name}",
                kind="method",
                group=public_path,
                location_path=location_path,
                skip_first="staticmethod" not in decorators,
            )
        )
    return operations


def _decorator_name(decorator: ast.expr) -> str:
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        return decorator.attr
    if isinstance(decorator, ast.Call):
        return _decorator_name(decorator.func)
    return ""


def _function_operation(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    op_id: str,
    kind: str,
    group: str,
    location_path: str,
    skip_first: bool,
) -> Operation:
    params = _params(node, op_id=op_id, skip_first=skip_first)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    arguments = ", ".join(_param_text(param) for param in params)
    returns = ast.unparse(node.returns) if node.returns else None
    signature = f"{prefix}{node.name}({arguments})"
    if returns:
        signature = f"{signature} -> {returns}"
    return Operation(
        id=op_id,
        kind="method" if kind == "method" else "function",
        signature=signature,
        group_hint=group,
        params=params,
        returns=returns,
        source_description=ast.get_docstring(node),
        location=SourceLocation(path=location_path, line=node.lineno),
    )


def _params(
    node: ast.FunctionDef | ast.AsyncFunctionDef, *, op_id: str, skip_first: bool
) -> list[Param]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults.extend(args.defaults)
    pairs: list[tuple[ast.arg, ast.expr | None, str]] = [
        (arg, default, "arg") for arg, default in zip(positional, defaults, strict=True)
    ]
    if skip_first and pairs:
        pairs = pairs[1:]
    if args.vararg:
        pairs.append((args.vararg, None, "vararg"))
    pairs.extend(
        (arg, default, "kwarg")
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    )
    if args.kwarg:
        pairs.append((args.kwarg, None, "varkw"))

    params = []
    for arg, default, role in pairs:
        name = arg.arg
        if role == "vararg":
            name = f"*{arg.arg}"
        elif role == "varkw":
            name = f"**{arg.arg}"
        params.append(
            Param(
                id=f"{op_id}#{arg.arg}",
                name=name,
                location="kwarg" if role in ("kwarg", "varkw") else "arg",
                type=ast.unparse(arg.annotation) if arg.annotation else "Any",
                required=default is None and role in ("arg", "kwarg"),
                default=ast.unparse(default) if default is not None else None,
            )
        )
    return params


def _param_text(param: Param) -> str:
    text = param.name
    if param.type != "Any":
        text = f"{text}: {param.type}"
    if param.default is not None:
        text = f"{text} = {param.default}"
    return text


def _title(modules: dict[str, _Module]) -> str:
    packages = sorted({name.split(".")[0] for name in modules if name})
    if len(packages) == 1:
        return packages[0]
    if packages:
        return ", ".join(packages[:3]) + (" and more" if len(packages) > 3 else "")
    return "Python API"
