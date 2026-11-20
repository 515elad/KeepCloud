"""ASGI entry point:  uvicorn keepair.gateway.main:app"""

from keepair.gateway.app import create_gateway_app

app = create_gateway_app()
