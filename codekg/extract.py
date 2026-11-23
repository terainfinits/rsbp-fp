import ast
import tokenize
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pathspec import GitIgnoreSpec
from rdflib import Literal, RDF

from .model import KG, entity, identifier, new_graph

SKIP = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
        ".ruff_cache", ".tox", ".nox", "codekg-out"}


@dataclass(eq=False)
class Scope:
    key: object
    kind: str
    path: str
    module: str
    name: str = ""
    parent: object = None
    bindings: dict = field(default_factory=lambda: defaultdict(list))
    wildcard: bool = False


@dataclass(frozen=True)
class Imported:
    name: str


def inventory(root):
    def walk(directory, rules):
        ignore = directory / ".gitignore"
        if ignore.is_file():
            rules = rules + [(directory, GitIgnoreSpec.from_lines(
                ignore.read_text(encoding="utf-8-sig", errors="replace").splitlines()))]
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink() or entry.name in SKIP:
                continue
            folder = entry.is_dir()
            if folder and (entry / "pyvenv.cfg").is_file():
                continue
            ignored = False
            for base, spec in rules:
                relative = entry.relative_to(base).as_posix() + ("/" if folder else "")
                decision = spec.check_file(relative).include
                if decision is not None:
                    ignored = decision
            if ignored or not (folder or entry.is_file()):
                continue
            yield entry
            if folder:
                yield from walk(entry, rules)
    yield from walk(root, [])


