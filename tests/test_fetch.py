from playwright.async_api import Page

from tests import assert_equal_requests, fetch


async def test_post_str_data(client_url, page: Page):
    await fetch(client_url, method='post', data='test data')
    await page.request.fetch(client_url, method='post', data='test data')
    assert_equal_requests()


async def test_post_bytes_data(client_url, page: Page):
    await fetch(client_url, method='post', data=b'test data')
    await page.request.fetch(client_url, method='post', data=b'test data')
    assert_equal_requests()


async def test_post_dict_data(client_url, page: Page):
    await fetch(client_url, method='post', data={'x': 'y'})
    await page.request.fetch(client_url, method='post', data={'x': 'y'})
    assert_equal_requests()


async def test_get_with_params(client_url, page: Page):
    params: dict = {'param?': 'value?', 'param&': 'value&'}
    await fetch(client_url, params=params)
    await page.request.fetch(client_url, params=params)
    assert_equal_requests()


async def test_headers(client_url, page: Page):
    headers: dict[str, str] = {
        # 'X-Custom-Header': 'my-value',
        'Authorization': 'Bearer 123',
    }
    await fetch(client_url, headers=headers)
    await page.request.fetch(client_url, headers=headers)
    assert_equal_requests()


async def test_post_with_json_headers(client_url, page: Page):
    headers = {'Content-Type': 'application/json'}
    data = {'key': 'value'}
    await fetch(client_url, method='post', data=data, headers=headers)
    await page.request.fetch(
        client_url, method='post', data=data, headers=headers
    )
    assert_equal_requests()


async def test_post_form_data(client_url, page: Page):
    form_data: dict = {'name': 'test', 'email': 'test@example.com'}
    await fetch(url=client_url, method='post', form=form_data)
    await page.request.fetch(client_url, method='post', form=form_data)
    assert_equal_requests()
