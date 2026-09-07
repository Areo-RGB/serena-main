"""Index MCP language-backend tool implementations.

These tools adapt Serena's public semantics to the JetBrains Index MCP server while
keeping the generic LSP tools independent. They are selected only when
LanguageBackend.INDEX_MCP is active.
"""

import os
from collections import Counter, defaultdict
from collections.abc import Sequence
from fnmatch import fnmatch
from typing import Any

from serena.index_mcp_client import IndexMcpClient, find_structure_node, parse_file_structure_tree
from serena.symbol import LanguageServerSymbol, LanguageServerSymbolDictGrouper
from serena.tools.tools_base import Tool, ToolMarkerOptional, ToolMarkerSymbolicRead
from serena.util.text_utils import GlobMatcher
from solidlsp.ls_types import SymbolKind

class IndexMcpGetSymbolsOverviewTool(Tool, ToolMarkerSymbolicRead, ToolMarkerOptional):
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

class IndexMcpFindSymbolTool(Tool, ToolMarkerSymbolicRead, ToolMarkerOptional):
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

class IndexMcpFindReferencingSymbolsTool(Tool, ToolMarkerSymbolicRead, ToolMarkerOptional):
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
        finder = IndexMcpFindSymbolTool(self.agent)
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

class IndexMcpFindFileTool(Tool, ToolMarkerOptional):
    """Finds files through the JetBrains Index MCP file index."""

    def apply(self, file_mask: str, relative_path: str) -> str:
        """
        Finds files matching a filename/mask using ``ide_find_file`` and then applies Serena's
        relative-path restriction locally.

        :param file_mask: filename or wildcard mask (``*``/``?``) to search for
        :param relative_path: directory to search under; pass ``.`` for the project root
        :return: a JSON object containing matching project-relative file paths
        """
        self.project.validate_relative_path(relative_path)
        client = IndexMcpClient(self.get_project_root())
        page = client.call_paginated_tool("ide_find_file", {"query": file_mask}, "files")

        base = relative_path.replace("\\", "/").strip("/")
        if base == ".":
            base = ""
        files: list[str] = []
        for match in page.items:
            path = str(match.get("path") or "").replace("\\", "/").strip("/")
            name = str(match.get("name") or os.path.basename(path))
            if base and not (path == base or path.startswith(base + "/")):
                continue
            # ide_find_file is fuzzy by design; retain Serena's mask semantics on the result set.
            if not fnmatch(name, file_mask):
                continue
            files.append(path)

        return self._to_json({"files": sorted(dict.fromkeys(files))})

