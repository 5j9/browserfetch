Fetch using your browser.

Let the browser manage cookies for you.

⚠️ Incomplete. Not tested thoroughly. Consider using `Playwright`_, especially for more complex scenarios.

Usage
-----
1. You'll run a Python script containing some code like this:

.. code-block:: python

    from asyncio import gather, new_event_loop

    from browserfetch import fetch, get, post, run_server


    async def main():
        response1, response2, reponse3 = await gather(
            get('https://example.com/path1', params={'a': 1}),
            fetch('https://example.com/image.png'),
            post('https://example.com/path2', data={'a': 1}),
        )
        # do stuff with retrieved responses


    loop = new_event_loop()
    loop.create_task(start_server())
    loop.run_until_complete(main())


2. Open your browser, goto http://example.com (perhaps solve a captcha and log in).
3. Copy the contents of `browserfetch.js`_ file and paste it in browser's console. (You can use a browser extensions like violentmonkey_/tampermonkey_ to do this step for you.)

That's it! Your Python script starts handling requests.
The browser tab should remain open of-coarse.

The server can handle multiple websocket connections from different websites simultaneously.

How it works
------------
``browserfetch`` communicates with your browser using a websocket. The ``fetch`` function just passes the request to browser and it is the browser that handles the actual request. Response data is sent back to Python using the same WebSocket connection.

Motivations
-----------
* `browser_cookie3 stopped working on Chrome-based browsers`_. There is a workaround: ShadowCopy, but it requires admin privilege.
* Another issue with browser_cookie's approach is that it retrieves cookies from cookie files, but these files are not updated instantly. Thus, you might have to wait or retry a few times before you can successfully access newly set cookies.
* ShadowCopying and File access are slow and inefficient operations.

Downsides
---------
* Setting up ``browserfetch`` is more cumbersome since it requires running a Python server and also injecting a small script into the webpage. Using ``browser_cookie3`` might be a better choice if there are many websites that you need to communicate with.

.. _playwright: https://playwright.dev/python/docs/intro
.. _`browser_cookie3 stopped working on Chrome-based browsers`: https://github.com/borisbabic/browser_cookie3/issues/180
.. _tampermonkey: https://github.com/Tampermonkey/tampermonkey
.. _violentmonkey: https://github.com/violentmonkey/violentmonkey
.. _browserfetch.js: https://github.com/5j9/browserfetch/blob/master/browserfetch/browserfetch.js
