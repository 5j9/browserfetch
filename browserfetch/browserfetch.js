// ==UserScript==
// @name        browserfetch
// @namespace   https://github.com/5j9/browserfetch
// @match       https://example.com/
// @grant       GM_registerMenuCommand
// ==/UserScript==
(() => {
    function connect() {
        var ws = new WebSocket("ws://127.0.0.1:9404/ws");
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
            ws.send(location.host);
        }

        ws.onclose = function () {
            console.error('browserfetch: WebSocket was closed; will retry in 5 seconds');
            setTimeout(connect, 5000);
        };

        ws.onmessage = async (evt) => {
            var returnData, responseBlob, body, jArray;
            var requestArray = new Uint8Array(evt.data);
            var nullIndex = requestArray.indexOf(0);
            if (nullIndex === -1) {
                body = null;
                jArray = requestArray;
            } else {
                body = requestArray.slice(nullIndex + 1);
                jArray = requestArray.slice(0, nullIndex)
            }
            var j = JSON.parse(new TextDecoder().decode(jArray));
            var options = j['options'] || {};

            if (j['timeout']) {
                options.signal = AbortSignal.timeout(j['timeout'] * 1000);
            }

            if (body !== null) {
                options.body = body;
            }

            try {
                var r = await fetch(j['url'], options);
                returnData = {
                    'event_id': j['event_id'],
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
                    'event_id': j['event_id'],
                    'error': err.toString()
                };
                responseBlob = "";
            };
            ws.send(new Blob([new TextEncoder().encode(JSON.stringify(returnData)), "\0", responseBlob]));
        }
    };

    if (window.GM_registerMenuCommand) {
        GM_registerMenuCommand(
            'connect to browserfetch',
            connect
        );
    } else {
        connect();
    }
})();
