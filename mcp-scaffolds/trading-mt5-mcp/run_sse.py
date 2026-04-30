"""SSE launcher for trading-mt5-mcp under Wine Python."""
import sys
import os

# Set working directory to the trading-mt5-mcp folder (Wine path)
mcp_dir = r"Z:\opt\trading-bot\app\mcp-scaffolds\trading-mt5-mcp"
shared_dir = r"Z:\opt\trading-bot\app\mcp-scaffolds\_shared"

sys.path.insert(0, mcp_dir)
sys.path.insert(0, shared_dir)
os.chdir(mcp_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(mcp_dir, ".env"))

from server import mcp

mcp.settings.port = 8004
mcp.settings.host = "127.0.0.1"
mcp.run(transport="sse")
