# Plan — Wire the Muse knowledge-base MCP server into the Kilo workspace

## Context
- The Muse app does **not** expose an MCP endpoint; it maintains a markdown knowledge base. The user built a dependency-free stdio MCP server (`server.py`) that serves that KB to any MCP client (including Kilo) with three read-only tools: `list_knowledge_files`, `read_knowledge_file`, `search_knowledge`.
- The knowledge base (`kilo-export`) is a **personal** folder on this machine: `C:\Users\siddhartha udatala\artha-ai\kilo-export`. It is **not** in the repo, and the user's `server.py` currently lives external to the repo too.
- The repo already has a root `kilo.json` with 3 MCP servers (`context7` enabled; `github` + `postgres`/DBHub disabled) plus a `permission` block. This plan **merges into** that, it does not replace it.

## Decision (user, 2026-10-28): Hybrid
- **Vendor `server.py` into the repo** so the tool is shared/portable across the team.
- **Put the `muse-knowledge` MCP entry + the personal `KB_DIR` in the GLOBAL `~/.config/kilo/kilo.jsonc`** (machine-local, not committed). Keeps the repo portable and the personal KB private.

## Tasks (ordered)
1. **Vendor the server.** Create `.kilo/mcp/muse-knowledge/server.py` with the user's tested script **verbatim** (no changes — it's stdio, stdlib-only, `KB_DIR` env-overridable). Keep its default `KB_DIR = <script dir>/knowledge-base` as a fallback only.
2. **Add a README.** Create `.kilo/mcp/muse-knowledge/README.md` covering: what it serves, the three tools, the exact global-config snippet (template with `<REPO>` and `<KB_DIR>` placeholders + the Windows `python`→`py`→venv fallback), the "search is O(files×lines), capped at 40 hits" note for when the base grows, and the reload/test steps.
3. **Shared permission policy.** In the repo `kilo.json` `permission` block, add `"muse-knowledge_*": "allow"` (all three tools are read-only → safe to auto-approve). Leave the existing 3 MCP entries and their permissions untouched.
4. **Global MCP registration (machine-local, not committed).** In `C:\Users\siddhartha udatala\.config\kilo\kilo.jsonc`, merge into any existing `mcp`:
   ```jsonc
   "mcp": {
     "muse-knowledge": {
       "type": "local",
       "command": ["cmd", "/c", "python",
         "C:\\Users\\siddhartha udatala\\sources\\Arthaa_ClaudeCode\\.kilo\\mcp\\muse-knowledge\\server.py"],
       "environment": { "KB_DIR": "C:\\Users\\siddhartha udatala\\artha-ai\\kilo-export" },
       "enabled": true,
       "timeout": 300000
     }
   }
   ```
   - If `python` is not on PATH, replace `python` with `py`, or drop `cmd /c` and use the venv interpreter directly: `C:\\Users\\siddhartha udatala\\sources\\Arthaa_ClaudeCode\\.venv\\Scripts\\python.exe`.
5. **Validate the server standalone (before wiring).** With `KB_DIR` set, pipe a JSON-RPC handshake to `server.py` and assert:
   - `initialize` → `result.serverInfo.name == "muse-knowledge-base"`.
   - `tools/list` → exactly the 3 tools.
   - `tools/call` `list_knowledge_files` → a non-empty `.md` list.
   - `tools/call` `search_knowledge` with `{"query":"momentum"}` → hits from the quant notes.
6. **Validate in Kilo.** Reload MCP servers (`/mcps` or the sidebar); confirm `muse-knowledge` connects and the 3 tools appear; ask Kilo to `list_knowledge_files` then `search_knowledge` for "momentum".
7. **Commit repo changes only:** `.kilo/mcp/muse-knowledge/{server.py,README.md}` and the `kilo.json` permission addition. **Do not** commit the global config or the `kilo-export` folder.

## Decisions
- Hybrid location (vendor server.py in repo; MCP entry + `KB_DIR` global).
- `server.py` is vendored **verbatim** (tested, dependency-free).
- MCP entry is **global** because `KB_DIR` is a personal absolute path; committing it would break the repo for other machines/users.
- Permissions: all 3 tools are read-only → `allow`.

## Risks / edge cases
- `python` not on PATH on Windows → use `py` or the venv `python.exe` (absolute) in the global command (step 4 fallback).
- Path with spaces (`siddhartha udatala`) → JSON-escape backslashes; the argv-array form passes spaces without shell parsing.
- `safe_path()` already prevents traversal outside `KB_DIR`.
- Search is O(files × lines), capped at 40 hits — fine for a markdown KB; note it in the README for when the base grows.
- Do not disturb the existing 3 MCP entries or permissions in repo `kilo.json`.

## Validation
- Standalone JSON-RPC handshake (step 5) before wiring.
- In-Kilo connection + tool visibility + a real `search_knowledge` round-trip (step 6).

## Out of scope
- Committing the knowledge base itself (stays personal/external).
- Cross-platform command portability beyond this Windows machine (documented as a template; other users adapt their own global entry).
- Any change to `server.py` behavior (it is tested as-is).

## Open questions
- None blocking. (If you'd rather commit the KB into the repo too, say so and I'll switch to an all-in-repo variant with a repo-relative `KB_DIR`.)