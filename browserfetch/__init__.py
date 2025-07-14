__version__ = '0.13.0'
__all__ = [
    'BrowserError',
    'Response',
    'evaluate',
    'fetch',
    'get',
    'post',
    'start_server',
]
import atexit
from asyncio import (
    AbstractEventLoop,
    Event,
    Task,
    get_running_loop,
    wait_for,
)
from collections import defaultdict
from dataclasses import dataclass
from functools import partial as _partial
from html import escape
from json import dumps as _dumps, loads as _loads
from logging import getLogger
from typing import Any as _Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aiohttp import ClientSession, ClientWebSocketResponse
from aiohttp.web import (
    Application,
    Request,
    Response as _Response,
    RouteTableDef,
    WebSocketResponse,
)
from aiohttp.web_runner import AppRunner, TCPSite

logger = getLogger(__name__)
# maps host to its host_ready event or its websocket
hosts: defaultdict[
    str, Event | WebSocketResponse | ClientWebSocketResponse
] = defaultdict(Event)

# maps response event id to its response event or response dict
responses: dict[int, Event | dict] = {}

_jdumps = _partial(_dumps, separators=(',', ':'), ensure_ascii=False)


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
            return _loads(self.body)
        return _loads(self.text(encoding=encoding, errors=errors))


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

    bytes_ = _jdumps(data).encode()
    if body is not None:
        bytes_ += b'\0' + body

    value = hosts[host]
    match value:
        case Event():
            # wait for the Event to be turned into a websocket response
            await value.wait()
            ws = hosts[host]
            await ws.send_bytes(bytes_)  # type: ignore
        case WebSocketResponse() | ClientWebSocketResponse():
            await value.send_bytes(bytes_)

    try:
        await wait_for(response_ready.wait(), data['timeout'])
    except TimeoutError:
        responses.pop(event_id, None)
        raise

    # this must return a dict at this point, not an Event
    return responses.pop(event_id)  # type: ignore


async def receive_responses(ws: WebSocketResponse | ClientWebSocketResponse):
    while True:
        blob = await ws.receive_bytes()
        json_blob, _, body = blob.partition(b'\0')
        j = _loads(json_blob)
        j['body'] = body
        event_id = j.pop('event_id')
        try:
            # We expect only one response to be recieved for each event,
            # therefore this must be an Event, not a dict.
            response_ready: Event = responses[event_id]  # type: ignore
        except KeyError:  # lock has reached timeout already
            continue
        responses[event_id] = j
        response_ready.set()


routes = RouteTableDef()
PROTOCOL = '3'


@routes.get('/ws')
async def _(request):
    ws = WebSocketResponse()
    await ws.prepare(request)

    version, _, host = (await ws.receive_str()).partition(' ')
    assert version == PROTOCOL, (
        f'JavaScript protocol version: {version}, expected: {PROTOCOL}'
    )
    logger.info('registering host %s', host)

    ws_or_event = hosts[host]
    if not isinstance(ws_or_event, Event):
        await ws.send_bytes(
            _dumps(
                {
                    'action': 'close_ws',
                    'reason': f'a host with the name `{host}` is already registered',
                }
            ).encode()
        )
        await ws.close()
        return ws

    hosts[host] = ws
    ws_or_event.set()

    try:
        await receive_responses(ws)
    except TypeError:
        logger.info('WebSocket was closed by browser')
        hosts[host] = Event()
    return ws


@routes.get('/relay')
async def _(request: Request) -> WebSocketResponse:
    ws = WebSocketResponse()
    await ws.prepare(request)

    while True:
        try:
            bytes_ = await ws.receive_bytes()
        except TypeError:  # ws closed
            return ws
        data, null, body = bytes_.partition(b'\0')
        data = _loads(data)
        relay_event_id = data['event_id']

        try:
            r: dict = await _request(
                data.pop('host'), data, body if null else None
            )
        except TimeoutError:
            r = {'error': 'TimeoutError in relay'}

        r['event_id'] = relay_event_id
        body = r.pop('body')
        await ws.send_bytes(_jdumps(r).encode() + b'\0' + body)


@routes.get('/')
async def _(_) -> _Response:
    hosts_html = '\n'.join(
        [f'<li>{k}: {escape(str(v))}</li>' for k, v in hosts.items()]
    )
    responses_html = '\n'.join(
        [f'<li>{k}: {escape(str(v))}</li>' for k, v in responses.items()]
    )
    return _Response(
        body='<meta charset="utf-8">\n<title>browserfetch</title>\n'
        f'Hosts:\n{hosts_html}\n'
        f'Responses:\n{responses_html}',
        content_type='text/html',
    )


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
    expression: str,
    /,
    *,
    host: str,
    timeout: int | float = 95,
    arg: _Any = None,
):
    """Evaluate string in browser context and return JSON.stringify(result)."""
    data = {'action': 'eval', 'string': expression, 'timeout': timeout}
    if arg is not None:
        data['arg'] = arg
    d = await _request(host, data, None)
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
        parsed_url = urlparse(url)
        url = urlunparse(
            parsed_url._replace(
                query=urlencode(
                    [*parse_qsl(parsed_url.query), *params.items()]
                )
            )
        )

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
    data=None,
    form: dict | None = None,
    timeout: int | float = 95,
    options: dict | None = None,
    host: str | None = None,
) -> Response:
    if options is None:
        options = {'method': 'POST'}
    else:
        options['method'] = 'POST'

    if data is not None:
        if isinstance(data, str):
            body = data.encode()
        elif isinstance(data, bytes):
            body = data
        else:
            body = _jdumps(data).encode()
            headers = options.setdefault('headers', {})
            headers['Content-Type'] = 'application/json'
    elif form is not None:
        body = urlencode(form).encode()
        headers = options.setdefault('headers', {})
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    else:
        body = None

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


def _cancel_relay_task(loop: AbstractEventLoop, task: Task):
    logger.info('cancelling relay task')
    task.cancel()


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
        logger.info('server started at http://%s:%s', host, port)
