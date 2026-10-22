"""Starts the back inside the desktop app (PyInstaller bundle): Electron gives the port and the folders by environment."""
import os

import uvicorn

from app.main import app

uvicorn.run(app, host="127.0.0.1", port=int(os.environ["PORT"]), log_level="warning", loop="asyncio", http="h11")
