"""
Language server-related tools
"""

import copy
import os
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from serena.index_mcp_client import IndexMcpClient, find_structure_node, parse_file_structure_tree
from serena.symbol import LanguageServerSymbol, LanguageServerSymbolDictGrouper
from serena.tools import (
    SUCCESS_RESULT,
    EditingToolWithDiagnostics,
    Tool,
    ToolMarkerSymbolicEdit,
    ToolMarkerSymbolicRead,
)
from serena.tools.tools_base import ToolMarkerOptional
from serena.util.ls_diagnostics import GroupedDiagnostics
from serena.util.text_utils import find_text_coordinates
from solidlsp.ls_types import SymbolKind


class RestartLanguageServerTool(Tool, ToolMarkerOptional):
    """Restarts the language server(s)."""

    def apply(self) -> str:
        """Use this tool only on explicit user request or after confirmation.
        It may be necessary to restart the language server if it hangs.
        """
        self.agent.reset_language_server_manager()
        return SUCCESS_RESULT


class GetSymbolsOverviewTool(Tool, ToolMarkerSymbolicRead):
    """Gets an overview of symbols using the JetBrains Index MCP backend."""

    symbol_dict_grouper = LanguageServerSymbolDictGrouper(["kind"], ["kind"], collapse_singleton=True)

    def apply(self, relative_path: str, depth: int = -1, max_answer_chars: int = -1) -> str:
        """
        Gets a high-level view of the symbols defined in a file using ``ide_file_structure``
        from the Index MCP server.

        :param relative_path: relative path to the file to inspect
        :param depth: descendant depth to include; -1 chooses 1 for Java/Kotlin and 0 otherwise
        :param max_answer_chars: max result length; -1 uses Serena's configured default
        :return: a JSON object containing symbols grouped by kind in Serena-compatible format
        """
        self.project.validate_relative_path(relative_path)
        if depth == -1:
            depth = 1 if relative_path.endswith((".java", ".kt")) else 0

        client = IndexMcpClient(self.get_project_root())
        payload = client.call_file_structure(relative_path)
        if payload is None:
            return self._to_json({})
        structure = str(payload.get("structure", ""))
        nodes = parse_file_structure_tree(structure)

        def to_symbol(node: dict[str, Any], remaining_depth: int) -> dict[str, Any]:
            result: dict[str, Any] = {"name": node["name"], "kind": node["kind"]}
            if remaining_depth > 0:
                children = [to_symbol(child, remaining_depth - 1) for child in node.get("children", [])]
                if children:
                    result["children"] = children
            return result

        symbol_dicts = [to_symbol(node, depth) for node in nodes]
        compact_result = self.symbol_dict_grouper.group(symbol_dicts)
        result_json = self._to_json(compact_result)

        def make_kind_counts() -> str:
            return f"Symbol counts by kind:\n{self._to_json(Counter(d.get('kind', 'unknown') for d in symbol_dicts))}"

        return self._limit_length(result_json, max_answer_chars, shortened_result_factories=[make_kind_counts])

    def get_symbol_overview(self, relative_path: str, depth: int = 0) -> list[dict[str, Any]]:
        """Compatibility helper used by callers that expect ungrouped overview dictionaries."""
        self.project.validate_relative_path(relative_path)
        client = IndexMcpClient(self.get_project_root())
        payload = client.call_file_structure(relative_path)
        if payload is None:
            return []
        nodes = parse_file_structure_tree(str(payload.get("structure", "")))

        def convert(node: dict[str, Any], remaining_depth: int) -> dict[str, Any]:
            out: dict[str, Any] = {"name": node["name"], "kind": node["kind"]}
            if remaining_depth > 0:
                children = [convert(child, remaining_depth - 1) for child in node.get("children", [])]
                if children:
                    out["children"] = children
            return out

        return [convert(node, depth) for node in nodes]


