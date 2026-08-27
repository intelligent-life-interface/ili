#!/usr/bin/env python3
"""MCP-Server für Kanban-Dashboard (Port 8798).

Connects to local Dashboard REST API (http://127.0.0.1:8798) and exposes MCP tools
for reading/writing Kanban boards and cards.

Usage: mcp-server-dashboard
       → Reads JSON-RPC messages from stdin
       → Writes JSON-RPC responses to stdout (standard MCP stdio protocol)

Tools exposed:
  - list_boards: Enumerate all boards (optional parent filter)
  - get_board: Fetch board with cards (trimmed description)
  - get_card: Fetch individual card
  - create_card: Add new card to column
  - move_card: Move card between columns or reorder
  - update_card: Update card fields (title, description, owner, labels, status)
  - add_note: Append timestamped note to card

Errors propagate as MCP error responses (code + message).
"""

import os
import subprocess
import sys
import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Optional
from datetime import datetime

# Setup logging to stderr (separate from stdout which is MCP protocol)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [mcp-dashboard] %(message)s",
)
log = logging.getLogger("mcp-dashboard")

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8798")


def _detect_kanban_source() -> str:
    """Identity rule shared with ~/.claude/statusline-kanban.sh: KANBAN_SOURCE
    env if set, else the tmux session name (term2, proj-<slug>), else "".
    Sent as X-Kanban-Source so board activity events can be attributed to the
    terminal that caused them. Spawned per Claude session, so once is enough.
    """
    src = os.environ.get("KANBAN_SOURCE", "").strip()
    if src:
        return src
    if os.environ.get("TMUX"):
        try:
            out = subprocess.run(["tmux", "display-message", "-p", "#S"],
                                 capture_output=True, text=True, timeout=2)
            return out.stdout.strip()
        except Exception as e:
            log.debug("tmux session name lookup failed: %s", e)
    return ""


KANBAN_SOURCE = _detect_kanban_source()
DESCRIPTION_TRIM = 200


def dashboard_request(method: str, path: str, data: Optional[dict] = None) -> Any:
    """Make HTTP request to Dashboard API.

    Raises:
        RuntimeError: HTTP error or connection failure
        json.JSONDecodeError: Invalid JSON response
    """
    url = f"{DASHBOARD_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if KANBAN_SOURCE:
        headers["X-Kanban-Source"] = KANBAN_SOURCE

    if data is not None:
        data_bytes = json.dumps(data).encode("utf-8")
    else:
        data_bytes = None

    try:
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        log.error("%s %s -> HTTP %d: %s", method, path, e.code, body)
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        log.error("Connection error to %s: %s", url, e.reason)
        raise RuntimeError(f"Connection error: {e.reason}")
    except Exception as e:
        log.error("Unexpected error in dashboard_request: %s", e)
        raise


def trim_description(desc: str) -> str:
    """Trim description to DESCRIPTION_TRIM chars, add ellipsis if truncated."""
    if len(desc) <= DESCRIPTION_TRIM:
        return desc
    return desc[:DESCRIPTION_TRIM] + "…"


def find_card_in_board(board: dict, card_id: str) -> tuple[Optional[dict], Optional[str]]:
    """Find card by ID in board. Returns (card, column_id) or (None, None)."""
    for column in board.get("columns", []):
        for card in column.get("cards", []):
            if card.get("id") == card_id:
                return card, column.get("id")
    return None, None


