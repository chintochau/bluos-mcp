# BluOS MCP

Control BluOS music players with Claude. Players are auto-discovered on your local network — no configuration needed.

## Install

Run this in Claude Code:

```bash
claude mcp add bluos -s user -- uvx --from git+https://github.com/chintochau/bluos-mcp.git bluos-mcp
```

Then restart Claude Code. That's it.

> **Requirement:** Your machine must be on the same local network as your BluOS players.

## What you can do

Once installed, just talk to Claude:

- "What's playing?"
- "Play my Office playlist"
- "Save this to preset 1"
- "Search for Thriller on Apple Music and play it"
- "Turn the volume up to 30"
- "Skip to the next track"
- "Save the current queue as a playlist called Friday Vibes"