class FindSymbolTool(Tool, ToolMarkerSymbolicRead):
    """Searches symbols through the JetBrains Index MCP server."""

    symbol_dict_grouper = LanguageServerSymbolDictGrouper([], ["kind"], collapse_singleton=True)

    _INDEX_TO_LSP_KIND = {
        "FILE": "File", "MODULE": "Module", "NAMESPACE": "Namespace", "PACKAGE": "Package",
        "CLASS": "Class", "METHOD": "Method", "PROPERTY": "Property", "FIELD": "Field",
        "CONSTRUCTOR": "Constructor", "ENUM": "Enum", "INTERFACE": "Interface", "FUNCTION": "Function",
        "VARIABLE": "Variable", "CONSTANT": "Constant", "STRING": "String", "NUMBER": "Number",
        "BOOLEAN": "Boolean", "ARRAY": "Array", "OBJECT": "Object", "KEY": "Key", "NULL": "Null",
        "ENUM_MEMBER": "EnumMember", "ENUM_CASE": "EnumMember", "STRUCT": "Struct", "EVENT": "Event",
        "OPERATOR": "Operator", "TYPE_PARAMETER": "TypeParameter", "RECORD": "Struct", "TRAIT": "Interface",
        "IMPL": "Class", "SYMBOL": "Object",
    }

    @staticmethod
    def _name_path(symbol: dict[str, Any]) -> str:
        name = str(symbol.get("name") or "unknown")
        kind = str(symbol.get("kind") or "").upper()
        container = str(symbol.get("containerName") or "").strip()
        if kind in {"METHOD", "FIELD", "PROPERTY", "CONSTRUCTOR", "ENUM_MEMBER", "ENUM_CASE"} and container:
            container = container.replace("::", ".").split(".")[-1]
            return f"{container}/{name}"
        return name

    @classmethod
    def _kind_name(cls, symbol: dict[str, Any]) -> str:
        raw = str(symbol.get("kind") or "Object").upper().replace(" ", "_")
        return cls._INDEX_TO_LSP_KIND.get(raw, raw.title().replace("_", ""))

    @staticmethod
    def _path_matches(relative_path: str, candidate: str) -> bool:
        if not relative_path:
            return True
        wanted = relative_path.strip("/\\")
        candidate_norm = candidate.replace("\\", "/").strip("/")
        wanted_norm = wanted.replace("\\", "/")
        return candidate_norm == wanted_norm or candidate_norm.startswith(wanted_norm.rstrip("/") + "/")

    @staticmethod
    def _split_overload(component: str) -> tuple[str, int | None]:
        if component.endswith("]") and "[" in component:
            base, _, suffix = component.rpartition("[")
            index_text = suffix[:-1]
            if index_text.isdigit():
                return base, int(index_text)
        return component, None

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
    def _name_paths_with_overloads(cls, symbols: list[dict[str, Any]]) -> list[str]:
        """Add Serena-style ``[i]`` suffixes to overloaded callables in a stable order."""
        paths = [cls._name_path(symbol) for symbol in symbols]
        groups: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
        callable_kinds = {"METHOD", "FUNCTION", "CONSTRUCTOR", "OPERATOR"}
        for i, (symbol, path) in enumerate(zip(symbols, paths, strict=True)):
            if str(symbol.get("kind") or "").upper() in callable_kinds:
                groups[(str(symbol.get("file") or ""), path)].append(i)
        for (_, base_path), indices in groups.items():
            if len(indices) <= 1:
                continue
            indices.sort(
                key=lambda i: (
                    int(symbols[i].get("line") or 1),
                    int(symbols[i].get("column") or 1),
                    str(symbols[i].get("qualifiedName") or ""),
                )
            )
            for overload_index, i in enumerate(indices):
                paths[i] = f"{base_path}[{overload_index}]"
        return paths

    def _structure_for_file(self, client: IndexMcpClient, relative_path: str) -> list[dict[str, Any]]:
        payload = client.call_file_structure(relative_path)
        if payload is None:
            return []
        return parse_file_structure_tree(str(payload.get("structure", "")))

    def apply(
        self,
        name_path_pattern: str,
        depth: int = 0,
        relative_path: str = "",
        include_body: bool = False,
        include_info: bool = False,
        include_kinds: list[int] = [],  # noqa: B006
        exclude_kinds: list[int] = [],  # noqa: B006
        substring_matching: bool = False,
        max_matches: int = -1,
        max_answer_chars: int = -1,
    ) -> str:
        """
        Finds symbols and code entities via the JetBrains ``ide_find_symbol`` Index MCP tool while
        retaining Serena's public parameters and result shape.

        :param name_path_pattern: Serena name-path pattern, e.g. ``MyClass/my_method``
        :param depth: descendant depth to include when file structure is available
        :param relative_path: optional file/directory restriction
        :param include_body: include source text for the matched structure node when available
        :param include_info: include Index MCP qualified-name/language/location metadata
        :param include_kinds: optional LSP symbol-kind integers to include
        :param exclude_kinds: optional LSP symbol-kind integers to exclude
        :param substring_matching: substring-match the final name-path component
        :param max_matches: maximum permitted matches; -1 means no Serena-level limit
        :param max_answer_chars: max result length; -1 uses Serena's configured default
        :return: Serena-compatible symbol dictionaries backed by the Index MCP search index
        """
        if not name_path_pattern:
            raise ValueError("name_path_pattern must not be empty")
        if max_matches == 0:
            raise ValueError("max_matches must be > 0 or equal to -1")
        if relative_path:
            self.project.validate_relative_path(relative_path)

        query = name_path_pattern.strip("/").replace("/", ".")
        # Overload suffixes are Serena-specific and are not understood by IntelliJ Go to Symbol.
        if query.endswith("]") and "[" in query.rsplit(".", 1)[-1]:
            last = query.rsplit(".", 1)[-1]
            query = query[: -len(last)] + last.rsplit("[", 1)[0]

        client = IndexMcpClient(self.get_project_root())
        # Local name-path/path/kind filtering can discard early fuzzy matches, so collect the
        # complete indexed result set (up to the client's defensive ceiling) before enforcing
        # Serena's max_matches semantics.
        page = client.call_paginated_tool("ide_find_symbol", {"query": query}, "symbols")

        include_kind_names = {SymbolKind(k).name.lower() for k in include_kinds} if include_kinds else None
        exclude_kind_names = {SymbolKind(k).name.lower() for k in exclude_kinds} if exclude_kinds else set()
        matches: list[dict[str, Any]] = []

        structure_cache: dict[str, list[dict[str, Any]]] = {}
        indexed_name_paths = self._name_paths_with_overloads(page.items)
        for raw, name_path in zip(page.items, indexed_name_paths, strict=True):
            file = str(raw.get("file") or "")
            if not self._path_matches(relative_path, file):
                continue
            if not self._name_path_matches(name_path_pattern, name_path, substring_matching):
                continue
            kind_name = self._kind_name(raw)
            if include_kind_names is not None and kind_name.lower() not in include_kind_names:
                continue
            if kind_name.lower() in exclude_kind_names:
                continue

            line_1 = int(raw.get("line") or 1)
            out: dict[str, Any] = {
                "name_path": name_path,
                "kind": kind_name,
                "relative_path": file,
                "body_location": {"start_line": max(0, line_1 - 1), "end_line": max(0, line_1 - 1)},
            }

            node: dict[str, Any] | None = None
            if depth > 0 or include_body:
                if file not in structure_cache:
                    structure_cache[file] = self._structure_for_file(client, file)
                node = find_structure_node(structure_cache[file], line=line_1, name=str(raw.get("name") or ""))
                if node is not None:
                    out["body_location"] = {
                        "start_line": max(0, int(node["start_line"]) - 1),
                        "end_line": max(0, int(node["end_line"]) - 1),
                    }

            if include_body:
                start = int(out["body_location"]["start_line"])
                end = int(out["body_location"]["end_line"])
                try:
                    lines = self.project.read_file(file).splitlines()
                    out["body"] = "\n".join(lines[start : end + 1])
                except Exception:
                    out["body"] = ""
            elif include_info:
                qname = raw.get("qualifiedName") or raw.get("name")
                language = raw.get("language")
                out["info"] = f"{kind_name} {qname} ({language or 'unknown language'}) at {file}:{line_1}:{raw.get('column', 1)}"

            if depth > 0 and node is not None:
                def convert_child(child: dict[str, Any], remaining: int) -> dict[str, Any]:
                    child_out: dict[str, Any] = {"name": child["name"], "kind": child["kind"]}
                    if remaining > 1:
                        grandchildren = [convert_child(c, remaining - 1) for c in child.get("children", [])]
                        if grandchildren:
                            child_out["children"] = grandchildren
                    return child_out

                children = [convert_child(child, depth) for child in node.get("children", [])]
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
        result = self._to_json(grouped)
        return self._limit_length(result, max_answer_chars, shortened_result_factories=[create_short_result_relative_path_to_name_paths])

    @classmethod
    def get_param_aliases(cls) -> dict[str, str]:
        return {"name_path": "name_path_pattern"}


