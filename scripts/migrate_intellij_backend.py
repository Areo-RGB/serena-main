from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def class_block(text: str, name: str) -> str:
    marker = f"class {name}"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"Could not find {marker}")
    next_match = __import__("re").search(r"^class [A-Za-z0-9_]+", text[start + 1 :], __import__("re").MULTILINE)
    end = start + 1 + next_match.start() if next_match else len(text)
    return text[start:end].rstrip() + "\n\n"


def replace_class(text: str, name: str, replacement: str) -> str:
    old = class_block(text, name)
    return text.replace(old, replacement.strip() + "\n\n", 1)


symbol_path = ROOT / "src/serena/tools/symbol_tools.py"
symbol = symbol_path.read_text(encoding="utf-8")
symbol = symbol.replace(
    "from serena.index_mcp_client import IndexMcpClient, find_structure_node, parse_file_structure_tree\n",
    "from serena.intellij_mcp_client import IntellijMcpClient\n",
)
symbol = replace_class(symbol, "GetSymbolsOverviewTool", '''
class GetSymbolsOverviewTool(Tool, ToolMarkerSymbolicRead):
    """Gets an overview of symbols through Code Intelligence MCP."""

    symbol_dict_grouper = LanguageServerSymbolDictGrouper(["kind"], ["kind"], collapse_singleton=True)

    @staticmethod
    def _kind_name(raw_kind: str) -> str:
        mapping = {
            "CLASS": "Class",
            "INTERFACE": "Interface",
            "ENUM": "Enum",
            "TRAIT": "Interface",
            "FUNCTION": "Function",
            "METHOD": "Method",
            "PROPERTY": "Property",
            "FIELD": "Field",
            "VARIABLE": "Variable",
            "CONSTANT": "Constant",
            "PARAMETER": "Variable",
            "MODULE": "Module",
            "PACKAGE": "Package",
        }
        raw = str(raw_kind or "Object").upper()
        return mapping.get(raw, raw.title().replace("_", ""))

    @classmethod
    def _convert_node(cls, node: dict[str, Any], depth: int) -> dict[str, Any]:
        symbol = node.get("symbol") or {}
        out: dict[str, Any] = {
            "name": str(symbol.get("name") or "unknown"),
            "kind": cls._kind_name(str(symbol.get("kind") or "Object")),
        }
        if depth > 0:
            children = [cls._convert_node(child, depth - 1) for child in node.get("children", []) if isinstance(child, dict)]
            if children:
                out["children"] = children
        return out

    def apply(self, relative_path: str, depth: int = -1, max_answer_chars: int = -1) -> str:
        """
        Get a high-level view of symbols in a file through intellij-mcp ``get_file_symbols``.

        :param relative_path: path to the source file, relative to the active Serena project
        :param depth: descendant depth to include; -1 chooses 1 for Java/Kotlin and 0 otherwise
        :param max_answer_chars: max result length; -1 uses Serena's configured default
        :return: symbols grouped by kind in Serena-compatible format
        """
        self.project.validate_relative_path(relative_path)
        client = IntellijMcpClient(self.get_project_root())
        payload = client.call_tool("get_file_symbols", {"filePath": client.absolute_file_path(relative_path)})
        if not isinstance(payload, dict):
            return self._to_json({})

        if depth == -1:
            language = str(payload.get("language") or "").lower()
            depth = 1 if language in {"java", "kotlin"} else 0

        symbol_dicts = [
            self._convert_node(node, depth)
            for node in payload.get("symbols", [])
            if isinstance(node, dict)
        ]
        compact_result = self.symbol_dict_grouper.group(symbol_dicts)
        result_json = self._to_json(compact_result)

        def make_kind_counts() -> str:
            return f"Symbol counts by kind:\n{self._to_json(Counter(d.get('kind', 'unknown') for d in symbol_dicts))}"

        return self._limit_length(result_json, max_answer_chars, shortened_result_factories=[make_kind_counts])

    def get_symbol_overview(self, relative_path: str, depth: int = 0) -> list[dict[str, Any]]:
        self.project.validate_relative_path(relative_path)
        client = IntellijMcpClient(self.get_project_root())
        payload = client.call_tool("get_file_symbols", {"filePath": client.absolute_file_path(relative_path)})
        if not isinstance(payload, dict):
            return []
        return [
            self._convert_node(node, depth)
            for node in payload.get("symbols", [])
            if isinstance(node, dict)
        ]
''')
symbol = replace_class(symbol, "FindSymbolTool", '''
class FindSymbolTool(Tool, ToolMarkerSymbolicRead):
    """Finds symbols through Code Intelligence MCP."""

    symbol_dict_grouper = LanguageServerSymbolDictGrouper([], ["kind"], collapse_singleton=True)

    _INTELLIJ_TO_SERENA_KIND = {
        "CLASS": "Class", "INTERFACE": "Interface", "ENUM": "Enum", "TRAIT": "Interface",
        "FUNCTION": "Function", "METHOD": "Method", "PROPERTY": "Property", "FIELD": "Field",
        "VARIABLE": "Variable", "CONSTANT": "Constant", "PARAMETER": "Variable",
        "MODULE": "Module", "PACKAGE": "Package",
    }

    @classmethod
    def _kind_name(cls, symbol: dict[str, Any]) -> str:
        raw = str(symbol.get("kind") or "Object").upper()
        return cls._INTELLIJ_TO_SERENA_KIND.get(raw, raw.title().replace("_", ""))

    @staticmethod
    def _split_overload(component: str) -> tuple[str, int | None]:
        if component.endswith("]") and "[" in component:
            base, _, suffix = component.rpartition("[")
            index_text = suffix[:-1]
            if index_text.isdigit():
                return base, int(index_text)
        return component, None

    @staticmethod
    def _path_matches(relative_path: str, candidate: str) -> bool:
        if not relative_path:
            return True
        wanted = relative_path.replace("\\", "/").strip("/")
        candidate_norm = candidate.replace("\\", "/").strip("/")
        return candidate_norm == wanted or candidate_norm.startswith(wanted.rstrip("/") + "/")

    @classmethod
    def _name_path(cls, symbol: dict[str, Any]) -> str:
        name = str(symbol.get("name") or "unknown")
        kind = str(symbol.get("kind") or "").upper()
        qualified = str(symbol.get("qualifiedName") or "").replace("::", ".")
        if kind in {"METHOD", "PROPERTY", "FIELD", "PARAMETER"} and qualified:
            parts = [p for p in qualified.split(".") if p]
            if len(parts) >= 2:
                return f"{parts[-2]}/{name}"
        return name

    @classmethod
    def _name_path_matches(cls, pattern: str, candidate: str, substring_matching: bool) -> bool:
        absolute = pattern.startswith("/")
        pattern_parts = [p for p in pattern.strip("/").split("/") if p]
        candidate_parts = [p for p in candidate.strip("/").split("/") if p]
        if len(pattern_parts) > len(candidate_parts):
            return False
        if absolute and len(pattern_parts) != len(candidate_parts):
            return False
        offset = len(candidate_parts) - len(pattern_parts)
        for i, expected in enumerate(pattern_parts):
            actual = candidate_parts[offset + i]
            expected_base, expected_overload = cls._split_overload(expected)
            actual_base, actual_overload = cls._split_overload(actual)
            if expected_overload is not None and expected_overload != actual_overload:
                return False
            if substring_matching and i == len(pattern_parts) - 1:
                if expected_base not in actual_base:
                    return False
            elif expected_base != actual_base:
                return False
        return True

    @classmethod
    def _relative_file(cls, client: IntellijMcpClient, symbol: dict[str, Any]) -> str:
        location = symbol.get("location") or {}
        return client.relative_file_path(str(location.get("filePath") or ""))

    @classmethod
    def _name_paths_with_overloads(cls, client: IntellijMcpClient, symbols: list[dict[str, Any]]) -> list[str]:
        paths = [cls._name_path(symbol) for symbol in symbols]
        groups: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
        for i, (symbol, path) in enumerate(zip(symbols, paths, strict=True)):
            if str(symbol.get("kind") or "").upper() in {"METHOD", "FUNCTION"}:
                groups[(cls._relative_file(client, symbol), path)].append(i)
        for (_, base_path), indices in groups.items():
            if len(indices) <= 1:
                continue
            indices.sort(key=lambda i: (
                int(((symbols[i].get("nameLocation") or symbols[i].get("location") or {}).get("line")) or 1),
                int(((symbols[i].get("nameLocation") or symbols[i].get("location") or {}).get("column")) or 1),
                str(symbols[i].get("signature") or ""),
            ))
            for overload_index, i in enumerate(indices):
                paths[i] = f"{base_path}[{overload_index}]"
        return paths

    @classmethod
    def _find_file_symbol_node(cls, nodes: list[dict[str, Any]], *, line_1: int, name: str) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        def visit(node: dict[str, Any]) -> None:
            symbol = node.get("symbol") or {}
            location = symbol.get("location") or {}
            start = int(location.get("line") or 1)
            end = int(location.get("endLine") or start)
            if start <= line_1 <= end:
                candidates.append(node)
                for child in node.get("children", []):
                    if isinstance(child, dict):
                        visit(child)
        for node in nodes:
            if isinstance(node, dict):
                visit(node)
        named = [node for node in candidates if str((node.get("symbol") or {}).get("name") or "") == name]
        if named:
            candidates = named
        if not candidates:
            return None
        def span(node: dict[str, Any]) -> int:
            location = (node.get("symbol") or {}).get("location") or {}
            start = int(location.get("line") or 1)
            return int(location.get("endLine") or start) - start
        return min(candidates, key=span)

    @classmethod
    def _convert_child(cls, node: dict[str, Any], depth: int) -> dict[str, Any]:
        symbol = node.get("symbol") or {}
        out: dict[str, Any] = {"name": str(symbol.get("name") or "unknown"), "kind": cls._kind_name(symbol)}
        if depth > 1:
            children = [cls._convert_child(child, depth - 1) for child in node.get("children", []) if isinstance(child, dict)]
            if children:
                out["children"] = children
        return out

    def _search(self, client: IntellijMcpClient, name_path_pattern: str, relative_path: str, substring_matching: bool) -> tuple[list[dict[str, Any]], list[str]]:
        final_component = name_path_pattern.strip("/").split("/")[-1]
        query_name, requested_overload = self._split_overload(final_component)
        raw = client.call_tool("find_symbol", {"name": query_name})
        symbols = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        paths = self._name_paths_with_overloads(client, symbols)
        matches: list[dict[str, Any]] = []
        match_paths: list[str] = []
        for symbol, candidate_path in zip(symbols, paths, strict=True):
            rel_file = self._relative_file(client, symbol)
            if relative_path and not self._path_matches(relative_path, rel_file):
                continue
            if not self._name_path_matches(name_path_pattern, candidate_path, substring_matching):
                continue
            if requested_overload is not None and self._split_overload(candidate_path.split("/")[-1])[1] != requested_overload:
                continue
            matches.append(symbol)
            match_paths.append(candidate_path)
        return matches, match_paths

    def apply(self, name_path_pattern: str, depth: int = 0, relative_path: str = "", include_body: bool = False,
              include_info: bool = False, include_kinds: list[int] = [], exclude_kinds: list[int] = [],
              substring_matching: bool = False, max_matches: int = -1, max_answer_chars: int = -1) -> str:  # noqa: B006
        """Find symbols through intellij-mcp ``find_symbol`` while retaining Serena's public result shape."""
        if not name_path_pattern:
            raise ValueError("name_path_pattern must not be empty")
        if max_matches == 0:
            raise ValueError("max_matches must be > 0 or equal to -1")
        if relative_path:
            self.project.validate_relative_path(relative_path)

        client = IntellijMcpClient(self.get_project_root())
        raw_matches, name_paths = self._search(client, name_path_pattern, relative_path, substring_matching)
        include_kind_names = {SymbolKind(k).name.lower() for k in include_kinds} if include_kinds else None
        exclude_kind_names = {SymbolKind(k).name.lower() for k in exclude_kinds} if exclude_kinds else set()
        matches: list[dict[str, Any]] = []
        file_symbols_cache: dict[str, dict[str, Any]] = {}

        for raw, candidate_path in zip(raw_matches, name_paths, strict=True):
            kind_name = self._kind_name(raw)
            if include_kind_names is not None and kind_name.lower() not in include_kind_names:
                continue
            if kind_name.lower() in exclude_kind_names:
                continue
            rel_file = self._relative_file(client, raw)
            location = raw.get("location") or {}
            line_1 = int(location.get("line") or 1)
            end_line_1 = int(location.get("endLine") or line_1)
            out: dict[str, Any] = {
                "name_path": candidate_path,
                "kind": kind_name,
                "relative_path": rel_file,
                "body_location": {"start_line": max(0, line_1 - 1), "end_line": max(0, end_line_1 - 1)},
            }
            node: dict[str, Any] | None = None
            if depth > 0 or include_body:
                if rel_file not in file_symbols_cache:
                    payload = client.call_tool("get_file_symbols", {"filePath": client.absolute_file_path(rel_file)})
                    file_symbols_cache[rel_file] = payload if isinstance(payload, dict) else {}
                node = self._find_file_symbol_node(file_symbols_cache[rel_file].get("symbols", []), line_1=line_1, name=str(raw.get("name") or ""))
                if node is not None:
                    node_location = (node.get("symbol") or {}).get("location") or {}
                    start = int(node_location.get("line") or line_1)
                    end = int(node_location.get("endLine") or start)
                    out["body_location"] = {"start_line": max(0, start - 1), "end_line": max(0, end - 1)}
            if include_body:
                start = int(out["body_location"]["start_line"])
                end = int(out["body_location"]["end_line"])
                lines = self.project.read_file(rel_file).splitlines()
                out["body"] = "\n".join(lines[start : end + 1])
            elif include_info:
                info_parts = [str(raw.get("signature") or "").strip(), str(raw.get("documentation") or "").strip()]
                if raw.get("returnType"):
                    info_parts.append(f"returns: {raw['returnType']}")
                out["info"] = "\n".join(part for part in info_parts if part)
            if depth > 0 and node is not None:
                children = [self._convert_child(child, depth) for child in node.get("children", []) if isinstance(child, dict)]
                if children:
                    out["children"] = children
            matches.append(out)

        n_matches = len(matches)
        def create_short_result_relative_path_to_name_paths() -> str:
            by_path: defaultdict[str, list[str]] = defaultdict(list)
            for item in matches:
                by_path[str(item.get("relative_path") or "unknown")].append(str(item.get("name_path") or "unknown"))
            return f"Shortened result:\n{self._to_json(by_path)}"
        if 0 < max_matches < n_matches:
            return f"Matched {n_matches}>{max_matches=} symbols.\n" + create_short_result_relative_path_to_name_paths()
        grouped = self.symbol_dict_grouper.group(matches)
        return self._limit_length(self._to_json(grouped), max_answer_chars, shortened_result_factories=[create_short_result_relative_path_to_name_paths])

    @classmethod
    def get_param_aliases(cls) -> dict[str, str]:
        return {"name_path": "name_path_pattern"}
''')
symbol = replace_class(symbol, "FindReferencingSymbolsTool", '''
class FindReferencingSymbolsTool(Tool, ToolMarkerSymbolicRead):
    """Finds references through Code Intelligence MCP."""

    symbol_dict_grouper = LanguageServerSymbolDictGrouper(["relative_path", "kind"], ["kind"], collapse_singleton=True)

    def apply(self, name_path: str, relative_path: str, include_kinds: list[int] = [], exclude_kinds: list[int] = [],
              max_answer_chars: int = -1) -> str:  # noqa: B006
        """Find references through intellij-mcp ``find_references`` using a Serena name path as the target."""
        self.project.validate_relative_path(relative_path)
        client = IntellijMcpClient(self.get_project_root())
        finder = FindSymbolTool(self.agent)
        candidates, candidate_paths = finder._search(client, name_path, relative_path, False)
        if not candidates:
            raise ValueError(f"No symbol matching {name_path!r} found in {relative_path!r} through Code Intelligence MCP")
        if len(candidates) > 1:
            exact_indices = [i for i, candidate_path in enumerate(candidate_paths) if candidate_path == name_path]
            if len(exact_indices) == 1:
                i = exact_indices[0]
                candidates = [candidates[i]]
                candidate_paths = [candidate_paths[i]]
            else:
                summaries = []
                for raw, candidate_path in zip(candidates, candidate_paths, strict=True):
                    location = raw.get("nameLocation") or raw.get("location") or {}
                    summaries.append({"name_path": candidate_path, "kind": finder._kind_name(raw),
                                      "relative_path": finder._relative_file(client, raw), "line": location.get("line")})
                raise ValueError(f"Found multiple {len(candidates)} symbols matching {name_path!r}. They are:\n" + self._to_json(summaries))

        target = candidates[0]
        location = target.get("nameLocation") or target.get("location") or {}
        refs = client.call_tool("find_references", {
            "filePath": str(location.get("filePath") or client.absolute_file_path(relative_path)),
            "line": int(location.get("line") or 1),
            "column": int(location.get("column") or 1),
        })
        locations = [item for item in refs if isinstance(item, dict)] if isinstance(refs, list) else []
        reference_dicts: list[dict[str, Any]] = []
        for usage in locations:
            ref_path = client.relative_file_path(str(usage.get("filePath") or ""))
            line_1 = int(usage.get("line") or 1)
            reference_dicts.append({
                "name_path": f"reference@{line_1}", "kind": "Reference", "relative_path": ref_path,
                "body_location": {"start_line": max(0, line_1 - 1), "end_line": max(0, int(usage.get("endLine") or line_1) - 1)},
                "content_around_reference": str(usage.get("preview") or ""), "reference_line": max(0, line_1 - 1),
            })
        ref_summaries = [{"name_path": d["name_path"], "kind": d["kind"], "relative_path": d["relative_path"],
                          "reference_line": d["reference_line"]} for d in reference_dicts]
        result = self.symbol_dict_grouper.group(reference_dicts)
        def make_refs_without_context() -> str:
            return f"References without surrounding lines:\n{self._to_json(self.symbol_dict_grouper.group(copy.deepcopy(ref_summaries)))}"
        def make_per_file_counts() -> str:
            return f"Reference counts per file:\n{self._to_json(Counter(str(r['relative_path']) for r in ref_summaries))}"
        def make_summary() -> str:
            return f"Found {len(ref_summaries)} references."
        return self._limit_length(self._to_json(result), max_answer_chars,
                                  shortened_result_factories=[make_refs_without_context, make_per_file_counts, make_summary])
''')
symbol_path.write_text(symbol, encoding="utf-8")

file_tools_path = ROOT / "src/serena/tools/file_tools.py"
file_tools = file_tools_path.read_text(encoding="utf-8")
upstream_url = "https://raw.githubusercontent.com/oraios/serena/main/src/serena/tools/file_tools.py"
upstream = urlopen(upstream_url, timeout=30).read().decode("utf-8")
file_tools = file_tools.replace("from serena.index_mcp_client import IndexMcpClient\n", "")
file_tools = replace_class(file_tools, "FindFileTool", class_block(upstream, "FindFileTool"))
file_tools = replace_class(file_tools, "SearchForPatternTool", class_block(upstream, "SearchForPatternTool"))
file_tools_path.write_text(file_tools, encoding="utf-8")

init_path = ROOT / "src/serena/tools/__init__.py"
init_text = init_path.read_text(encoding="utf-8")
init_text = init_text.replace("from .index_mcp_ui_tools import *\n", "from .intellij_mcp_tools import *\n")
init_path.write_text(init_text, encoding="utf-8")

for obsolete in [ROOT / "src/serena/index_mcp_client.py", ROOT / "src/serena/tools/index_mcp_ui_tools.py"]:
    if obsolete.exists():
        obsolete.unlink()
