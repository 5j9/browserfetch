from asyncio import Lock, Queue, gather
from json import loads
from logging import getLogger

from aiohttp.web import Application, RouteTableDef, WebSocketResponse, run_app

logger = getLogger(__name__)
# maps each domain the queue object of that domain
queues: dict[str, Queue] = {}
# maps each lock id to either the active lock or the resolved response
locks: dict[int, Lock | dict] = {}


def extract_host(url: str) -> str:
    return url.partition('//')[2].partition('/')[0]


async def send_requests(q, ws):
    while True:
        url, options, lock = await q.get()
        await ws.send_json(
            {'url': url, 'options': options, 'lock_id': id(lock)}
        )


async def receive_responses(ws: WebSocketResponse):
    while True:
        blob = await ws.receive_bytes()
        json_blob, _, body = blob.partition(b'\0')
        j = loads(json_blob)
        j['body'] = body
        lock_id = j.pop('lock_id')
        lock = locks[lock_id]
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


async def fetch(url: str, options: dict = None, host=None) -> dict:
    """fetch using browser fetch API available on host.

    :param url: the URL of the resource you want to fetch.
    :param options: See https://developer.mozilla.org/en-US/docs/Web/API/fetch
    :param host: `location.host` of the tab that is supposed to handle this
        request.
    :return: a dict of response values.
    """
    if host is None:
        host = extract_host(url)
    q = queues.get(host) or queues.setdefault(host, Queue())
    lock = Lock()
    lock_id = id(lock)
    locks[lock_id] = lock
    await lock.acquire()

    await q.put((url, options, lock))
    async with lock:
        return locks.pop(lock_id)


app = Application()
app.add_routes(routes)


def run_server(*, host='127.0.0.1', port=9404, loop=None):
    run_app(app, host=host, port=port, loop=loop)
