__version__ = '0.15.2.dev1'
__all__ = [
    'BrowserError',
    'Response',
    'evaluate',
    'fetch',
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
from base64 import b64decode, b64encode
from collections import defaultdict
from dataclasses import dataclass
from functools import partial as _partial
from html import escape
from json import dumps as _dumps, loads as _loads
from logging import getLogger
from typing import Any as _Any

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

    message = _jdumps(data)

    value = hosts[host]
    match value:
        case Event():
            # wait for the Event to be turned into a websocket response
            await value.wait()
            ws = hosts[host]
            await ws.send_str(message)  # type: ignore
        case WebSocketResponse() | ClientWebSocketResponse():
            await value.send_str(message)

    try:
        await wait_for(response_ready.wait(), data['timeout'])
    except TimeoutError:
        responses.pop(event_id, None)
        raise

    # this must return a dict at this point, not an Event
    return responses.pop(event_id)  # type: ignore


async def receive_responses(ws: WebSocketResponse | ClientWebSocketResponse):
    while True:
        msg = await ws.receive_str()
        j = _loads(msg)
        event_id = j.pop('event_id')

        b64_body = j.pop('bodyBase64', None)
        body_bytes = b''
        if b64_body:
            try:
                body_bytes = b64decode(b64_body)
            except Exception:
                logger.error('Failed to decode base64 body')

        j['body'] = body_bytes

        try:
            # We expect only one response to be recieved for each event,
            # therefore this must be an Event, not a dict.
            response_ready: Event = responses[event_id]  # type: ignore
        except KeyError:  # lock has reached timeout already
            continue

        responses[event_id] = j
        response_ready.set()


routes = RouteTableDef()
PROTOCOL = '5'


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
        await ws.send_str(
            _dumps(
                {
                    'action': 'close_ws',
                    'reason': f'a host with the name `{host}` is already registered',
                }
            )
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
            msg = await ws.receive_str()
        except TypeError:  # ws closed
            return ws

        data = _loads(msg)
        relay_event_id = data['event_id']
        try:
            r: dict = await _request(data.pop('host', None), data)
        except TimeoutError:
            r = {'error': 'TimeoutError in relay'}

        r['event_id'] = relay_event_id

        # Re-encode body to Base64 for the response
        # The Response object has 'body' as bytes.
        body_bytes = r.pop('body', b'')
        if body_bytes:
            r['bodyBase64'] = b64encode(body_bytes).decode('utf-8')
        else:
            r['bodyBase64'] = None

        await ws.send_str(_jdumps(r))


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
    d = await _request(host, data)
    return d['result']


async def fetch(
    url: str,
    *,
    method: str | None = None,
    params: dict | None = None,
    data: _Any = None,
    form: dict | None = None,
    timeout: int | float = 95,
    headers: dict | None = None,
    host: str | None = None,
    options: dict | None = None,
) -> Response:
    """Fetch using browser fetch API available on host.


    This function tries to be similar to Playwright's API.
    (but it's not identical)

    :param url: the URL of the resource you want to fetch.
    :param params: parameters to be url-encoded and added to url.
    :param data: the JSON-serializable body of the request.
        If data is str or bytes, `application/octet-stream` content-type
        header will be set. Otherwise, the object will be encoded and sent as
        `application/json`.
    :param form: a dict of form data to be url-encoded.
        Passing `form` will automatically set
        `application/x-www-form-urlencoded` header.
    :param timeout: timeout in seconds (do not add to options).
    :param options: See https://developer.mozilla.org/en-US/docs/Web/API/fetch
    :param host: `location.host` of the tab that is supposed to handle this
        request.
    :return: a dict of response values.
    """

    payload_data = {
        'action': 'fetch',
        'url': url,
        'method': method,
        'headers': headers,
        'options': options or {},
        'timeout': timeout,
        'params': params,
    }

    if form is not None:
        payload_data['form'] = form
    elif data is not None:
        if isinstance(data, str | bytes):
            # Handle raw binary/string data by Base64 encoding it
            if isinstance(data, str):
                data_bytes = data.encode('utf-8')
            else:
                data_bytes = data

            payload_data['bodyBase64'] = b64encode(data_bytes).decode('utf-8')

            # Ensure content type is set (unless user specified it in headers)
            if headers is None or 'Content-Type' not in headers:
                payload_data['content_type'] = 'application/octet-stream'
        else:
            # Handle JSON data
            payload_data['options']['body'] = _jdumps(data)
            payload_data['content_type'] = 'application/json'

    d = await _request(host, payload_data)

    if (err := d.get('error')) is not None:
        raise BrowserError(err)

    return Response(**d)


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
