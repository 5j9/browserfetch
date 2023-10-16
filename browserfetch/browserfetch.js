// ==UserScript==
// @name        browserfetch
// @namespace   https://github.com/5j9/browserfetch
// @match       https://example.com/
// ==/UserScript==
(() => {
    var ws = new WebSocket("ws://127.0.0.1:9404/ws");

    ws.onopen = () => {
        ws.send(location.host);
    }
    ws.onmessage = async (evt) => {
        var j = JSON.parse(evt.data);
        var r = await fetch(j['url'], j['options']);
        var jsonBlob = new TextEncoder().encode(JSON.stringify({
            'lock_id': j['lock_id'],
            'headers': Object.fromEntries([...r.headers]),
            'ok': r.ok,
            'redirected': r.redirected,
            'status': r.status,
            'status_text': r.statusText,
            'type': r.type,
            'url': r.url
        }));
        blob = new Blob([jsonBlob, "\0", await r.blob()]);
        ws.send(blob);
    };

    ws.onclose = function () {
        console.error('browserfetch: WebSocket was closed');
    };
})();
