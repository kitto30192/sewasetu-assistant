"""SSE transport runner compatible with the local MCP server stack."""

import asyncio

import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route


def run_sse(mcp_server, port: int) -> None:
    """Serve a FastMCP 1.x server over SSE without Route response adaptation."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server._mcp_server.run(
                streams[0],
                streams[1],
                mcp_server._mcp_server.create_initialization_options(),
            )
        return Response()

    application = Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ])
    config = uvicorn.Config(application, host="0.0.0.0", port=port, log_level="info")
    asyncio.run(uvicorn.Server(config).serve())
