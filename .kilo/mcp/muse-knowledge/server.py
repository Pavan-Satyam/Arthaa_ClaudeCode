#!/usr/bin/env python3
"""Muse knowledge base MCP server (stdio, dependency-free).

Serves the markdown knowledge base that Muse (ammu) maintains -- the
Artha AI memory bank and knowledge files -- to any MCP client,
including Kilo Code in VS Code.

Transport: newline-delimited JSON-RPC 2.0 over stdin/stdout
(the standard MCP stdio transport).

Tools:
  - list_knowledge_files: list every .md file in the knowledge base.
  - read_knowledge_file: read one file by its path relative to KB_DIR.
  - search_knowledge: grep all files for a query, return matching
    snippets with file names and line numbers.

Configuration: point KB_DIR at the knowledge base folder on the
machine running Kilo, e.g. the copied kilo-export folder:

    KB_DIR=/path/to/artha-ai-knowledge python3 server.py

No third-party packages required. Python 3.8+.
"""

import json
import os
import re
import sys

KB_DIR = os.path.abspath(os.environ.get(
    "KB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "knowledge-base")))


def safe_path(rel):
    """Resolve rel inside KB_DIR; return None if it escapes."""
    base = KB_DIR
    target = os.path.abspath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target


def list_md_files():
    out = []
    for root, _dirs, files in os.walk(KB_DIR):
        for name in sorted(files):
            if name.endswith(".md"):
                full = os.path.join(root, name)
                out.append(os.path.relpath(full, KB_DIR))
    return sorted(out)


def tool_list_knowledge_files(_args):
    files = list_md_files()
    if not files:
        return "No markdown files found under KB_DIR: %s" % KB_DIR
    return "\n".join(files)


def tool_read_knowledge_file(args):
    rel = args.get("path", "")
    if not rel:
        return "Error: 'path' is required (relative to the knowledge base)."
    target = safe_path(rel)
    if target is None or not os.path.isfile(target):
        return "Error: file not found in the knowledge base: %s" % rel
    with open(target, "r", encoding="utf-8") as f:
        return f.read()


def tool_search_knowledge(args):
    query = args.get("query", "")
    if not query:
        return "Error: 'query' is required."
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    hits = []
    for rel in list_md_files():
        full = os.path.join(KB_DIR, rel)
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                snippet = line.strip()
                if len(snippet) > 200:
                    snippet = snippet[:200] + "..."
                hits.append("%s:%d: %s" % (rel, i, snippet))
                if len(hits) >= 40:
                    break
        if len(hits) >= 40:
            break
    if not hits:
        return "No matches for %r in the knowledge base." % query
    return "\n".join(hits)


TOOLS = [
    {
        "name": "list_knowledge_files",
        "description": "List every markdown file in the Muse-maintained "
                       "knowledge base (Artha AI memory bank and notes).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_knowledge_file",
        "description": "Read one knowledge base file. 'path' is relative "
                       "to the knowledge base root, e.g. "
                       "'knowledge/quant-knowledge-base.md'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Path relative to the knowledge base root."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search all knowledge base files for a word or phrase "
                       "and return matching lines with file names.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Word or phrase to search for."}
            },
            "required": ["query"],
        },
    },
]

HANDLERS = {
    "list_knowledge_files": tool_list_knowledge_files,
    "read_knowledge_file": tool_read_knowledge_file,
    "search_knowledge": tool_search_knowledge,
}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    # Notifications (no id) get no response.
    if mid is None:
        return
    if method == "initialize":
        client_version = (msg.get("params") or {}).get("protocolVersion")
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": client_version or "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "muse-knowledge-base",
                           "version": "1.0.0"},
        }})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32602, "message": "Unknown tool: %s" % name}})
            return
        try:
            text = fn(args)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}]}})
        except Exception as exc:  # noqa: BLE001 - surface as tool error
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": "Error: %s" % exc}],
                "isError": True}})
    else:
        send({"jsonrpc": "2.0", "id": mid, "error": {
            "code": -32601, "message": "Method not found: %s" % method}})


def main():
    if not os.path.isdir(KB_DIR):
        sys.stderr.write("KB_DIR does not exist: %s\n" % KB_DIR)
        sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    main()
