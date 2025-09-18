from asyncio import Future

from playwright.async_api import (
    Browser,
    ConsoleMessage,
    Page,
    async_playwright,
)
from pytest_asyncio import fixture as async_fixture

from browserfetch import evaluate, hosts, start_server
from browserfetch.__main__ import read_js

js = read_js('async function generateHostName() { return "test" };')


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


async def test_eval_sync_func(page):
    assert await evaluate('() => { return 42}', host='test') == 42


async def test_eval_async_func(page: Page):
    string = 'async () => {return 11}'
    assert await page.evaluate(string) == 11
    assert await evaluate(string, host='test') == 11


async def test_eval_promise(page):
    assert (
        await evaluate('new Promise((resolve) => resolve(7));', host='test')
        == 7
    )


async def test_eval_sync_func_with_arg(page):
    assert await evaluate('(a) => { return a + 7}', host='test', arg=13) == 20


async def test_eval_async_func_with_arg(page: Page):
    string = 'async (a) => {return a + 11}'
    assert await page.evaluate(string, 3) == 14
    assert await evaluate(string, host='test', arg=3) == 14


async def test_close_ws_on_connection_from_same_domain(
    page: Page, browser: Browser
):
    future_console_msg: Future[ConsoleMessage] = Future()
    assert await evaluate('1', host='test') == 1
    test_host = hosts['test']
    page2 = await browser.new_page()
    page2.on('console', lambda msg: future_console_msg.set_result(msg))
    await page2.evaluate(js)
    msg = await future_console_msg
    assert (
        msg.text == 'websocket closed. reason:'
        ' a host with the name `test` is already registered'
    )
    # assert host has not changed
    assert hosts['test'] is test_host
    # check that eval still works as expected
    assert await evaluate('2', host='test') == 2
