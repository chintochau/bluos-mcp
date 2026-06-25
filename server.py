import asyncio
import json
import os

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from bluos_client import BluOSClient, discover_bluos_players

load_dotenv()

server = Server("bluos")

_discovered_players: list[dict] = []
_discovery_done = False


def _client(arguments: dict) -> BluOSClient:
    ip = arguments.get("ip")
    if ip:
        return BluOSClient(ip)
    if _discovered_players:
        return BluOSClient(_discovered_players[0]["ip"])
    raise RuntimeError("No BluOS players found on the network.")


def _player_ip_param() -> dict:
    if len(_discovered_players) == 1:
        p = _discovered_players[0]
        description = f"IP address of the target player. Only one player available: {p['name']} ({p['ip']}). Can be omitted."
    elif len(_discovered_players) > 1:
        hints = ", ".join(f"{p['name']} ({p['ip']})" for p in _discovered_players)
        description = (
            f"IP address of the target player. "
            f"Available players: {hints}. "
            f"Pick the best match from context (e.g. 'my player', a room name, or a player name the user mentions). "
            f"Only ask if genuinely ambiguous."
        )
    else:
        description = "IP address of the player. No players found at startup — call discover_players to scan the network."
    return {"ip": {"type": "string", "description": description}}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="discover_players",
            description=(
                "Refresh the list of BluOS players on the network. "
                "Players are already discovered at server startup and embedded in each tool's ip parameter — "
                "only call this if you need to detect players that came online after the session started."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_status",
            description="Get current track info, playback state, and volume from a BluOS player.",
            inputSchema={"type": "object", "properties": _player_ip_param()},
        ),
        Tool(
            name="transport",
            description="Control playback on a BluOS player: play, pause, skip to next track, or go back to previous track.",
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "action": {
                        "type": "string",
                        "enum": ["play", "pause", "skip", "back"],
                        "description": "Playback action to perform.",
                    },
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="set_volume",
            description="Set the volume on a BluOS player.",
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "level": {
                        "type": "integer",
                        "description": "Volume level from 0 to 100.",
                        "minimum": 0,
                        "maximum": 100,
                    },
                },
                "required": ["level"],
            },
        ),
        Tool(
            name="get_queue",
            description="Get the current play queue of a BluOS player.",
            inputSchema={"type": "object", "properties": _player_ip_param()},
        ),
        Tool(
            name="browse_presets",
            description=(
                "Browse available preset sources on a BluOS player. "
                "Use this to find playlists, stations, live radio, and inputs that can be saved as presets. "
                "Call with no arguments to get the top-level list of sources (Apple Music, Tidal, Radio, Inputs, etc.). "
                "Then drill into a source by passing the url and service from a result. "
                "Items with type='audio' are ready to save — pass their url and image to presets: save. "
                "Items with type='link' need another browse call to go deeper. "
                "IMPORTANT: Albums cannot be saved as presets directly. If the user wants an album as a preset, "
                "say 'Since BluOS presets don't support albums directly, I'll play it, save it as a local playlist, "
                "then save that as your preset' — then do: play_music, queue_manage save, local_playlists save_as_preset."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "url": {
                        "type": "string",
                        "description": "URL from a previous browse_presets result. Omit to get top-level sources.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service from a previous browse_presets result (e.g. 'AppleMusic', 'Tidal'). Include when drilling into a service.",
                    },
                },
            },
        ),
        Tool(
            name="presets",
            description=(
                "List saved presets, play one by ID, save an item as a preset, or delete a preset. "
                "To save: use browse_presets to find an audio item, then call this with action=save passing its url and image. "
                "Albums cannot be saved directly — use the local playlist workaround instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "action": {
                        "type": "string",
                        "enum": ["list", "play", "save", "delete"],
                        "description": (
                            "list: return all presets. "
                            "play: start the preset with the given id. "
                            "save: save an item as a preset — requires id, name, and url. "
                            "delete: remove a preset by id."
                        ),
                    },
                    "id": {
                        "type": "integer",
                        "description": "Preset slot number. Required for action=play, save, or delete.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the preset. Required for action=save.",
                    },
                    "url": {
                        "type": "string",
                        "description": "URL of the item to save, from a browse_presets audio result. Required for action=save.",
                    },
                    "image": {
                        "type": "string",
                        "description": "Image URL from a browse_presets result. Optional for action=save.",
                    },
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="get_music_services",
            description="Get the list of music streaming services available on a BluOS player (e.g. Tidal, Qobuz, Amazon). Use this to know which services to search.",
            inputSchema={"type": "object", "properties": _player_ip_param()},
        ),
        Tool(
            name="search_music",
            description=(
                "Search for music on a BluOS player. Returns the full catalog of albums, songs, or artists "
                "matching the query on a specific service. Albums are sorted newest-first by release date. "
                "IMPORTANT: Extract a clean search term before calling — natural language like "
                "'Taylor Swift's latest album' should become query='Taylor Swift', type='albums'. "
                "Then pick the best match from the results based on the user's intent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "query": {
                        "type": "string",
                        "description": "Clean search term: artist name, album title, or song title.",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service ID (e.g. 'AppleMusic', 'Tidal', 'Qobuz'). Get available services from get_music_services.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["albums", "songs", "artists"],
                        "description": "What to search for.",
                    },
                },
                "required": ["query", "service", "type"],
            },
        ),
        Tool(
            name="local_playlists",
            description=(
                "List and play playlists saved on the BluOS player itself. "
                "These are different from streaming service playlists (Tidal, Apple Music, etc.) — "
                "a BluOS local playlist can contain tracks mixed from any service. "
                "When the user says 'my playlist', 'play my queue', or mentions a playlist by name "
                "without specifying a service, try this first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "action": {
                        "type": "string",
                        "enum": ["list", "play", "save_as_preset"],
                        "description": (
                            "list: return all playlists saved on the BluOS player with their IDs and names. "
                            "play: start playing a playlist by its ID (get IDs from list). "
                            "save_as_preset: save a local playlist to a BluOS preset slot by ID."
                        ),
                    },
                    "playlist_id": {
                        "type": "string",
                        "description": "Playlist ID from the list action. Required for action=play and save_as_preset.",
                    },
                    "preset_id": {
                        "type": "integer",
                        "description": "Preset slot number (1-6). Required for action=save_as_preset.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the preset. For save_as_preset only. If omitted, uses the playlist name.",
                    },
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="queue_manage",
            description=(
                "Manage the current play queue on a BluOS player: "
                "remove a track by position, reorder tracks, clear the queue, "
                "or save the current queue as a named local playlist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "action": {
                        "type": "string",
                        "enum": ["remove", "reorder", "clear", "save"],
                        "description": (
                            "remove: delete a track at the given index. "
                            "reorder: move a track from from_index to to_index. "
                            "clear: empty the entire queue. "
                            "save: save the current queue as a named local playlist."
                        ),
                    },
                    "index": {
                        "type": "integer",
                        "description": "0-based track position in the queue. Required for action=remove.",
                    },
                    "from_index": {
                        "type": "integer",
                        "description": "Current 0-based position of the track to move. Required for action=reorder.",
                    },
                    "to_index": {
                        "type": "integer",
                        "description": "Target 0-based position to move the track to. Required for action=reorder.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the saved playlist. Required for action=save.",
                    },
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="play_music",
            description=(
                "Play a music item on a BluOS player using a URI returned by search_music. "
                "Handles individual songs and full albums. "
                "For albums, all tracks are queued in order and playback starts immediately. "
                "Set add_to_queue=true to append to the existing queue without interrupting current playback."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    **_player_ip_param(),
                    "uri": {
                        "type": "string",
                        "description": "The URI from a search_music result (song or album URI).",
                    },
                    "add_to_queue": {
                        "type": "boolean",
                        "description": "If true, append to the queue without interrupting current playback. Defaults to false.",
                    },
                },
                "required": ["uri"],
            },
        ),
    ]


