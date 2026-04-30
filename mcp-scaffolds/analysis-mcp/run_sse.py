import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from server import mcp
mcp.settings.port = 8002
mcp.settings.host = "127.0.0.1"
mcp.run(transport="sse")