class FindReferencingSymbolsTool(Tool, ToolMarkerSymbolicRead):
    """Finds references through the JetBrains Index MCP server."""

    symbol_dict_grouper = LanguageServerSymbolDictGrouper(["relative_path", "kind"], ["kind"], collapse_singleton=True)

    def apply(
        self,
        name_path: str,
        relative_path: str,
        include_kinds: list[int] = [],  # noqa: B006
        exclude_kinds: list[int] = [],  # noqa: B006
        max_answer_chars: int = -1,
    ) -> str:
        """
        Finds references to a symbol through ``ide_find_references``. The target position is resolved
        using ``ide_find_symbol`` so Serena callers can keep passing ``name_path`` + ``relative_path``.

        :param name_path: Serena name path of the target symbol
        :param relative_path: file containing the target symbol
        :param include_kinds: retained for API compatibility; Index MCP references do not expose enclosing LSP kinds
        :param exclude_kinds: retained for API compatibility; Index MCP references do not expose enclosing LSP kinds
        :param max_answer_chars: max result length; -1 uses Serena's configured default
        :return: Serena-compatible reference entries grouped by file/kind
        """
        self.project.validate_relative_path(relative_path)
        client = IndexMcpClient(self.get_project_root())

        query = name_path.strip("/").replace("/", ".")
        if query.endswith("]") and "[" in query.rsplit(".", 1)[-1]:
            last = query.rsplit(".", 1)[-1]
            query = query[: -len(last)] + last.rsplit("[", 1)[0]
        search = client.call_paginated_tool("ide_find_symbol", {"query": query}, "symbols")
        finder = FindSymbolTool(self.agent)
        indexed_paths = finder._name_paths_with_overloads(search.items)
        candidate_pairs = [
            (raw, indexed_path)
            for raw, indexed_path in zip(search.items, indexed_paths, strict=True)
            if finder._path_matches(relative_path, str(raw.get("file") or ""))
            and finder._name_path_matches(name_path, indexed_path, False)
        ]
        if not candidate_pairs:
            # Relax to the final component; qualified popup naming varies by language.
            target_name, target_overload = finder._split_overload(name_path.strip("/").split("/")[-1])
            candidate_pairs = [
                (raw, indexed_path)
                for raw, indexed_path in zip(search.items, indexed_paths, strict=True)
                if finder._path_matches(relative_path, str(raw.get("file") or ""))
                and str(raw.get("name") or "") == target_name
                and (target_overload is None or finder._split_overload(indexed_path.split("/")[-1])[1] == target_overload)
            ]
        if not candidate_pairs:
            raise ValueError(f"No symbol matching {name_path!r} found in {relative_path!r} through Index MCP")
        if len(candidate_pairs) > 1:
            exact = [(raw, path) for raw, path in candidate_pairs if path == name_path]
            if len(exact) == 1:
                candidate_pairs = exact
            else:
                summaries = [
                    {
                        "name_path": path,
                        "kind": finder._kind_name(raw),
                        "relative_path": raw.get("file"),
                        "line": raw.get("line"),
                    }
                    for raw, path in candidate_pairs
                ]
                raise ValueError(
                    f"Found multiple {len(candidate_pairs)} symbols matching {name_path!r}. They are: \n"
                    + json.dumps(summaries, indent=2)
                )

        target = candidate_pairs[0][0]
        refs = client.call_paginated_tool(
            "ide_find_references",
            {
                "file": relative_path,
                "line": int(target.get("line") or 1),
                "column": int(target.get("column") or 1),
            },
            "usages",
        )

        reference_dicts: list[dict[str, Any]] = []
        for usage in refs.items:
            ref_path = str(usage.get("file") or "")
            line_1 = int(usage.get("line") or 1)
            ast_path = usage.get("astPath")
            if isinstance(ast_path, list) and ast_path:
                ref_name_path = "/".join(str(part) for part in ast_path)
            else:
                ref_name_path = f"reference@{line_1}"
            context = str(usage.get("context") or "")
            reference_dicts.append(
                {
                    "name_path": ref_name_path,
                    "kind": "Reference",
                    "relative_path": ref_path,
                    "body_location": {"start_line": max(0, line_1 - 1), "end_line": max(0, line_1 - 1)},
                    "content_around_reference": context,
                    "reference_line": max(0, line_1 - 1),
                }
            )

        ref_summaries = [
            {
                "name_path": d["name_path"],
                "kind": d["kind"],
                "relative_path": d["relative_path"],
                "reference_line": d["reference_line"],
            }
            for d in reference_dicts
        ]
        result = self.symbol_dict_grouper.group(reference_dicts)

        def make_refs_without_context() -> str:
            grouped = self.symbol_dict_grouper.group(copy.deepcopy(ref_summaries))
            return f"References without surrounding lines:\n{self._to_json(grouped)}"

        def make_per_file_counts() -> str:
            counts = Counter(str(r["relative_path"]) for r in ref_summaries)
            return f"Reference counts per file:\n{self._to_json(counts)}"

        def make_summary() -> str:
            suffix = " (truncated by Index MCP pagination ceiling)" if refs.truncated else ""
            return f"Found {len(ref_summaries)} references{suffix}."

        return self._limit_length(
            self._to_json(result),
            max_answer_chars,
            shortened_result_factories=[make_refs_without_context, make_per_file_counts, make_summary],
        )


