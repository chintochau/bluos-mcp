# BluOS MCP Server

## Project Overview
Python MCP server that exposes BluOS player control as tools for AI assistants (Claude).
Runs locally on your Mac, connects to BluOS players on your local network via HTTP.

## Architecture
Claude Code -> stdio -> MCP Server (server.py on your Mac) -> HTTP:11000 -> BluOS Player (local network)

## Tech Stack
- Python 3.11+
- `mcp` - official Anthropic MCP SDK
- `httpx` - async HTTP client for BluOS API calls
- `python-dotenv` - optional player IP override via .env
- `zeroconf` - mDNS discovery of BluOS players on local network

## BluOS API Reference
- Base URL: `http://<player_ip>:11000`
- No authentication required (local network only)
- Responses are XML (SDUI endpoints may return JSON or XML)
- **Primary reference**: `/Users/jasonchau/projects/desktop_app_v2` — most complete BluOS controller implementation. Check `packages/renderer/src/api/` for correct endpoint paths, query params, request/response shapes, and parsers before adding any new tool.
- **Secondary reference**: `/Users/jasonchau/projects/electron-player-controller` — older reference, still useful for simpler endpoint examples

### Known Endpoints

**Playback**
- `GET /Play` — start playback
- `GET /Play?seek=<seconds>` — seek to position
- `GET /Pause` — pause
- `GET /Stop` — stop
- `GET /Skip` — next track
- `GET /Back` — previous track

**Status**
- `GET /Status` — playback state, track info, volume, etag
- `GET /Status?timeout=15&etag=<etag>` — long-poll (blocks until state changes)
- `GET /SyncStatus` — player info, model, friendly name, grouping
- `GET /SyncStatus?timeout=10&etag=<etag>` — long-poll variant

**Volume**
- `GET /Volume?level=<0-100>` — set volume
- `GET /Volume?level=<0-100>&tell_slaves=0` — set volume without affecting grouped players

**Queue**
- `GET /ui/Queue?playnum=1` — current queue (XML)
- `GET /Playlist` — raw playlist XML

**Presets**
- `GET /Presets` — list all presets
- `GET /Preset?id=<id>` — play a preset
- `GET /SetPreset?id=<id>` — save current as preset

**Grouping / Multi-room**
- `GET /AddSlave?slave=<ip>&port=11000` — add player to group
- `GET /RemoveSlave?slave=<ip>&port=11000` — remove player from group
- `GET /GetUnpairedSlaves` — list available players for grouping

**Browse**
- `GET /Browse` — top-level browse menu
- `GET /ui/Home?playnum=1` — home screen (SDUI)
- `GET /ui/Sources?playnum=1` — input sources (SDUI)
- `GET /ui/Search?playnum=1&q=<query>&service=<service>` — search (SDUI)

**Device**
- `GET /Settings` — player settings
- `GET /upgrade?upgrade=check` — check for firmware update

## MCP Tools

| Tool | BluOS Endpoint | Description |
|------|---------------|-------------|
| discover_players | mDNS `_musc._tcp.local` + GET /SyncStatus | Find all players on network, returns friendly names and IPs |
| get_status | GET /Status | Current track, playback state, volume |
| transport | GET /Play, /Pause, /Skip, /Back | Playback control (action: play/pause/skip/back) |
| set_volume | GET /Volume?level=X | Set volume 0-100 |
| get_queue | GET /ui/Queue?playnum=1 | Current play queue |
| presets | GET /Presets, GET /Preset?id=X | List presets or play one by ID (action: list/play) |
| get_music_services | GET /ui/Search?playnum=1 | List available streaming services (Tidal, Qobuz, etc.) |
| search_music | GET /Albums, /Songs, /Artists?expr=X | Search full catalog with release dates, sorted newest-first |
| play_music | GET /Add?playnow=1, GET /Songs?albumid=X | Play a song or full album from a search_music URI |

All tools accept an optional `ip` parameter. If omitted and only one player is found, it is used automatically. If multiple players exist, the server returns an error listing them so the AI can ask the user to pick one.

## Player Discovery Flow
1. On startup, server auto-discovers via mDNS (or uses `BLUOS_PLAYER_IP` env var if set)
2. Discovery runs once and is cached — subsequent tool calls use the cached result
3. `discover_players` can be called explicitly to refresh the player list

## Project Structure
```
bluos-mcp/
├── server.py        # MCP server entry point, tool definitions
├── bluos_client.py  # thin HTTP wrapper for BluOS API + mDNS discovery
├── .mcp.json        # MCP config for Claude Code (project-scoped)
├── .env.example     # optional BLUOS_PLAYER_IP override
└── requirements.txt
```

## Setup
1. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. Run `claude mcp add` to register globally, or use `.mcp.json` for project-scoped use
3. No `.env` needed — players are discovered automatically via mDNS

## Go Handoff Notes
- Each tool in `server.py` maps 1:1 to a tool in the Go server
- `bluos_client.py` becomes an internal package at `pkg/bluos/`
- MCP library for Go: `github.com/mark3labs/mcp-go`
- XML responses will need `xml.Unmarshal` structs matching the shapes in `bluos_client.py`
- Keep `server.py` thin, no business logic, just HTTP calls and tool wiring
- mDNS discovery: use `github.com/grandcat/zeroconf` for Go equivalent
