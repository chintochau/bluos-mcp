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


def _client(arguments: dict) -> BluOSClient:
    ip = arguments.get("ip")
    if ip:
        return BluOSClient(ip)
    if _discovered_players:
        return BluOSClient(_discovered_players[0]["ip"])
    raise RuntimeError("No players found. Call discover_players first.")


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
            name="play",
            description="Start or resume playback on a BluOS player.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
        ),
        Tool(
            name="pause",
            description="Pause playback on a BluOS player.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
        ),
        Tool(
            name="skip",
            description="Skip to the next track on a BluOS player.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
        ),
        Tool(
            name="back",
            description="Go back to the previous track on a BluOS player.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
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
            name="get_presets",
            description="Get saved presets and radio stations from a BluOS player.",
            inputSchema={"type": "object", "properties": PLAYER_IP_PARAM},
        ),
        Tool(
            name="play_preset",
            description="Play a preset by its ID on a BluOS player.",
            inputSchema={
                "type": "object",
                "properties": {
                    **PLAYER_IP_PARAM,
                    "id": {
                        "type": "integer",
                        "description": "The preset ID to play.",
                    },
                },
                "required": ["id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _discovered_players

    try:
        if name == "discover_players":
            players = await asyncio.get_event_loop().run_in_executor(
                None, discover_bluos_players
            )
            _discovered_players = players
            result = {"players": players}

        elif name == "get_status":
            result = await _client(arguments).get_status()
        elif name == "play":
            result = await _client(arguments).play()
        elif name == "pause":
            result = await _client(arguments).pause()
        elif name == "skip":
            result = await _client(arguments).skip()
        elif name == "back":
            result = await _client(arguments).back()
        elif name == "set_volume":
            result = await _client(arguments).set_volume(arguments["level"])
        elif name == "get_queue":
            result = await _client(arguments).get_queue()
        elif name == "get_presets":
            result = await _client(arguments).get_presets()
        elif name == "play_preset":
            result = await _client(arguments).play_preset(arguments["id"])
        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        result = {"error": str(e)}

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _auto_discover():
    global _discovered_players

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
