import json
import unittest
from unittest.mock import Mock, patch

from serena.index_mcp_client import IndexMcpClient, IndexMcpError, find_structure_node, parse_file_structure_tree


def _response(payload: dict) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _mcp_result(data: dict, *, is_error: bool = False) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": json.dumps(data)}],
            "isError": is_error,
        },
    }


class IndexMcpClientTest(unittest.TestCase):
    def test_call_tool_adds_project_path_and_streamable_http_headers(self) -> None:
        with patch("serena.index_mcp_client.requests.post") as post:
            post.return_value = _response(_mcp_result({"symbols": []}))
            client = IndexMcpClient("/workspace/project")

            result = client.call_json_tool("ide_find_symbol", {"query": "Widget"})

            self.assertEqual(result, {"symbols": []})
            kwargs = post.call_args.kwargs
            self.assertEqual(kwargs["json"]["method"], "tools/call")
            self.assertEqual(kwargs["json"]["params"]["name"], "ide_find_symbol")
            self.assertEqual(
                kwargs["json"]["params"]["arguments"],
                {"project_path": "/workspace/project", "query": "Widget"},
            )
            self.assertEqual(kwargs["headers"]["Accept"], "application/json, text/event-stream")

    def test_paginated_tool_follows_index_cursor(self) -> None:
        first = {
            "symbols": [{"name": "One"}],
            "hasMore": True,
            "nextCursor": "cursor-2",
            "totalCount": 2,
        }
        second = {
            "symbols": [{"name": "Two"}],
            "hasMore": False,
            "totalCount": 2,
        }
        with patch("serena.index_mcp_client.requests.post") as post:
            post.side_effect = [_response(_mcp_result(first)), _response(_mcp_result(second))]
            result = IndexMcpClient("/workspace/project").call_paginated_tool(
                "ide_find_symbol", {"query": "Thing"}, "symbols"
            )

        self.assertEqual([item["name"] for item in result.items], ["One", "Two"])
        self.assertEqual(
            post.call_args_list[1].kwargs["json"]["params"]["arguments"],
            {"project_path": "/workspace/project", "cursor": "cursor-2", "pageSize": 500},
        )

    def test_streamable_http_sse_response_is_accepted(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("not a plain JSON body")
        response.text = (
            'event: message\n'
            'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\\"files\\": []}"}],"isError":false}}\n\n'
        )
        with patch("serena.index_mcp_client.requests.post", return_value=response):
            result = IndexMcpClient("/workspace/project").call_json_tool("ide_find_file", {"query": "x.py"})
        self.assertEqual(result, {"files": []})

    def test_non_json_payload_has_actionable_response_format_error(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "symbols[0]:"}], "isError": False},
        }
        with patch("serena.index_mcp_client.requests.post", return_value=_response(payload)):
            with self.assertRaisesRegex(IndexMcpError, "Response format to JSON"):
                IndexMcpClient("/workspace/project").call_json_tool("ide_find_symbol", {"query": "Widget"})

    def test_file_structure_parser_recovers_hierarchy_and_ranges(self) -> None:
        structure = """Widget.java

class public Widget (lines 3-20)
  field private count: int (line 4)
  method public run(String): void (lines 6-12)
    variable local: String (line 8)
"""
        nodes = parse_file_structure_tree(structure)

        self.assertEqual(nodes[0]["name"], "Widget")
        self.assertEqual(nodes[0]["kind"], "Class")
        self.assertEqual(nodes[0]["children"][1]["name"], "run")
        self.assertEqual(nodes[0]["children"][1]["kind"], "Method")
        self.assertEqual(find_structure_node(nodes, line=8, name="local")["name"], "local")


if __name__ == "__main__":
    unittest.main()