class FindImplementationsTool(Tool, ToolMarkerSymbolicRead):
    """
    Finds symbols that implement the given symbol using the language server backend.
    """

    # noinspection PyDefaultArgument
    def apply(
        self,
        name_path: str,
        relative_path: str,
        include_info: bool = False,
        include_kinds: list[int] = [],  # noqa: B006
        exclude_kinds: list[int] = [],  # noqa: B006
        max_answer_chars: int = -1,
    ) -> str:
        """
        Finds implementations of the symbol at the given `name_path`.

        :param name_path: the symbol's name path
        :param relative_path: the relative path to the file containing the symbol for which to find implementations.
            Note that here you can't pass a directory but must pass a file.
        :param include_info: whether to include additional info (hover-like, typically including docstring and signature),
            about the implementing symbols.
        :param include_kinds: (optional) limits results to the given LSP symbol kinds (integers)
        :param exclude_kinds: (optional) list of LSP symbol kinds (integers) to exclude.
        :param max_answer_chars: max result length; -1 for default
        :return: a list of JSON objects with the symbols implementing the requested symbol
        """
        self.project.ls_sync_file_system_changes()

        include_body = False
        parsed_include_kinds: Sequence[SymbolKind] | None = [SymbolKind(k) for k in include_kinds] if include_kinds else None
        parsed_exclude_kinds: Sequence[SymbolKind] | None = [SymbolKind(k) for k in exclude_kinds] if exclude_kinds else None
        symbol_retriever = self.create_language_server_symbol_retriever()

        implementing_symbols = symbol_retriever.find_implementing_symbols(
            name_path,
            relative_file_path=relative_path,
            include_body=include_body,
            include_kinds=parsed_include_kinds,
            exclude_kinds=parsed_exclude_kinds,
        )

        symbol_dicts = [
            dict(s.to_dict(kind=True, relative_path=True, depth=0, body=include_body, body_location=True)) for s in implementing_symbols
        ]
        if include_info:
            info_by_symbol = symbol_retriever.request_info_for_symbol_batch(implementing_symbols)
            for s, s_dict in zip(implementing_symbols, symbol_dicts, strict=True):
                if symbol_info := info_by_symbol.get(s):
                    s_dict["info"] = symbol_info
                    s_dict.pop("name", None)  # name is included in the info

        result = self._to_json(symbol_dicts)
        return self._limit_length(result, max_answer_chars)


