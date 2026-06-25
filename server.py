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


PLAYER_IP_PARAM = {
    "ip": {
        "type": "string",
        "description": "IP address of the player. Use the IP from discover_players. If omitted, uses the first discovered player.",
    }
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="discover_players",
            description="Scan the local network for BluOS players. Returns a list of players with their friendly names and IP addresses. Call this first to know which players are available.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_status",
            description="Get current track info, playback state, and volume from a BluOS player.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
        ),
        Tool(
            name="transport",
            description="Control playback on a BluOS player: play, pause, skip to next track, or go back to previous track.",
            inputSchema={
                "type": "object",
                "properties": {
                    **PLAYER_IP_PARAM,
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
                    **PLAYER_IP_PARAM,
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
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
        ),
        Tool(
            name="presets",
            description="List saved presets and radio stations, or play one by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    **PLAYER_IP_PARAM,
                    "action": {
                        "type": "string",
                        "enum": ["list", "play"],
                        "description": "list: return all presets. play: start the preset with the given id.",
                    },
                    "id": {
                        "type": "integer",
                        "description": "Preset ID to play. Required when action is 'play'.",
                    },
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="get_music_services",
            description="Get the list of music streaming services available on a BluOS player (e.g. Tidal, Qobuz, Amazon). Use this to know which services to search.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
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
                    **PLAYER_IP_PARAM,
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
                    **PLAYER_IP_PARAM,
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
        elif name == "presets":
            if arguments["action"] == "list":
                result = await _client(arguments).get_presets()
            else:
                result = await _client(arguments).play_preset(arguments["id"])
        elif name == "get_music_services":
            result = await _client(arguments).get_music_services()
        elif name == "search_music":
            result = await _client(arguments).search_music(arguments["query"], arguments["service"], arguments["type"])
        elif name == "play_music":
            result = await _client(arguments).play_music(arguments["uri"], arguments.get("add_to_queue", False))
        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        result = {"error": str(e)}

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


if __name__ == "__main__":
    asyncio.run(main())
