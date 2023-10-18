// ==UserScript==
// @name        browserfetch
// @namespace   https://github.com/5j9/browserfetch
// @match       https://example.com/
// ==/UserScript==
(() => {
    function connect() {
        var ws = new WebSocket("ws://127.0.0.1:9404/ws");

        ws.onopen = () => {
            ws.send(location.host);
        }

        ws.onclose = function () {
            console.error('browserfetch: WebSocket was closed; will retry in 5 seconds');
            setTimeout(connect, 5000);
        };

        ws.onmessage = async (evt) => {
            var returnData, responseBlob;
            var j = JSON.parse(evt.data);
            if (j['timeout']) {
                var signal = AbortSignal.timeout(j['timeout'] * 1000);
                if (j['options']) {
                    j['options'].signal = signal;
                } else {
                    j['options'] = { 'signal': signal };
                }
            }
            try {
                var r = await fetch(j['url'], j['options']);
                var returnData = {
                    'lock_id': j['lock_id'],
                    'headers': Object.fromEntries([...r.headers]),
                    'ok': r.ok,
                    'redirected': r.redirected,
                    'status': r.status,
                    'status_text': r.statusText,
                    'type': r.type,
                    'url': r.url
                };
                responseBlob = await r.blob();
            } catch (err) {
                returnData = {
                    'lock_id': j['lock_id'],
                    'error': err.toString()
                };
                responseBlob = "";
            };
            ws.send(new Blob([new TextEncoder().encode(JSON.stringify(returnData)), "\0", responseBlob]));
        }
    };

    connect();
})();
