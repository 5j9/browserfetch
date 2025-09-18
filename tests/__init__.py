from functools import partial
from json import loads

from browserfetch import fetch
from browserfetch.__main__ import read_js

js: str = read_js('async function generateHostName() { return "test" };')


captured_requests = []
fetch = partial(fetch, host='test')


def assert_equal_requests():
    bf_request, pr_request = captured_requests
    pr_headers = pr_request['headers']
    bf_headers = bf_request['headers']

    assert bf_request['method'] == pr_request['method']
    assert bf_request['query'] == pr_request['query']

    is_json = bf_headers.get('Content-Type') == 'application/json'

    if is_json:
        assert loads(bf_request['body']) == loads(pr_request['body'])
    else:
        assert bf_request['body'] == pr_request['body'], (
            f'\n{pr_request['body']=}\n{bf_request['body']=}'
        )

    for ignore_header in (
        'Accept-Encoding',
        'Accept-Language',
        'Sec-Fetch-Dest',
        'Sec-Fetch-Mode',
        'Sec-Fetch-Site',
        'sec-ch-ua',
        'sec-ch-ua-mobile',
        'sec-ch-ua-platform',
        'Origin',
    ):
        pr_headers.pop(ignore_header, None)
        bf_headers.pop(ignore_header, None)
    if is_json:
        del pr_headers['Content-Length']
        del bf_headers['Content-Length']
    assert pr_headers == bf_headers, f'\n{pr_headers=}\n{bf_headers=}'
