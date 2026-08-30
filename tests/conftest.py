import pytest
from tests.mock_pocketbase import MockPocketBaseServer


@pytest.fixture
def pb_server():
    with MockPocketBaseServer() as server:
        yield server
