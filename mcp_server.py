"""Read-only MCP interface to tracker history. No Instagram credentials exposed."""
import json
from mcp.server.fastmcp import FastMCP
import tracker

mcp = FastMCP('Instagram tracker')

@mcp.tool()
def tracker_status() -> dict:
    """Read target, last successful check, pause state and pending alert count."""
    return tracker.status()

@mcp.tool()
def recent_snapshots(limit: int = 10) -> list:
    """Read recent saved snapshots, including follower/following usernames and IDs."""
    with tracker.database() as db:
        rows = db.execute('SELECT at,data FROM snapshots ORDER BY id DESC LIMIT ?',
                          (min(max(limit, 1), 30),)).fetchall()
    return [{'at': at, **json.loads(data)} for at, data in rows]

if __name__ == '__main__':
    mcp.run(transport='stdio')