class IndexMcpSearchForPatternTool(Tool, ToolMarkerOptional):
    def apply(
        self,
        substring_pattern: str,
        context_lines_before: int = 0,
        context_lines_after: int = 0,
        paths_include_glob: str = "",
        paths_exclude_glob: str = "",
        relative_path: str = "",
        restrict_search_to_code_files: bool = False,
        skip_ignored_files: bool = True,
        multiline: bool = True,
        max_answer_chars: int = -1,
    ) -> str:
        """
        Searches project text through JetBrains ``ide_search_text`` and returns Serena's familiar
        per-file match listing. The query is treated as a regular expression, matching Serena's API.

        :param substring_pattern: regular expression to search for
        :param context_lines_before: local context lines to add before each indexed match
        :param context_lines_after: local context lines to add after each indexed match
        :param paths_include_glob: optional project-relative include glob
        :param paths_exclude_glob: optional project-relative exclusion glob
        :param relative_path: optional file/subdirectory restriction
        :param restrict_search_to_code_files: if true, discard hits outside Serena-detected source files
        :param skip_ignored_files: if true, discard hits Serena considers ignored
        :param multiline: when true, add Java-regex multiline/DOTALL flags before sending the query to IntelliJ
        :param max_answer_chars: maximum result length; -1 uses Serena's configured default
        :return: mapping from file paths to matched lines/context, with 0-based line numbers
        """
        relative_path = relative_path.strip()
        if relative_path:
            self.project.validate_relative_path(relative_path)

        paths: list[str] = []
        include_glob = paths_include_glob.strip()
        exclude_glob = paths_exclude_glob.strip()
        include_glob_matcher = GlobMatcher(include_glob) if include_glob else None
        exclude_glob_matcher = GlobMatcher(exclude_glob) if exclude_glob else None
        if include_glob:
            paths.append(include_glob)
        elif relative_path and relative_path != ".":
            paths.append(relative_path.replace("\\", "/"))
        if exclude_glob:
            paths.append("!" + exclude_glob.lstrip("!"))

        indexed_pattern = f"(?ms){substring_pattern}" if multiline else substring_pattern
        args: dict[str, object] = {
            "query": indexed_pattern,
            "regex": True,
            "caseSensitive": True,
            "wholeWord": False,
        }
        if paths:
            args["paths"] = paths

        client = IndexMcpClient(self.get_project_root())
        page = client.call_paginated_tool("ide_search_text", args, "matches")

        base = relative_path.replace("\\", "/").strip("/")
        if base == ".":
            base = ""
        source_files = (
            {p.replace("\\", "/") for p in self.project.gather_source_files(relative_path or "")}
            if restrict_search_to_code_files
            else None
        )

        file_to_matches: dict[str, list[str]] = defaultdict(list)
        match_lines_by_file: dict[str, list[dict[str, int | str]]] = defaultdict(list)
        for match in page.items:
            path = str(match.get("file") or "").replace("\\", "/").strip("/")
            if base and not (path == base or path.startswith(base + "/")):
                continue
            if include_glob_matcher is not None and not include_glob_matcher.matches(path):
                continue
            if exclude_glob_matcher is not None and exclude_glob_matcher.matches(path):
                continue
            if skip_ignored_files and self.project.is_ignored_path(path):
                continue
            if source_files is not None and path not in source_files:
                continue

            line_0 = max(0, int(match.get("line") or 1) - 1)
            line_text = str(match.get("context") or "")
            if context_lines_before or context_lines_after:
                try:
                    rendered = self.project.retrieve_content_around_line(
                        relative_file_path=path,
                        line=line_0,
                        context_lines_before=context_lines_before,
                        context_lines_after=context_lines_after,
                    ).to_display_string()
                except Exception:
                    rendered = f"{line_0}: {line_text}"
            else:
                rendered = f"{line_0}: {line_text}"
            file_to_matches[path].append(rendered)
            match_lines_by_file[path].append({"line": line_0, "text": line_text.strip()})

        _TEXT_TRUNCATE = 60

        def render_first_lines(truncate: bool) -> str:
            def entry_text(text: str) -> str:
                if truncate and len(text) > _TEXT_TRUNCATE:
                    return text[:_TEXT_TRUNCATE] + "..."
                return text

            compact = {
                path: [{"line": m["line"], "text": entry_text(str(m["text"]))} for m in lines]
                for path, lines in match_lines_by_file.items()
            }
            header = (
                f"Matched lines (text over {_TEXT_TRUNCATE} chars is truncated); use read_file for full content:"
                if truncate
                else "Matched lines per file; use read_file with the line numbers for surrounding context:"
            )
            return f"{header}\n{self._to_json(compact)}"

        def make_first_lines_full() -> str:
            return render_first_lines(False)

        def make_first_lines_truncated() -> str:
            return render_first_lines(True)

        def make_line_numbers_only() -> str:
            numbers = {path: [m["line"] for m in lines] for path, lines in match_lines_by_file.items()}
            return f"Match lines per file:\n{self._to_json(numbers)}"

        def make_per_file_counts() -> str:
            counts = {path: len(lines) for path, lines in match_lines_by_file.items()}
            return f"Match counts per file:\n{self._to_json(counts)}"

        def make_summary() -> str:
            suffix = " (truncated by Index MCP pagination ceiling)" if page.truncated else ""
            return f"Found {sum(len(v) for v in match_lines_by_file.values())} matches in {len(match_lines_by_file)} files{suffix}."

        result = self._to_json(file_to_matches)
        return self._limit_length(
            result,
            max_answer_chars,
            shortened_result_factories=[
                make_first_lines_full,
                make_first_lines_truncated,
                make_line_numbers_only,
                make_per_file_counts,
                make_summary,
            ],
        )

    """Performs a search for a pattern in the project via Index MCP."""

