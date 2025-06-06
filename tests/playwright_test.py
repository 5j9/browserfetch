from playwright.async_api import Page, async_playwright
from pytest_asyncio import fixture as async_fixture

from browserfetch import evaluate, start_server
from browserfetch.__main__ import read_js

js = read_js('async function generateHostName() { return "test" };')


@async_fixture(scope='session')
async def page():
    await start_server()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        async with browser:
            page = await browser.new_page()
            await page.add_script_tag(content=js)
            yield page


async def test_eval_sync_func(page):
    assert await evaluate('() => { return 42}', 'test') == 42


async def test_eval_async_func(page: Page):
    string = 'async () => {return 11}'
    assert await page.evaluate(string) == 11
    assert await evaluate(string, 'test') == 11


async def test_eval_promise(page):
    assert await evaluate('new Promise((resolve) => resolve(7));', 'test') == 7