async def _ensure_players():
    global _discovered_players, _discovery_done
    if not _discovered_players and not _discovery_done:
        _discovery_done = True
        players = await asyncio.get_event_loop().run_in_executor(None, discover_bluos_players)
        _discovered_players = players


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _discovered_players

    try:
        if name != "discover_players":
            await _ensure_players()

        if name == "discover_players":
            players = await asyncio.get_event_loop().run_in_executor(
                None, discover_bluos_players
            )
            _discovered_players = players
            result = {"players": players}

        elif name == "get_status":
            result = await _client(arguments).get_status()
        elif name == "transport":
            action = arguments["action"]
            client = _client(arguments)
            if action == "play":
                result = await client.play()
            elif action == "pause":
                result = await client.pause()
            elif action == "skip":
                result = await client.skip()
            elif action == "back":
                result = await client.back()
            else:
                result = {"error": f"Unknown action: {action}"}
        elif name == "set_volume":
            result = await _client(arguments).set_volume(arguments["level"])
        elif name == "get_queue":
            result = await _client(arguments).get_queue()
        elif name == "browse_presets":
            result = await _client(arguments).browse_presets(
                arguments.get("url"),
                arguments.get("service"),
            )
        elif name == "presets":
            action = arguments["action"]
            client = _client(arguments)
            if action == "list":
                result = await client.get_presets()
            elif action == "play":
                result = await client.play_preset(arguments["id"])
            elif action == "save":
                if "url" in arguments:
                    url = arguments["url"]
                    if any(url.startswith(p) for p in ("/Albums", "/Songs", "/Add?", "/Artists")):
                        result = {"error": (
                            "Albums and songs cannot be saved as presets directly. "
                            "To save an album as a preset: (1) play_music the album, "
                            "(2) queue_manage save it as a local playlist, "
                            "(3) local_playlists save_as_preset to the desired slot. "
                            "Tell the user: 'Since BluOS presets don't support albums directly, "
                            "I'll play it, save it as a local playlist, then save that as your preset.'"
                        )}
                    else:
                        result = await client.save_preset(
                            arguments["id"],
                            arguments["name"],
                            url,
                            arguments.get("image"),
                        )
                else:
                    result = await client.save_preset_from_status(arguments["id"], arguments.get("name"))
            elif action == "delete":
                result = await client.delete_preset(arguments["id"])
            else:
                result = {"error": f"Unknown action: {action}"}
        elif name == "queue_manage":
            action = arguments["action"]
            client = _client(arguments)
            if action == "remove":
                result = await client.queue_remove(arguments["index"])
            elif action == "reorder":
                result = await client.queue_reorder(arguments["from_index"], arguments["to_index"])
            elif action == "clear":
                result = await client.queue_clear()
            elif action == "save":
                result = await client.queue_save(arguments["name"])
            else:
                result = {"error": f"Unknown action: {action}"}
        elif name == "local_playlists":
            action = arguments["action"]
            client = _client(arguments)
            if action == "list":
                result = await client.list_local_playlists()
            elif action == "play":
                result = await client.play_local_playlist(arguments["playlist_id"])
            elif action == "save_as_preset":
                result = await client.save_local_playlist_as_preset(
                    arguments["playlist_id"],
                    arguments["preset_id"],
                    arguments.get("name"),
                )
            else:
                result = {"error": f"Unknown action: {action}"}
        elif name == "get_music_services":
            result = await _client(arguments).get_music_services()
        elif name == "search_music":
            result = await _client(arguments).search_music(arguments["query"], arguments["service"], arguments["type"])
        elif name == "play_music":
            result = await _client(arguments).play_music(arguments["uri"], arguments.get("add_to_queue", False))
        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__}

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _auto_discover():
    global _discovered_players, _discovery_done
    _discovery_done = True

    ip = os.getenv("BLUOS_PLAYER_IP")
    if ip:
        _discovered_players = [{"name": ip, "ip": ip, "port": 11000}]
        return

    players = await asyncio.get_event_loop().run_in_executor(None, discover_bluos_players)
    _discovered_players = players


async def main():
    await _auto_discover()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