class FindDeclarationTool(Tool, ToolMarkerSymbolicRead):
    """
    Finds the declaration/definition of a symbol
    """

    def apply(
        self,
        relative_path: str,
        regex: str,
        containing_symbol_name_path: str | None = None,
        include_body: bool = False,
        include_info: bool = False,
    ) -> str:
        r"""
        Finds the declaration of a symbol.

        :param relative_path: the relative path to the source file containing the symbol for which to find the declaration.
        :param regex: a regular expression with one group, where the group matches the symbol for which to perform the lookup.
            For example, to find the declaration of the `process` method in a call like `obj.process()`,
            pass an expression like "obj\.(process)\(process_input_arg=37\)".
            Prefer regexes with sufficiently large context around the group to render the match unambiguous.
            Uses Python syntax with MULTILINE and DOTALL flags enabled.
        :param containing_symbol_name_path: optional name path of a containing symbol whose body shall be searched instead of the full file.
        :param include_body: whether to include the symbol's body in the result. Default False.
        :param include_info: whether to include additional info (hover-like). Default False.
        """
        self.project.ls_sync_file_system_changes()

        symbol_retriever = self.create_language_server_symbol_retriever()
        relative_path = self._sanitize_input_param(relative_path)
        regex = self._sanitize_input_param(regex)

        # find relevant location for lookup
        editor = self.create_code_editor()
        if not containing_symbol_name_path:
            content = editor.read_file(relative_path)
            coords = find_text_coordinates(content, regex, require_unique=True)
            assert coords is not None
        else:
            symbol = symbol_retriever.find_unique(name_path_pattern=containing_symbol_name_path, within_relative_path=relative_path)
            body_line_numers = symbol.get_body_line_numbers_or_raise()
            content = editor.read_file(relative_path, lines=body_line_numers)
            coords = find_text_coordinates(content, regex, require_unique=True)
            assert coords is not None
            coords.line += body_line_numers[0]

        # retrieve declaration
        defining_symbol = symbol_retriever.find_declaration(
            relative_file_path=relative_path,
            line=coords.line,
            column=coords.col,
            include_body=include_body,
        )
        if defining_symbol is None:
            raise ValueError(
                f"No symbol declaration found at the location of the regex match. Location: {relative_path}:{coords.line}:{coords.col}."
            )

        # create output
        symbol_dict = self._defining_symbol_to_result_dict(
            symbol_retriever,
            defining_symbol,
            include_body,
            include_info,
        )
        result = self._to_json(symbol_dict)
        return result

    @staticmethod
    def _defining_symbol_to_result_dict(
        symbol_retriever: Any,
        defining_symbol: LanguageServerSymbol,
        include_body: bool,
        include_info: bool,
    ) -> dict[str, Any]:
        symbol_dict = dict(defining_symbol.to_dict(kind=True, relative_path=True, depth=0, body=include_body, body_location=True))
        if not include_body and include_info:
            if symbol_info := symbol_retriever.request_info_for_symbol(defining_symbol):
                symbol_dict["info"] = symbol_info
                symbol_dict.pop("name", None)
        return symbol_dict