class Collector(ast.NodeVisitor):
    def __init__(self, graph, scope, package):
        self.graph = graph
        self.scope = scope
        self.package = package
        self.calls = []
        self.bases = []
        self.imports = []
        self.count = 0
        self.occurrences = defaultdict(int)
        self.conditional = 0

    def bind(self, name, value=None):
        self.scope.bindings[name].append(None if self.conditional else value)

    def declare(self, name, kind, node):
        outer = self.scope
        fullname = ".".join(filter(None, [outer.name, name]))
        self.occurrences[fullname] += 1
        occurrence = self.occurrences[fullname]
        identity = fullname if occurrence == 1 else f"{fullname}#{occurrence}"
        key = identifier("symbol", outer.path, identity)
        inner = Scope(key, kind, outer.path, outer.module, fullname, outer)
        entity(self.graph, key, kind, outer.path, name,
               ".".join(filter(None, [outer.module, fullname])), node)
        self.graph.add((outer.key, KG.declares, key))
        self.bind(name, inner)
        self.count += 1
        return inner

    def definition(self, node, kind):
        outer = self.scope
        inner = self.declare(node.name, kind, node)
        for parameter in getattr(node, "type_params", []):
            self.visit(parameter)
        for expression in node.decorator_list:
            self.visit(expression)
        if kind == "Class":
            for base in node.bases:
                self.bases.append((outer, inner, base))
                self.visit(base)
            for kw in node.keywords:
                self.visit(kw.value)
        else:
            for expression in [*node.args.defaults, *node.args.kw_defaults]:
                if expression:
                    self.visit(expression)
            for arg in ast.walk(node.args):
                if isinstance(arg, ast.arg):
                    inner.bindings[arg.arg].append(None)
                    if arg.annotation:
                        self.visit(arg.annotation)
            if node.returns:
                self.visit(node.returns)
        self.scope = inner
        previous, self.conditional = self.conditional, 0
        for statement in node.body:
            self.visit(statement)
        self.scope, self.conditional = outer, previous

    def visit_ClassDef(self, node):
        self.definition(node, "Class")

    def visit_FunctionDef(self, node):
        self.definition(node, "Method" if self.scope.kind == "Class" else "Function")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append((self.scope, alias.name))
            first = alias.name.split(".")[0]
            self.bind(alias.asname or first, Imported(alias.name if alias.asname else first))

    def visit_ImportFrom(self, node):
        prefix = node.module or ""
        if node.level:
            parts = self.package.split(".") if self.package else []
            if node.level > len(parts):
                prefix = "<invalid>"
            else:
                prefix = ".".join(filter(None, parts[:len(parts) - node.level + 1] + [prefix]))
        self.imports.append((self.scope, prefix))
        for alias in node.names:
            if alias.name == "*":
                self.scope.wildcard = True
            else:
                target = ".".join(filter(None, [prefix, alias.name]))
                self.imports.append((self.scope, target))
                self.bind(alias.asname or alias.name, Imported(target))

    def visit_conditional(self, node):
        self.conditional += 1
        self.generic_visit(node)
        self.conditional -= 1

    visit_If = visit_conditional
    visit_Try = visit_conditional
    visit_TryStar = visit_conditional
    visit_Match = visit_conditional
    visit_For = visit_conditional
    visit_AsyncFor = visit_conditional
    visit_While = visit_conditional

    def visit_Call(self, node):
        self.calls.append((self.scope, node, False))
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node.id)

    def assignment(self, node, targets):
        for target in targets:
            if (self.scope.kind == "File" and isinstance(target, ast.Name)
                    and target.id.isupper()):
                self.declare(target.id, "Constant", node)
            else:
                self.visit(target)
        if node.value:
            self.visit(node.value)

    def visit_Assign(self, node):
        self.assignment(node, node.targets)

    def visit_AnnAssign(self, node):
        self.assignment(node, [node.target])
        self.visit(node.annotation)

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bind(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.bind(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self.bind(node.rest)
        self.generic_visit(node)

    def visit_Global(self, node):
        for name in node.names:
            scope = self.scope
            while scope:
                scope.bindings[name].append(None)
                scope = scope.parent

    visit_Nonlocal = visit_Global

    def isolated_expression(self, node):
        # Lambda dan comprehension memiliki lingkungan nama tersendiri.
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                self.calls.append((self.scope, child, True))

    visit_Lambda = isolated_expression
    visit_ListComp = isolated_expression
    visit_SetComp = isolated_expression
    visit_DictComp = isolated_expression
    visit_GeneratorExp = isolated_expression


class Resolver:
    def __init__(self, modules):
        self.modules = modules

    def imported(self, name, seen):
        if name in seen:
            return None
        if name in self.modules:
            options = self.modules[name]
            return options[0] if len(options) == 1 else None
        parent, _, member = name.rpartition(".")
        if not parent:
            return None
        source = self.imported(parent, seen | {name})
        if source:
            return self.member(source, member, seen | {name})
        return None

    def member(self, scope, name, seen):
        values = scope.bindings.get(name, [])
        if scope.wildcard or len(values) != 1:
            return None
        value = values[0]
        if isinstance(value, Imported):
            return self.imported(value.name, seen)
        return value

    def expression(self, scope, node):
        if isinstance(node, ast.Name):
            while scope:
                if node.id in scope.bindings or scope.wildcard:
                    return self.member(scope, node.id, set())
                scope = scope.parent
                while scope and scope.kind == "Class":
                    scope = scope.parent
        elif isinstance(node, ast.Attribute):
            parts = []
            base = node
            while isinstance(base, ast.Attribute):
                parts.insert(0, base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                owner = scope
                while owner:
                    values = owner.bindings.get(base.id, [])
                    if owner.wildcard:
                        return None
                    if values:
                        if len(values) == 1 and isinstance(values[0], Imported):
                            return self.imported(".".join([values[0].name, *parts]), set())
                        break
                    owner = owner.parent
                    while owner and owner.kind == "Class":
                        owner = owner.parent
            target = self.expression(scope, node.value)
            if target:
                return self.member(target, node.attr, set())
        return None


def extract(root):
    graph = new_graph()
    modules = defaultdict(list)
    collectors = []
    stats = dict(files=0, symbols=0, resolved=0, unresolved=0, errors=[])
    entity(graph, identifier("folder", "."), "Folder", ".", root.name, ".")
    for entry in inventory(root):
        path = entry.relative_to(root).as_posix()
        folder = entry.is_dir()
        kind = "Folder" if folder else "File"
        key = identifier(kind.lower(), path)
        entity(graph, key, kind, path, entry.name, path)
        graph.add((identifier("folder", Path(path).parent.as_posix()), KG.contains, key))
        if folder:
            continue
        stats["files"] += 1
        if entry.suffix != ".py":
            continue
        try:
            with tokenize.open(entry) as source:
                tree = ast.parse(source.read(), filename=path)
        except (SyntaxError, UnicodeError, OSError) as exc:
            stats["errors"].append(dict(path=path, reason=str(exc)))
            continue
        parts = list(Path(path).with_suffix("").parts)
        if parts[0] == "src" and len(parts) > 1 and not (root / "src/__init__.py").exists():
            parts.pop(0)
        package_init = parts[-1] == "__init__"
        if package_init:
            parts.pop()
        module = ".".join(parts)
        scope = Scope(key, "File", path, module)
        modules[module].append(scope)
        collector = Collector(graph, scope, module if package_init else ".".join(parts[:-1]))
        collector.visit(tree)
        collectors.append(collector)
        stats["symbols"] += collector.count
    resolver = Resolver(modules)
    for collector in collectors:
        for scope, name in collector.imports:
            targets = modules.get(name, [])
            if len(targets) == 1:
                graph.add((scope.key, KG.imports, targets[0].key))
        for scope, subclass, base in collector.bases:
            superclass = resolver.expression(scope, base)
            if superclass and superclass.kind == "Class":
                graph.add((subclass.key, KG.inheritsFrom, superclass.key))
        for scope, node, uncertain in collector.calls:
            target = None if uncertain else resolver.expression(scope, node.func)
            site = identifier("site", scope.path, f"{node.lineno}.{node.col_offset}-{node.end_lineno}.{node.end_col_offset}")
            graph.add((site, RDF.type, KG.CallSite))
            for prop, value in [(KG.path, scope.path), (KG.line, node.lineno),
                                (KG.column, node.col_offset), (KG.expression, ast.unparse(node.func))]:
                graph.add((site, prop, Literal(value)))
            graph.add((site, KG.caller, scope.key))
            resolved = target and target.kind in {"Method", "Function", "Class"}
            status = "resolved" if resolved else "unresolved"
            stats[status] += 1
            graph.add((site, KG.status, Literal(status)))
            if resolved:
                graph.add((site, KG.target, target.key))
                graph.add((scope.key, KG.calls, target.key))
    return graph, stats
