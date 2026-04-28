#!/usr/bin/env python3
"""Refresh Nutmeg's local Python import graph assets.

The script intentionally uses only stdlib AST parsing so future agents can rebuild
architecture context without network access or optional tooling.
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    path: Path
    package: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate Nutmeg local code graph assets.')
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--output-dir', type=Path, default=Path('graphify-out'))
    return parser.parse_args()


def module_name_for(path: Path, project_root: Path) -> str:
    relative = path.relative_to(project_root).with_suffix('')
    parts = list(relative.parts)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def package_name(module_name: str) -> str:
    parts = module_name.split('.')
    if len(parts) <= 2:
        return module_name
    return '.'.join(parts[:2])


def discover_modules(project_root: Path) -> dict[str, ModuleInfo]:
    source_root = project_root / 'nutmeg'
    modules: dict[str, ModuleInfo] = {}
    for path in sorted(source_root.rglob('*.py')):
        name = module_name_for(path, project_root)
        modules[name] = ModuleInfo(name=name, path=path, package=package_name(name))
    return modules


def resolve_import_target(import_name: str, modules: set[str]) -> str | None:
    if not import_name.startswith('nutmeg'):
        return None
    parts = import_name.split('.')
    for end in range(len(parts), 0, -1):
        candidate = '.'.join(parts[:end])
        if candidate in modules:
            return candidate
    return None


def import_edges_for(path: Path, source: str, modules: set[str]) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    edges: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve_import_target(alias.name, modules)
                if target and target != source:
                    edges.add((source, target))
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module or not node.module.startswith('nutmeg'):
                continue
            module_target = resolve_import_target(node.module, modules)
            targets: set[str] = set()
            if module_target:
                targets.add(module_target)
            for alias in node.names:
                if alias.name == '*':
                    continue
                child_target = resolve_import_target(f'{node.module}.{alias.name}', modules)
                if child_target:
                    targets.add(child_target)
            for target in targets:
                if target != source:
                    edges.add((source, target))

    return edges


def build_graph(project_root: Path) -> dict[str, object]:
    modules = discover_modules(project_root)
    module_names = set(modules)
    edges: set[tuple[str, str]] = set()
    for source, info in modules.items():
        edges.update(import_edges_for(info.path, source, module_names))

    in_degree: Counter[str] = Counter()
    out_degree: Counter[str] = Counter()
    for source, target in edges:
        out_degree[source] += 1
        in_degree[target] += 1

    communities_counter: Counter[str] = Counter(info.package for info in modules.values())
    module_payload = [
        {
            'name': info.name,
            'path': info.path.relative_to(project_root).as_posix(),
            'package': info.package,
            'in_degree': in_degree[info.name],
            'out_degree': out_degree[info.name],
        }
        for info in sorted(modules.values(), key=lambda item: item.name)
    ]
    edge_payload = [
        {'source': source, 'target': target}
        for source, target in sorted(edges)
    ]
    communities = [
        {'package': package, 'module_count': count}
        for package, count in sorted(communities_counter.items())
    ]

    return {
        'module_count': len(modules),
        'edge_count': len(edges),
        'modules': module_payload,
        'edges': edge_payload,
        'communities': communities,
    }


def render_report(graph: dict[str, object]) -> str:
    modules = list(graph['modules'])
    edges = list(graph['edges'])
    communities = list(graph['communities'])
    high_degree = sorted(
        modules,
        key=lambda item: (-(item['in_degree'] + item['out_degree']), item['name']),
    )[:15]

    lines = [
        '# Nutmeg Code Graph Report',
        '',
        'Generated from local Python AST imports. Re-run with `make graph` after '
        'structural changes.',
        '',
        '## Summary',
        '',
        f"- Modules: {graph['module_count']}",
        f"- Internal dependency edges: {graph['edge_count']}",
        '- Scope: `nutmeg/**/*.py` only; no network or provider calls.',
        '',
        '## Package Communities',
        '',
    ]
    for community in communities:
        lines.append(f"- `{community['package']}`: {community['module_count']} modules")

    lines.extend(['', '## High-Degree Modules', ''])
    for module in high_degree:
        total = module['in_degree'] + module['out_degree']
        lines.append(
            f"- `{module['name']}`: degree {total} "
            f"(in {module['in_degree']}, out {module['out_degree']})"
        )

    lines.extend(['', '## Dependency Edges', ''])
    for edge in edges[:200]:
        lines.append(f"- `{edge['source']}` -> `{edge['target']}`")
    if len(edges) > 200:
        lines.append(f'- ... {len(edges) - 200} additional edges omitted; see `graph.json`.')

    return '\n'.join(lines) + '\n'


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    graph = build_graph(project_root)
    (output_dir / 'graph.json').write_text(json.dumps(graph, indent=2, sort_keys=True) + '\n')
    (output_dir / 'GRAPH_REPORT.md').write_text(render_report(graph))
    print(
        f"Wrote graph assets to {output_dir} "
        f"({graph['module_count']} modules, {graph['edge_count']} edges)."
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
