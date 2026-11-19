"""ASGI entry point:  uvicorn keepair.web.main:app"""

from keepair.web.app import create_app

app = create_app()