class GetDiagnosticsForFileTool(Tool, ToolMarkerSymbolicRead):
    """
    Gets diagnostics for a file, optionally restricted to a line range, grouped by file, severity, and containing symbol.
    """

    FILE_LEVEL_DIAGNOSTIC_BUCKET = "<file>"

    def apply(
        self,
        relative_path: str,
        start_line: int = 0,
        end_line: int = -1,
        min_severity: int = 4,
        max_answer_chars: int = -1,
    ) -> str:
        """
        Gets diagnostics for a file. Diagnostics are grouped as `relative_path -> severity -> name_path -> diagnostics_results`.
        If a diagnostic cannot be mapped to a symbol, it is grouped under the special name path `<file>`.

        :param relative_path: the relative path to the file to inspect.
        :param start_line: the first 0-based line to include. Defaults to 0.
        :param end_line: the last 0-based line to include. Defaults to -1, which means until the end of the file.
        :param min_severity: minimum LSP severity to include, where 1=Error, 2=Warning, 3=Information, 4=Hint.
            Diagnostics with lower-or-equal numeric severity are returned.
        :param max_answer_chars: max result length; -1 for default
        :return: grouped diagnostics for the requested file.
        """
        self.project.ls_sync_file_system_changes()

        symbol_retriever = self.create_language_server_symbol_retriever()
        diagnostics = symbol_retriever.get_file_diagnostics(
            relative_file_path=relative_path,
            start_line=start_line,
            end_line=end_line,
            min_severity=min_severity,
        )

        grouped_diagnostics = GroupedDiagnostics()
        for diagnostic in diagnostics:
            diag_range = diagnostic["range"]["start"]
            name_path = self.FILE_LEVEL_DIAGNOSTIC_BUCKET
            owner_symbol = symbol_retriever.find_diagnostic_owner_symbol(
                relative_file_path=relative_path,
                line=diag_range["line"],
                column=diag_range["character"],
            )
            if owner_symbol is not None:
                name_path = owner_symbol.get_name_path()
            grouped_diagnostics.add(relative_path, name_path, diagnostic)

        result = self._to_json(grouped_diagnostics.get_dict())
        return self._limit_length(result, max_answer_chars)


