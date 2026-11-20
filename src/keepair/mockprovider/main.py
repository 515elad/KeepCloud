"""ASGI entry point:  uvicorn keepair.mockprovider.main:app --port 8090"""

from keepair.mockprovider.app import create_mock_provider

app = create_mock_provider()
