import asyncio
import xml.etree.ElementTree as ET

import httpx
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf


def discover_bluos_players(timeout: float = 5.0) -> list[dict]:
    """Synchronously discover BluOS players on the local network via mDNS."""
    found = []
    zc = Zeroconf()

    def on_service_state_change(zeroconf, service_type, name, state_change):
        if state_change is ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                ip = ".".join(str(b) for b in info.addresses[0]) if info.addresses else None
                found.append({"ip": ip, "port": info.port})

    browser = ServiceBrowser(zc, "_musc._tcp.local.", handlers=[on_service_state_change])
    import time
    time.sleep(timeout)
    zc.close()

    # Fetch friendly names from each player's SyncStatus
    return asyncio.run(_enrich_players(found))


async def _enrich_players(players: list[dict]) -> list[dict]:
    async def fetch_name(player: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"http://{player['ip']}:{player['port']}/SyncStatus")
                root = ET.fromstring(r.text)
                player["name"] = root.get("name", player["ip"])
        except Exception:
            player["name"] = player["ip"]
        return player

    return list(await asyncio.gather(*[fetch_name(p) for p in players]))


class BluOSClient:
    def __init__(self, player_ip: str):
        self.player_ip = player_ip
        self.base_url = f"http://{player_ip}:11000"

    async def _get(self, path: str, params: dict = None) -> ET.Element:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            return ET.fromstring(response.text)

    async def get_status(self) -> dict:
        root = await self._get("/Status")
        return {
            "state": root.findtext("state"),
            "artist": root.findtext("artist"),
            "album": root.findtext("album"),
            "name": root.findtext("name"),
            "volume": root.findtext("volume"),
            "quality": root.findtext("quality"),
            "service": root.findtext("service"),
            "totlen": root.findtext("totlen"),
            "secs": root.findtext("secs"),
        }

    async def play(self) -> dict:
        root = await self._get("/Play")
        return {"result": root.text or "ok"}

    async def pause(self) -> dict:
        root = await self._get("/Pause")
        return {"result": root.text or "ok"}

    async def skip(self) -> dict:
        root = await self._get("/Skip")
        return {"result": root.text or "ok"}

    async def back(self) -> dict:
        root = await self._get("/Back")
        return {"result": root.text or "ok"}

    async def set_volume(self, level: int) -> dict:
        root = await self._get("/Volume", params={"level": level})
        return {"volume": root.findtext("volume") or str(level)}

    async def get_queue(self) -> dict:
        root = await self._get("/ui/Queue", params={"playnum": 1})
        items = []
        for item in root.findall("item"):
            items.append({
                "title": item.get("title"),
                "artist": item.get("subTitle"),
                "album": item.get("subSubTitle"),
                "duration": item.get("duration"),
                "quality": item.get("quality"),
            })
        return {
            "name": root.get("name"),
            "total": root.get("total"),
            "songs": items,
        }

    async def get_presets(self) -> list[dict]:
        root = await self._get("/Presets")
        presets = []
        for preset in root.findall("preset"):
            presets.append({
                "id": preset.get("id"),
                "name": preset.get("name"),
                "image": preset.get("image"),
            })
        return presets

    async def play_preset(self, preset_id: int) -> dict:
        root = await self._get("/Preset", params={"id": preset_id})
        return {"result": root.text or "ok"}
