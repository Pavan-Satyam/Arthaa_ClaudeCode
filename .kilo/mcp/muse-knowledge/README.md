# Muse knowledge-base MCP server

A dependency-free, stdio **Model Context Protocol** server that serves the
markdown knowledge base Muse (ammu) maintains — the Artha AI memory bank and
knowledge files — to any MCP client, including Kilo Code in VS Code.

The Muse app does **not** expose an MCP endpoint (it reaches apps through
Connectors, not the other way around). This server is the bridge: it reads the
exported knowledge base from disk and exposes it to Kilo on demand, so Kilo can
pull one note instead of loading the whole bank into every task.

- **Transport:** newline-delimited JSON-RPC 2.0 over stdin/stdout.
- **Runtime:** Python 3.8+, standard library only. No packages to install.
- **File:** [`server.py`](server.py) (vendored here; it is the tested original).

## Tools exposed

| Tool | Args | Returns |
|---|---|---|
| `list_knowledge_files` | — | every `.md` file, relative to the KB root |
| `read_knowledge_file` | `path` | the file's contents |
| `search_knowledge` | `query` | matching lines as `file:line: snippet` (case-insensitive) |

All three are **read-only**. `read_knowledge_file` resolves paths through
`safe_path()`, which rejects anything that escapes the knowledge-base root.

## Where things live (hybrid layout)

- **This server lives in the repo** (`.kilo/mcp/muse-knowledge/server.py`) so the
  tool is shared and versioned.
- **The knowledge base is personal and stays external** — it is *not* committed.
  Point `KB_DIR` at your copy of the Muse `kilo-export` folder.
- **The MCP registration is machine-local** (your global Kilo config), because
  `KB_DIR` is an absolute path that is specific to your machine.

## Registering it (global config)

Merge this into the `mcp` object of your **global** Kilo config
(`~/.config/kilo/kilo.jsonc`), replacing the two paths with your real ones:

```jsonc
{
  "mcp": {
    "muse-knowledge": {
      "type": "local",
      "command": ["<REPO>\\.venv\\Scripts\\python.exe",
        "<REPO>\\.kilo\\mcp\\muse-knowledge\\server.py"],
      "environment": { "KB_DIR": "<KB_DIR>" },
      "enabled": true,
      "timeout": 300000
    }
  }
}
```

- `<REPO>` — absolute path to this repository.
- `<KB_DIR>` — absolute path to your `kilo-export` folder (the one containing
  `.kilocode/` and `knowledge/`).

### Windows notes

Call the interpreter by **absolute path** in the argv form (as above). Do **not**
use a `cmd /c python <path>` wrapper: `cmd` joins its arguments without quoting,
so it breaks whenever any path contains a space (e.g. a Windows username like
`siddhartha udatala`). `python` resolves here, but the venv interpreter is the
reliable choice because it does not depend on the PATH that Kilo's process sees:

```jsonc
"command": ["<REPO>\\.venv\\Scripts\\python.exe",
            "<REPO>\\.kilo\\mcp\\muse-knowledge\\server.py"]
```

Swap in `python` or `py` only if you are sure it is on the PATH Kilo sees. The
argv-array form passes spaces correctly because there is no shell parsing.

## Validate

Standalone handshake (no Kilo):

```powershell
$env:KB_DIR = "<KB_DIR>"
@(
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}'
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_knowledge","arguments":{"query":"momentum"}}}'
) | python .kilo\mcp\muse-knowledge\server.py
```

Expect `serverInfo.name = muse-knowledge-base`, the three tool definitions, and
matching lines from your notes.

In Kilo: reload MCP servers (`/mcps` or the sidebar) and confirm `muse-knowledge`
connects with the three tools, then ask Kilo to search for "momentum".

## Keeping it updated

The server reads files from disk on **every** call, so updating the knowledge
base needs no restart — copy (or git-pull) the new version into your `KB_DIR` and
Kilo sees it on the next tool call. Only a change to `server.py` itself needs an
MCP restart.

## Performance note

`search_knowledge` walks every `.md` file and scans each line, stopping after 40
hits. That is fine for a markdown knowledge base; if it grows large, switch to a
pre-built index or narrow the search by file.