class MCPServer:
    """Minimal MCP server implementation (stdio-based JSON-RPC)."""

    def __init__(self):
        self.request_id = None
        self.protocol_version = "2024-11-05"
        self.server_name = "dashboard-kanban"
        self.server_version = "1.0.0"

    def tool_list_boards(self, params: dict) -> Any:
        """List all boards (optional parent filter)."""
        parent = params.get("parent", "")
        query = f"?parent={urllib.parse.quote(parent)}" if parent else ""
        boards = dashboard_request("GET", f"/boards{query}")

        # Trim description for efficiency
        for b in boards.get("boards", []):
            if "description" in b:
                b["description"] = trim_description(b["description"])

        return boards

    def tool_get_board(self, params: dict) -> Any:
        """Fetch board with cards (trimmed descriptions)."""
        board_id = params.get("board_id")
        if not board_id:
            raise ValueError("Missing parameter: board_id")

        board = dashboard_request("GET", f"/board?id={urllib.parse.quote(board_id)}")

        # Trim descriptions
        for column in board.get("columns", []):
            for card in column.get("cards", []):
                if "description" in card:
                    card["description"] = trim_description(card["description"])

        return board

    def tool_get_card(self, params: dict) -> Any:
        """Fetch individual card."""
        board_id = params.get("board_id")
        card_id = params.get("card_id")

        if not board_id or not card_id:
            raise ValueError("Missing parameters: board_id, card_id")

        board = dashboard_request("GET", f"/board?id={urllib.parse.quote(board_id)}")
        card, column_id = find_card_in_board(board, card_id)

        if not card:
            raise ValueError(f"Card '{card_id}' not found in board '{board_id}'")

        result = dict(card)
        if "description" in result:
            result["description"] = trim_description(result["description"])
        result["column_id"] = column_id

        return result

    def tool_create_card(self, params: dict) -> Any:
        """Create new card in column."""
        board_id = params.get("board_id")
        column_id = params.get("column_id")
        title = params.get("title", "Untitled")
        description = params.get("description", "")
        position = params.get("position")  # Optional: insert at position

        if not board_id or not column_id:
            raise ValueError("Missing parameters: board_id, column_id")

        # Fetch board
        board = dashboard_request("GET", f"/board?id={urllib.parse.quote(board_id)}")

        # Find target column
        target_col = None
        for col in board.get("columns", []):
            if col.get("id") == column_id:
                target_col = col
                break

        if not target_col:
            raise ValueError(f"Column '{column_id}' not found in board '{board_id}'")

        # Create new card
        import uuid
        new_card = {
            "id": str(uuid.uuid4()),
            "title": title,
            "description": description,
            "owner": params.get("owner"),
            "labels": params.get("labels", []),
        }

        cards = target_col.get("cards", [])
        if position is not None and 0 <= position < len(cards):
            cards.insert(position, new_card)
        else:
            cards.append(new_card)

        target_col["cards"] = cards

        # Save board
        dashboard_request("POST", f"/board?id={urllib.parse.quote(board_id)}", board)

        return new_card

    def tool_move_card(self, params: dict) -> Any:
        """Move card between columns or reorder within column."""
        board_id = params.get("board_id")
        card_id = params.get("card_id")
        target_column_id = params.get("target_column_id")
        position = params.get("position")

        if not board_id or not card_id or not target_column_id:
            raise ValueError("Missing parameters: board_id, card_id, target_column_id")

        # Fetch board
        board = dashboard_request("GET", f"/board?id={urllib.parse.quote(board_id)}")

        # Find and remove card from source column
        card = None
        source_col = None
        for col in board.get("columns", []):
            cards = col.get("cards", [])
            for i, c in enumerate(cards):
                if c.get("id") == card_id:
                    card = cards.pop(i)
                    source_col = col
                    break
            if card:
                break

        if not card:
            raise ValueError(f"Card '{card_id}' not found in board '{board_id}'")

        # Find target column
        target_col = None
        for col in board.get("columns", []):
            if col.get("id") == target_column_id:
                target_col = col
                break

        if not target_col:
            raise ValueError(f"Target column '{target_column_id}' not found")

        # Insert card into target column
        target_cards = target_col.get("cards", [])
        if position is not None and 0 <= position <= len(target_cards):
            target_cards.insert(position, card)
        else:
            target_cards.append(card)

        target_col["cards"] = target_cards

        # Save board
        dashboard_request("POST", f"/board?id={urllib.parse.quote(board_id)}", board)

        return {"id": card_id, "column_id": target_column_id, "position": len(target_cards) - 1}

    def tool_update_card(self, params: dict) -> Any:
        """Update card fields."""
        board_id = params.get("board_id")
        card_id = params.get("card_id")
        updates = {k: v for k, v in params.items() if k not in ["board_id", "card_id"]}

        if not board_id or not card_id:
            raise ValueError("Missing parameters: board_id, card_id")

        if not updates:
            raise ValueError("No update fields provided")

        # Fetch board
        board = dashboard_request("GET", f"/board?id={urllib.parse.quote(board_id)}")

        # Find and update card
        card, column_id = find_card_in_board(board, card_id)
        if not card:
            raise ValueError(f"Card '{card_id}' not found in board '{board_id}'")

        for key, value in updates.items():
            card[key] = value

        # Save board
        dashboard_request("POST", f"/board?id={urllib.parse.quote(board_id)}", board)

        return card

    def tool_add_note(self, params: dict) -> Any:
        """Append timestamped note to card description."""
        board_id = params.get("board_id")
        card_id = params.get("card_id")
        text = params.get("text", "")

        if not board_id or not card_id:
            raise ValueError("Missing parameters: board_id, card_id")

        if not text:
            raise ValueError("Missing parameter: text")

        # Fetch board
        board = dashboard_request("GET", f"/board?id={urllib.parse.quote(board_id)}")

        # Find card
        card, column_id = find_card_in_board(board, card_id)
        if not card:
            raise ValueError(f"Card '{card_id}' not found in board '{board_id}'")

        # Append note
        timestamp = datetime.now().strftime("%H:%M")
        note = f"— 🤖 {timestamp}: {text}"
        current_desc = card.get("description", "")
        if current_desc:
            card["description"] = current_desc + "\n" + note
        else:
            card["description"] = note

        # Save board
        dashboard_request("POST", f"/board?id={urllib.parse.quote(board_id)}", board)

        return card

    def handle_tool_call(self, name: str, params: dict) -> Any:
        """Dispatch tool call to handler."""
        handlers = {
            "list_boards": self.tool_list_boards,
            "get_board": self.tool_get_board,
            "get_card": self.tool_get_card,
            "create_card": self.tool_create_card,
            "move_card": self.tool_move_card,
            "update_card": self.tool_update_card,
            "add_note": self.tool_add_note,
        }

        if name not in handlers:
            raise ValueError(f"Unknown tool: {name}")

        return handlers[name](params)

    def send_response(self, result: Any = None, error: Optional[dict] = None) -> None:
        """Send JSON-RPC response."""
        response = {"jsonrpc": "2.0"}

        if self.request_id is not None:
            response["id"] = self.request_id

        if error:
            response["error"] = error
        else:
            response["result"] = result

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    def handle_initialize(self, params: dict) -> dict:
        """Handle initialize request."""
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": self.server_name,
                "version": self.server_version,
            },
        }

    def get_tools(self) -> list[dict]:
        """Return tool definitions."""
        return [
            {
                "name": "list_boards",
                "description": "List all Kanban boards (optionally filter by parent)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "parent": {
                            "type": "string",
                            "description": "Parent board ID (optional)",
                        },
                    },
                },
            },
            {
                "name": "get_board",
                "description": "Fetch a board with all its cards and columns",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "board_id": {
                            "type": "string",
                            "description": "Board ID",
                        },
                    },
                    "required": ["board_id"],
                },
            },
            {
                "name": "get_card",
                "description": "Fetch a single card by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "board_id": {"type": "string"},
                        "card_id": {"type": "string"},
                    },
                    "required": ["board_id", "card_id"],
                },
            },
            {
                "name": "create_card",
                "description": "Create a new card in a column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "board_id": {"type": "string"},
                        "column_id": {"type": "string"},
                        "title": {"type": "string", "default": "Untitled"},
                        "description": {"type": "string", "default": ""},
                        "owner": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                        "position": {
                            "type": "integer",
                            "description": "Insert at position (0=first, omit=append)",
                        },
                    },
                    "required": ["board_id", "column_id"],
                },
            },
            {
                "name": "move_card",
                "description": "Move card between columns or reorder within column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "board_id": {"type": "string"},
                        "card_id": {"type": "string"},
                        "target_column_id": {"type": "string"},
                        "position": {
                            "type": "integer",
                            "description": "Position in target column (0=first, omit=append)",
                        },
                    },
                    "required": ["board_id", "card_id", "target_column_id"],
                },
            },
            {
                "name": "update_card",
                "description": "Update card fields (title, description, owner, labels, status, etc.)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "board_id": {"type": "string"},
                        "card_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "owner": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                    },
                    "required": ["board_id", "card_id"],
                },
            },
            {
                "name": "add_note",
                "description": "Append a timestamped note to a card's description",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "board_id": {"type": "string"},
                        "card_id": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["board_id", "card_id", "text"],
                },
            },
        ]

    def handle_tools_list(self) -> dict:
        """Handle tools/list request."""
        return {"tools": self.get_tools()}

    def handle_call_tool(self, params: dict) -> Any:
        """Handle tool/call request."""
        name = params.get("name")
        tool_params = params.get("arguments", {})

        try:
            result = self.handle_tool_call(name, tool_params)
            return {
                "content": [
                    {"type": "text", "text": json.dumps(result, indent=2)}
                ],
                "isError": False,
            }
        except Exception as e:
            log.error("Tool call %s failed: %s", name, e)
            return {
                "content": [
                    {"type": "text", "text": f"Error: {str(e)}"}
                ],
                "isError": True,
            }

    def run(self) -> None:
        """Main loop: read JSON-RPC from stdin, respond to stdout."""
        log.info("Starting MCP server (stdio mode)")

        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                    method = msg.get("method")
                    params = msg.get("params", {})

                    if "id" not in msg:
                        # JSON-RPC notification (e.g. notifications/initialized) —
                        # no response allowed, not even an error.
                        log.debug("Received notification: %s", method)
                        continue

                    self.request_id = msg.get("id")
                    log.debug("Received: %s (id=%s)", method, self.request_id)

                    if method == "initialize":
                        result = self.handle_initialize(params)
                        self.send_response(result=result)

                    elif method == "tools/list":
                        result = self.handle_tools_list()
                        self.send_response(result=result)

                    elif method == "tools/call":
                        result = self.handle_call_tool(params)
                        self.send_response(result=result)

                    else:
                        self.send_response(error={
                            "code": -32601,
                            "message": f"Method not found: {method}",
                        })

                except json.JSONDecodeError as e:
                    log.error("JSON decode error: %s", e)
                    self.send_response(error={
                        "code": -32700,
                        "message": "Parse error",
                    })

                except Exception as e:
                    log.error("Unhandled error: %s", e)
                    self.send_response(error={
                        "code": -32603,
                        "message": str(e),
                    })

        except KeyboardInterrupt:
            log.info("Shutting down (SIGINT)")
            sys.exit(0)
        except Exception as e:
            log.error("Fatal error: %s", e, exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    server = MCPServer()
    server.run()
