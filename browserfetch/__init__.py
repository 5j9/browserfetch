__version__ = '0.9.0'

import atexit
from asyncio import (
    AbstractEventLoop,
    CancelledError,
    Event,
    Task,
    get_running_loop,
    wait_for,
)
from collections import defaultdict
from dataclasses import dataclass
from json import dumps, loads
from logging import getLogger
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientSession, ClientWebSocketResponse
from aiohttp.web import Application, RouteTableDef, WebSocketResponse
from aiohttp.web_runner import AppRunner, TCPSite

logger = getLogger(__name__)
# maps host to its host_ready event or its websocket
hosts: dict[str, Event | WebSocketResponse | ClientWebSocketResponse] = (
    defaultdict(Event)
)
# maps response event id to its response event or response dict
responses: dict[int, Event | dict] = {}


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


async def _request(
    host: str | None,
    data: dict,
    body: bytes | None,
    /,
) -> dict:
    if host is None:
        host = extract_host(data['url'])
    if _server is False:
        data['host'] = host
    response_ready = Event()
    event_id = id(response_ready)
    data['event_id'] = event_id
    responses[event_id] = response_ready

    bytes_ = dumps(data).encode()
    if body is not None:
        bytes_ += b'\0' + body

    ws = hosts[host]
    if isinstance(ws, Event):
        await ws.wait()
        ws = hosts[host]

    await ws.send_bytes(bytes_)

    try:
        await wait_for(response_ready.wait(), data['timeout'])
    except TimeoutError:
        responses.pop(event_id, None)
        raise

    return responses.pop(event_id)


async def receive_responses(ws: WebSocketResponse | ClientWebSocketResponse):
    while True:
        blob = await ws.receive_bytes()
        json_blob, _, body = blob.partition(b'\0')
        j = loads(json_blob)
        j['body'] = body
        event_id = j.pop('event_id')
        try:
            event = responses[event_id]
        except KeyError:  # lock has reached timeout already
            continue
        responses[event_id] = j
        event.set()


routes = RouteTableDef()
PROTOCOL = '2'


@routes.get('/ws')
async def _(request):
    ws = WebSocketResponse()
    await ws.prepare(request)

    host, _, version = (await ws.receive_str()).partition(' ')
    assert (
        version == PROTOCOL
    ), f'JavaScript protocol version: {version}, expected: {PROTOCOL}'
    logger.info('registering host %s', host)

    ws_or_e = hosts[host]
    hosts[host] = ws
    if isinstance(ws_or_e, Event):
        ws_or_e.set()

    try:
        await receive_responses(ws)
    except TypeError:
        logger.info('host WebSocket was closed')
        hosts[host] = Event()
    return ws


@routes.get('/relay')
async def _(request):
    ws = WebSocketResponse()
    await ws.prepare(request)

    while True:
        try:
            bytes_ = await ws.receive_bytes()
        except TypeError:  # ws closed
            return
        data, null, body = bytes_.partition(b'\0')
        data = loads(data)
        relay_event_id = data['event_id']

        try:
            r = await _request(data.pop('host'), data, body if null else None)
        except TimeoutError:
            r = {'error': 'TimeoutError in relay'}

        r['event_id'] = relay_event_id
        body = r.pop('body')
        await ws.send_bytes(dumps(r).encode() + b'\0' + body)


async def relay_client(server_host, server_port):
    async with ClientSession() as session:
        relay_url = f'ws://{server_host}:{server_port}/relay'
        async with session.ws_connect(relay_url) as ws:
            logger.info('connected to %s', relay_url)
            hosts.default_factory = lambda: ws
            for host, ws_or_e in hosts.items():
                hosts[host] = ws
                if isinstance(ws_or_e, Event):
                    ws_or_e.set()
            try:
                await receive_responses(ws)
            except TypeError:
                logger.info('relay WebSocket was closed')
                hosts.default_factory = Event
                for host, ws_or_e in hosts.items():
                    if isinstance(ws_or_e, Event):
                        ws_or_e.clear()
                    else:
                        hosts[host] = Event()
                await start_server(host=_host, port=_port)
                return


async def evaluate(
    string: str,
    host: str,
    timeout: int | float = 95,
):
    """Evaluate string in browser context and return JSON.stringify(result)."""
    d = await _request(
        host, {'action': 'eval', 'string': string, 'timeout': timeout}, None
    )
    return d['result']


async def fetch(
    url: str,
    *,
    params: dict | None = None,
    body: bytes | None = None,
    timeout: int | float = 95,
    options: dict | None = None,
    host: str | None = None,
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

    d = await _request(
        host,
        {
            'action': 'fetch',
            'url': url,
            'options': options,
            'timeout': timeout,
        },
        body,
    )

    if (err := d.get('error')) is not None:
        raise BrowserError(err)

    return Response(**d)


async def get(
    url: str,
    *,
    params: dict | None = None,
    options: dict | None = None,
    host: str | None = None,
    timeout: int | float = 95,
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
    params: dict | None = None,
    data: bytes | dict | str | None = None,
    form: dict | None = None,
    timeout: int | float = 95,
    options: dict | None = None,
    host: str | None = None,
) -> Response:
    if options is None:
        options: dict[str, Any] = {'method': 'POST'}
    else:
        options['method'] = 'POST'

    if data is not None:
        if isinstance(data, str):
            body = data.encode()
        elif isinstance(data, bytes):
            body = data
        else:
            body = dumps(data).encode()
            headers = options.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'

    if form is not None:
        assert data is None
        body = urlencode(form).encode()
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


def _shutdown_server(loop: AbstractEventLoop):
    logger.info('waiting for app_runner.cleanup()')
    loop.run_until_complete(app_runner.cleanup())


def _cancel_relay_task(loop: AbstractEventLoop, task: Task):
    logger.info('cancelling relay task')
    task.cancel()
    try:
        loop.run_until_complete(task)
    except CancelledError:
        pass


_server = False
_host = '127.0.0.1'
_port = 9404


async def start_server(*, host=_host, port=_port):
    global _server, _host, _port
    _host, _port = host, port
    loop = get_running_loop()
    await app_runner.setup()
    site = TCPSite(app_runner, host, port)
    try:
        await site.start()  # does not block
    except OSError as e:
        logger.info(
            'port %d is in use; will try to connect to existing server; %r',
            port,
            e,
        )
        relay_task = loop.create_task(relay_client(host, port))
        atexit.register(_cancel_relay_task, loop, relay_task)
    else:
        _server = True
        atexit.register(_shutdown_server, loop)
        logger.info('server started at http://%s:%s', host, port)
