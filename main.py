import uvicorn
import os
from backend.main import app

if __name__ == "__main__":
    is_prod = os.environ.get("REPL_DEPLOYMENT", "") == "1"
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        access_log=not is_prod,
        log_level="info",
        timeout_keep_alive=30,
    )
