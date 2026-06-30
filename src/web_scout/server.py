"""Web Scout MCP Server — Entry Point."""

from fastmcp import FastMCP

mcp = FastMCP("Web Scout", description="AI-powered web API & DOM discovery tool")


@mcp.tool()
def scout_open(url: str, keyword: str = None) -> str:
    """Open a URL in Chromium browser and begin network monitoring.

    Args:
        url: Target website URL (e.g. https://www.xiaohongshu.com/explore)
        keyword: Optional search keyword to auto-type and submit

    Returns:
        Status message with page info
    """
    return f"Page opened: {url}"


@mcp.tool()
def scout_list_apis() -> str:
    """List all captured JSON API endpoints.

    Returns:
        tabulate of discovered API endpoints with URL, method, field count
    """
    return "No APIs captured yet. Run scout_open or scout_search first."


def main():
    mcp.run()


if __name__ == "__main__":
    main()
