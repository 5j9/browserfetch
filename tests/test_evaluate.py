from asyncio import Future
from functools import partial

from playwright.async_api import Browser, ConsoleMessage, Page

from browserfetch import evaluate as orig_evaluate, hosts
from tests import js

evaluate = partial(orig_evaluate, host='test')


async def test_eval_sync_func(page):
    assert await evaluate('() => { return 42}') == 42


async def test_eval_async_func(page: Page):
    string = 'async () => {return 11}'
    assert await page.evaluate(string) == 11
    assert await evaluate(string) == 11


async def test_eval_promise(page):
    assert await evaluate('new Promise((resolve) => resolve(7));') == 7


async def test_eval_sync_func_with_arg(page):
    assert await evaluate('(a) => { return a + 7}', arg=13) == 20


async def test_eval_async_func_with_arg(page: Page):
    string = 'async (a) => {return a + 11}'
    assert await page.evaluate(string, 3) == 14
    assert await evaluate(string, arg=3) == 14


async def test_close_ws_on_connection_from_same_domain(
    page: Page, browser: Browser
):
    future_console_msg: Future[ConsoleMessage] = Future()
    assert await evaluate('1') == 1
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
    assert await evaluate('2') == 2