class GetDiagnosticsForSymbolTool(Tool, ToolMarkerSymbolicRead, ToolMarkerOptional):
    """
    Gets diagnostics for a symbol and, optionally, for symbols that reference it.
    """

    def apply(
        self,
        name_path: str,
        reference_file: str = "",
        check_symbol_references: bool = False,
        min_severity: int = 4,
        max_answer_chars: int = -1,
    ) -> str:
        """
        Gets diagnostics for the specified symbol. When `check_symbol_references` is true, diagnostics for all
        referencing symbols are also included. The result is grouped as
        `relative_path -> severity -> name_path -> diagnostics_results`.

        :param name_path: the name path of the symbol to inspect.
        :param reference_file: optional file path used to disambiguate the symbol search.
        :param check_symbol_references: whether to additionally collect diagnostics for symbols that reference the symbol.
        :param min_severity: minimum LSP severity to include, where 1=Error, 2=Warning, 3=Information, 4=Hint.
            Diagnostics with lower-or-equal numeric severity are returned.
        :param max_answer_chars: max result length; -1 for default
        :return: grouped diagnostics for the requested symbol and, optionally, its referencing symbols.
        """
        self.project.ls_sync_file_system_changes()

        symbol_retriever = self.create_language_server_symbol_retriever()
        diagnostics_by_symbol = symbol_retriever.get_symbol_diagnostics(
            name_path=name_path,
            reference_file=reference_file or None,
            check_symbol_references=check_symbol_references,
            min_severity=min_severity,
        )

        grouped_diagnostics = GroupedDiagnostics()
        for symbol, diagnostics in diagnostics_by_symbol.items():
            relative_path = symbol.relative_path
            if relative_path is None:
                continue
            symbol_name_path = symbol.get_name_path()
            for diagnostic in diagnostics:
                grouped_diagnostics.add(relative_path, symbol_name_path, diagnostic)

        result = self._to_json(grouped_diagnostics.get_dict())
        return self._limit_length(result, max_answer_chars)


class ReplaceSymbolBodyTool(EditingToolWithDiagnostics):
    """
    Replaces the full definition of a symbol using the language server backend.
    """

    def apply(
        self,
        name_path: str,
        relative_path: str,
        body: str,
    ) -> str:
        r"""
        Replaces the body of the given symbol.

        IMPORTANT: Only replace symbol bodies if you have previously made a retrieval with include_body=True and thus know what
        constitutes the body!

        :param name_path: name path of the symbol whose body to replace
        :param relative_path: the relative path to the file containing the symbol
        :param body: the new symbol body. The symbol body is the definition of a symbol
            in the programming language, including e.g. the signature line for functions.
            Depending on the language, it may or may not include a preceding docstring or other preceding annotations.
        """
        with self.DiagnosticsContext(self, relative_path) as diagnostics_context:
            code_editor = self.create_code_editor()
            code_editor.replace_body(
                name_path,
                relative_file_path=relative_path,
                body=body,
            )
            return diagnostics_context.format_result(SUCCESS_RESULT)


class InsertAfterSymbolTool(EditingToolWithDiagnostics):
    """
    Inserts content after the end of the definition of a given symbol.
    """

    def apply(
        self,
        name_path: str,
        relative_path: str,
        body: str,
    ) -> str:
        """
        Use this to insert code after a class/method/function definition.
        Don't use to insert after assignments (constants, fields).

        :param name_path: name path of the symbol after which to insert content
        :param relative_path: the relative path to the file containing the symbol
        :param body: the body/content to be inserted. The inserted code shall begin with the next line after
            the symbol.
        """
        with self.DiagnosticsContext(self, relative_path) as diagnostics_context:
            code_editor = self.create_code_editor()
            code_editor.insert_after_symbol(name_path, relative_file_path=relative_path, body=body)
            return diagnostics_context.format_result(SUCCESS_RESULT)


