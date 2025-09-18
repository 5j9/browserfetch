from aiohttp.web import Application, Request, Response
from playwright.async_api import Browser, async_playwright
from pytest_asyncio import fixture as async_fixture

from browserfetch import start_server
from tests import captured_requests, js


@async_fixture(scope='session')
async def browser():
    await start_server()
    async with async_playwright() as p:
        yield await p.chromium.launch(headless=True, channel='msedge')


@async_fixture(scope='session')
async def page(browser: Browser):
    async with browser:
        page = await browser.new_page()
        await page.add_script_tag(content=js)
        yield page


async def capture_request_details(request: Request):
    # This is a simple handler to capture request details
    if request.method != 'OPTIONS':
        request_details = {
            'method': request.method,
            'headers': dict(request.headers),
            'body': await request.text() if request.can_read_body else None,
            'query': request.query,
        }
        captured_requests.append(request_details)

    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': '*',
        'Access-Control-Allow-Headers': '*',
        'Access-Control-Allow-Credentials': 'true',
    }
    return Response(text='Success', headers=headers)


@async_fixture()
async def client_url(aiohttp_client):
    app = Application()
    app.router.add_route('*', '/test', capture_request_details)
    client = await aiohttp_client(app)
    yield str(client.make_url('/test'))
    captured_requests.clear()
