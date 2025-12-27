import os
import sys
import anyio
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream


async def run_session(
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
):
    async with ClientSession(read_stream, write_stream) as session:
        print("[client] initializing...")
        await session.initialize()
        print("[client] initialized.")
        tools = await session.list_tools()
        print("[client] tools:")
        for t in tools.tools:
            print(f" - {t.name}")
        # tentar chamar test_connection
        try:
            print("[client] calling tool: test_connection")
            result = await session.call_tool("test_connection", {})
            print("[client] test_connection result:")
            print(result)
        except Exception as e:
            print("[client] test_connection error:", e)


async def main():
    python = sys.executable
    params = StdioServerParameters(
        command=python,
        args=["server.py"],
        env=dict(os.environ),
    )

    async with stdio_client(params) as streams:
        await run_session(*streams)


if __name__ == "__main__":
    anyio.run(main, backend="asyncio")
