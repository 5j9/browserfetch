from contextlib import suppress
from unittest.mock import Mock, patch

from browserfetch import fetch

request_mock = Mock()


@patch('browserfetch._request', new=request_mock)
async def test_params():
    with suppress(TypeError):
        await fetch(
            url='http://stackoverflow.com/search?q=question',
            params={'lang': 'en', 'tag': 'python', 'q': True},
        )
    request_mock.assert_called_once_with(
        None,  # host
        {
            'action': 'fetch',
            'url': 'http://stackoverflow.com/search?q=question&lang=en&tag=python&q=True',
            'options': None,
            'timeout': 95,
        },  # data
        None,  # body
    )
