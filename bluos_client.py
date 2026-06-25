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

    async def delete_preset(self, preset_id: int) -> dict:
        await self._get("/SetPreset", params={"id": preset_id, "delete": 1})
        return {"result": "deleted", "preset_id": preset_id}

    async def browse_presets(self, url: str = None, service: str = None) -> dict:
        if url is None:
            root = await self._get("/RadioBrowse", params={"service": "Presets"})
        else:
            params = {"url": url}
            if service:
                params["service"] = service
            root = await self._get("/RadioBrowse", params=params)

        items = []
        for item in root.findall("item"):
            items.append({
                "text": item.get("text"),
                "type": item.get("type"),
                "url": item.get("URL"),
                "service": item.get("service"),
                "key": item.get("key"),
                "image": item.get("image"),
            })
        return {"items": items}

    async def save_preset(self, preset_id: int, name: str, encoded_url: str, image: str = None) -> dict:
        params = {"id": preset_id, "name": name, "encoded_url": encoded_url}
        if image:
            params["image"] = image
        await self._get("/SetPreset", params=params)
        return {"result": "saved", "preset_id": preset_id, "name": name}

    async def save_preset_from_status(self, preset_id: int, name: str = None) -> dict:
        status = await self._get("/Status")
        source_url = (
            status.findtext("fn")
            or status.findtext("trackstationid")
            or status.findtext("streamUrl")
        )
        if not source_url:
            return {"error": "Nothing is playing or the current source cannot be saved as a preset."}
        if not name:
            artist = status.findtext("artist")
            title = status.findtext("name")
            if artist and title:
                name = f"{artist} - {title}"
            elif title:
                name = title
            else:
                name = f"Preset {preset_id}"
        image = status.findtext("image")
        params = {"id": preset_id, "name": name, "encoded_url": source_url}
        if image:
            params["image"] = image
        await self._get("/SetPreset", params=params)
        return {"result": "saved", "preset_id": preset_id, "name": name}

    async def get_music_services(self) -> list[dict]:
        root = await self._get("/ui/Search", params={"playnum": 1})
        services = []
        selector = root.find("selectorMenu")
        if selector is not None:
            for item in selector.findall("item"):
                action = item.find("action")
                if action is not None:
                    uri = action.get("URI", "")
                    # extract service= param from URI
                    for part in uri.split("&"):
                        if part.startswith("service=") or part.startswith("/ui/Search?service="):
                            service_id = part.split("service=")[-1]
                            services.append({"name": item.get("text"), "service": service_id})
                            break
        return services

    async def search_music(self, query: str, service: str, type: str) -> dict:
        endpoint_map = {"albums": "/Albums", "songs": "/Songs", "artists": "/Artists"}
        endpoint = endpoint_map.get(type)
        if not endpoint:
            return {"error": f"type must be one of: {', '.join(endpoint_map)}"}

        root = await self._get(endpoint, params={"expr": f'"{query}"', "service": service})

        if type == "albums":
            items = []
            for album in root.findall("album"):
                albumid = album.get("albumid")
                items.append({
                    "title": album.findtext("title"),
                    "artist": album.findtext("art"),
                    "date": album.get("date"),
                    "tracks": album.get("tracks"),
                    "uri": f"/Albums?service={service}&albumid={albumid}",
                    "image": f"/Artwork?service={service}&albumid={albumid}" if albumid else None,
                })
            items.sort(key=lambda a: a["date"] or "", reverse=True)
            return {"type": "albums", "total": len(items), "results": items}

        if type == "songs":
            items = []
            for song in root.findall(".//song"):
                fn = song.findtext("fn")
                songid = song.findtext("songid") or (fn.split(":")[-1] if fn else None)
                items.append({
                    "title": song.findtext("title"),
                    "artist": song.findtext("art"),
                    "album": song.findtext("alb"),
                    "uri": f"/Add?playnow=1&file={fn}" if fn else None,
                    "image": f"/Artwork?service={service}&songid={service}%3A{songid}" if songid else None,
                })
            return {"type": "songs", "total": len(items), "results": items}

        if type == "artists":
            items = []
            for artist in root.findall("art"):
                items.append({
                    "name": artist.text,
                    "uri": f"/Artists?service={service}&artistid={artist.get('artistid')}",
                })
            return {"type": "artists", "total": len(items), "results": items}

    async def list_local_playlists(self) -> dict:
        root = await self._get("/Playlists", params={"service": "LocalMusic"})
        playlists = []
        for name_el in root.findall("name"):
            name = name_el.text
            if name:
                playlists.append({"id": name, "name": name})
        return {"playlists": playlists}

    async def play_local_playlist(self, playlist_id: str) -> dict:
        await self._get("/Add", params={
            "service": "LocalMusic",
            "playnow": 1,
            "playlistid": playlist_id,
            "all": 1,
        })
        return {"result": "playing", "playlist_id": playlist_id}

    async def save_local_playlist_as_preset(self, playlist_id: str, preset_id: int, name: str = None) -> dict:
        root = await self._get("/Playlists", params={"service": "LocalMusic"})

        playlist_name = None
        image_url = None
        for name_el in root.findall("name"):
            if name_el.text == playlist_id:
                playlist_name = name_el.text
                image_url = name_el.get("image")
                break

        if not name:
            name = playlist_name or f"Playlist {playlist_id}"

        from urllib.parse import quote
        encoded_url = f"/Load?name={quote(playlist_id)}"

        params = {"id": preset_id, "name": name, "encoded_url": encoded_url}
        if image_url:
            params["image"] = image_url

        await self._get("/SetPreset", params=params)
        return {"result": "saved", "preset_id": preset_id, "name": name, "encoded_url": encoded_url, "image": image_url}

    async def queue_remove(self, index: int) -> dict:
        root = await self._get("/Delete", params={"id": index})
        return {"result": "removed", "length": root.get("length")}

    async def queue_reorder(self, from_index: int, to_index: int) -> dict:
        await self._get("/Move", params={"old": from_index, "new": to_index})
        return {"result": "reordered"}

    async def queue_clear(self) -> dict:
        await self._get("/Clear")
        return {"result": "cleared"}

    async def queue_save(self, name: str) -> dict:
        await self._get("/Save", params={"name": name})
        return {"result": "saved", "name": name}

    async def play_music(self, uri: str, add_to_queue: bool = False) -> dict:
        # Songs: uri is already /Add?playnow=1&file=...
        if uri.startswith("/Add"):
            if add_to_queue:
                # Strip playnow=1 and just add to queue
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(uri)
                fn = parse_qs(parsed.query).get("file", [None])[0]
                if fn:
                    root = await self._get("/Add", params={"file": fn})
                    return {"result": "queued", "queue_length": root.get("length")}
            root = await self._get(uri)
            return {"result": "playing", "queue_length": root.get("length")}

        # Albums: uri is /Albums?service=X&albumid=Y — fetch tracks and queue them
        if "/Albums?" in uri:
            params = dict(p.split("=") for p in uri.split("?")[1].split("&") if "=" in p)
            service = params.get("service")
            albumid = params.get("albumid")
            songs_root = await self._get("/Songs", params={"service": service, "albumid": albumid})
            album_el = songs_root.find("album")
            if album_el is None:
                return {"error": "No tracks found for album"}
            songs = album_el.findall("song")
            if not songs:
                return {"error": "Album has no tracks"}
            first_fn = songs[0].findtext("fn")
            if add_to_queue:
                # Add all tracks to queue without starting playback
                await self._get("/Add", params={"file": first_fn})
            else:
                await self._get("/Add", params={"playnow": 1, "file": first_fn})
            for song in songs[1:]:
                fn = song.findtext("fn")
                if fn:
                    await self._get("/Add", params={"file": fn})
            return {
                "result": "queued album" if add_to_queue else "playing album",
                "tracks_queued": len(songs),
                "first_track": songs[0].findtext("title"),
            }

        return {"error": f"Unsupported URI type: {uri}"}