class InsertBeforeSymbolTool(EditingToolWithDiagnostics):
    """
    Inserts content before the beginning of the definition of a given symbol.
    """

    def apply(
        self,
        name_path: str,
        relative_path: str,
        body: str,
    ) -> str:
        """
        Inserts the given content before the beginning of the definition of the given symbol (via the symbol's location).
        A typical use case is to insert a new class, function, method, field or variable assignment; or
        a new import statement before the first symbol in the file.

        :param name_path: name path of the symbol before which to insert content
        :param relative_path: the relative path to the file containing the symbol
        :param body: the body/content to be inserted before the line in which the referenced symbol is defined
        """
        with self.DiagnosticsContext(self, relative_path) as diagnostics_context:
            code_editor = self.create_code_editor()
            code_editor.insert_before_symbol(name_path, relative_file_path=relative_path, body=body)
            return diagnostics_context.format_result(SUCCESS_RESULT)


class RenameSymbolTool(Tool, ToolMarkerSymbolicEdit):
    """
    Renames a symbol throughout the codebase using language server refactoring capabilities.
    For JB, we use a separate tool.
    """

    def apply(
        self,
        name_path: str,
        relative_path: str,
        new_name: str,
    ) -> str:
        """
        Renames the symbol with the given `name_path` to `new_name` throughout the entire codebase.
        Note: for languages with method overloading, like Java, name_path may have to include a method's
        signature to uniquely identify a method.

        :param name_path: name path of the symbol to rename
        :param relative_path: the relative path to the file containing the symbol to rename
        :param new_name: the new name for the symbol
        :return: result summary indicating success or failure
        """
        self.project.ls_sync_file_system_changes()
        code_editor = self.create_ls_code_editor()
        status_message = code_editor.rename_symbol(name_path, relative_path=relative_path, new_name=new_name)
        return status_message


class SafeDeleteSymbol(Tool, ToolMarkerSymbolicEdit):
    def apply(
        self,
        name_path_pattern: str,
        relative_path: str,
    ) -> str:
        """
        Deletes the symbol if it is safe to do so (i.e., if there are no references to it)
        or returns a list of references to it.

        :param name_path_pattern: name path of the symbol to delete
        :param relative_path: the relative path to the file containing the symbol to delete
        """
        self.project.ls_sync_file_system_changes()

        ls_symbol_retriever = self.create_language_server_symbol_retriever()
        symbol = ls_symbol_retriever.find_unique(name_path_pattern, substring_matching=False, within_relative_path=relative_path)
        symbol_rel_path = symbol.relative_path
        assert symbol_rel_path is not None, f"Symbol {name_path_pattern} has no relative path, this is likely a bug."
        assert symbol_rel_path == relative_path, f"Symbol {name_path_pattern} is not in the expected relative path {relative_path}."
        symbol_name_path = symbol.get_name_path()

        symbol_line = symbol.line
        symbol_col = symbol.column
        assert symbol_line is not None and symbol_col is not None, (
            f"Symbol {name_path_pattern} has no identifier position, this is likely a bug."
        )
        lang_server = ls_symbol_retriever.get_language_server(symbol_rel_path)
        references_locations = lang_server.request_references(symbol_rel_path, symbol_line, symbol_col)
        file_to_lines: dict[str, list[int]] = defaultdict(list)
        if references_locations:
            for ref_loc in references_locations:
                ref_relative_path = ref_loc.get("relativePath")
                if ref_relative_path is None:
                    continue
                file_to_lines[ref_relative_path].append(ref_loc["range"]["start"]["line"])
        if file_to_lines:
            return f"Cannot delete, the symbol {symbol_name_path} is referenced in: {self._to_json(file_to_lines)}"
        code_editor = self.create_ls_code_editor()
        code_editor.delete_symbol(symbol_name_path, relative_file_path=symbol_rel_path)
        return SUCCESS_RESULT
