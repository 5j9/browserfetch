__version__ = '0.4.0'

import atexit
from asyncio import Lock, Queue, gather, get_event_loop, wait_for
from dataclasses import dataclass
from json import dumps, loads
from logging import getLogger
from typing import Any
from urllib.parse import urlencode

from aiohttp.web import Application, RouteTableDef, WebSocketResponse
from aiohttp.web_runner import AppRunner, TCPSite

logger = getLogger(__name__)
# maps each domain the queue object of that domain
queues: dict[str, Queue] = {}
# maps each lock id to either the active lock or the resolved response
locks: dict[int, Lock | dict] = {}


class BrowserError(Exception):
    pass


@dataclass(slots=True, weakref_slot=True)
class Response:
    """
    For the meaning of attributes see:
    https://developer.mozilla.org/en-US/docs/Web/API/Response
    """

    body: bytes
    ok: bool
    redirected: bool
    status: int
    status_text: str
    type: str
    url: str
    headers: dict

    def text(self, encoding=None, errors='strict') -> str:
        return self.body.decode(encoding or 'utf-8', errors)

    def json(self, encoding=None, errors='strict'):
        if encoding is None:
            return loads(self.body)
        return loads(self.text(encoding=encoding, errors=errors))


def extract_host(url: str) -> str:
    return url.partition('//')[2].partition('/')[0]


async def send_requests(q, ws):
    while True:
        url, options, lock_id, timeout, body = await q.get()
        request_blob = dumps(
            {
                'url': url,
                'options': options,
                'lock_id': lock_id,
                'timeout': timeout,
            }
        ).encode()
        if body is not None:
            request_blob += b'\0' + body
        await ws.send_bytes(request_blob)


async def receive_responses(ws: WebSocketResponse):
    while True:
        blob = await ws.receive_bytes()
        json_blob, _, body = blob.partition(b'\0')
        j = loads(json_blob)
        j['body'] = body
        lock_id = j.pop('lock_id')
        try:
            lock = locks[lock_id]
        except KeyError:  # lock has reached timeout already
            continue
        locks[lock_id] = j
        lock.release()


routes = RouteTableDef()


@routes.get('/ws')
async def _(request):
    ws = WebSocketResponse()
    await ws.prepare(request)

    host = await ws.receive_str()
    logger.info('registering host %s', host)
    q = queues.get(host) or queues.setdefault(host, Queue())

    await gather(send_requests(q, ws), receive_responses(ws))


async def fetch(
    url: str,
    *,
    params: dict = None,
    body: bytes = None,
    timeout: int | float = None,
    options: dict = None,
    host=None,
) -> Response:
    """Fetch using browser fetch API available on host.

    :param url: the URL of the resource you want to fetch.
    :param params: parameters to be url-encoded and added to url.
    :param body: the body of the request (do not add to options).
    :param timeout: timeout in seconds (do not add to options).
    :param options: See https://developer.mozilla.org/en-US/docs/Web/API/fetch
    :param host: `location.host` of the tab that is supposed to handle this
        request.
    :return: a dict of response values.
    """
    if params is not None:
        url += urlencode(params)

    if host is None:
        host = extract_host(url)
    q = queues.get(host) or queues.setdefault(host, Queue())
    lock = Lock()
    lock_id = id(lock)
    locks[lock_id] = lock
    await lock.acquire()

    await q.put((url, options, lock_id, timeout, body))

    try:
        await wait_for(lock.acquire(), timeout)
    except TimeoutError:
        locks.pop(lock_id, None)
        raise

    j = locks.pop(lock_id)
    if (err := j.get('error')) is not None:
        raise BrowserError(err)

    return Response(**j)


async def get(
    url: str,
    *,
    params: dict = None,
    options: dict = None,
    host: str = None,
    timeout: int | float = None,
) -> Response:
    if options is None:
        options = {'method': 'GET'}
    else:
        options['method'] = 'GET'
    return await fetch(
        url, options=options, host=host, timeout=timeout, params=params
    )


async def post(
    url: str,
    *,
    params: dict = None,
    body: bytes = None,
    data: dict = None,
    json=None,
    timeout: int | float = None,
    options: dict = None,
    host: str = None,
) -> Response:
    if options is None:
        options: dict[str, Any] = {'method': 'POST'}
    else:
        options['method'] = 'POST'

    if json is not None:
        assert body is None
        body = dumps(json).encode()
        headers = options.setdefault('headers', {})
        headers['Content-Type'] = 'application/json'

    if data is not None:
        assert body is None
        body = urlencode(data).encode()
        headers = options.setdefault('headers', {})
        headers['Content-Type'] = 'application/x-www-form-urlencoded'

    return await fetch(
        url,
        options=options,
        host=host,
        timeout=timeout,
        body=body,
        params=params,
    )


app = Application()
app.add_routes(routes)
app_runner = AppRunner(app)


@atexit.register
def shutdown_server():
    loop = get_event_loop()
    logger.info('waiting for app_runner.cleanup()')
    loop.run_until_complete(app_runner.cleanup())


async def start_server(*, host='127.0.0.1', port=9404):
    await app_runner.setup()
    site = TCPSite(app_runner, host, port)
    await site.start()
    logger.info('server started at http://%s:%s', host, port)
