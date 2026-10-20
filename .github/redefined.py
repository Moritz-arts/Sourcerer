"""Names a module defines twice at its top level -- the second silently replaces the first (a new function once took the name of
Patreon's `_campaigns` cache dict and every Patreon source failed with "'function' object has no attribute 'get'"; py_compile and a
start never show it). Prints "file:line name" for each and exits 1 when there are any."""
import ast
import pathlib
import sys

found = 0
for path in sorted(pathlib.Path("Sourcerer_files").rglob("*.py")):
    if "venv" in path.parts or "Userdata" in path.parts:
        continue
    seen = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        for name in names:
            if name in seen:
                print("%s:%d %s (first at line %d)" % (path, node.lineno, name, seen[name]))
                found += 1
            seen[name] = node.lineno
sys.exit(1 if found else 0)
