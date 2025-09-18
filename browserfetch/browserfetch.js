// ==UserScript==
// @name        browserfetch
// @namespace   https://github.com/5j9/browserfetch
// @match       https://example.com/
// @grant       GM_registerMenuCommand
// ==/UserScript==
// @ts-check
(async () => {
    /**
     * @param {Uint8Array | URLSearchParams | null} body 
     * @param {any} req
     * @returns {Promise<Blob>}
     */
    async function doFetch(req, body) {
        var returnData, response, headers;
        var url = req.url;
        var options = req.options || {};

        if (req.method) {
            options.method = req.method;
        }

        if (req.headers) {
            headers = { ...options.headers, ...req.headers };
        } else {
            headers = options.headers || {};
        }
        options.headers = headers;

        if (req.params) {
            url = new URL(url);
            for (const [key, value] of Object.entries(req.params)) {
                url.searchParams.set(key, value);
            }
        }

        if (req.form) {
            body = new URLSearchParams(req.form);
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
        }

        if (req.timeout) {
            options.signal = AbortSignal.timeout(req.timeout * 1000);
        }

        if (body !== null) {
            options.body = body;
        }

        try {
            var r = await fetch(url, options);
            returnData = {
                'event_id': req.event_id,
                'headers': Object.fromEntries([...r.headers]),
                'ok': r.ok,
                'redirected': r.redirected,
                'status': r.status,
                'status_text': r.statusText,
                'type': r.type,
                'url': r.url
            };
            response = await r.blob();
        } catch (/**@type {any} */err) {
            returnData = {
                'event_id': req.event_id,
                'error': err.toString()
            };
            response = "";
        };
        return new Blob([new TextEncoder().encode(JSON.stringify(returnData)), "\0", response]);
    }

    /**
     * 
     * @param {any} req
     * @returns {Promise<Uint8Array>}
     */
    async function doEval(req) {
        var evalled, resp;
        try {
            evalled = eval(req['string']);
            switch (evalled.constructor.name) {
                case 'AsyncFunction':
                    evalled = await evalled(req['arg']);
                    break;
                case 'Promise':
                    evalled = await evalled;
                    break;
                case 'Function':
                    evalled = evalled(req['arg']);
                    break;
            }
            resp = { 'result': evalled, 'event_id': req['event_id'] };
        } catch (/**@type {any} */err) {
            resp = { 'result': err.toString(), 'event_id': req['event_id'] };
        }
        return new TextEncoder().encode(JSON.stringify(resp));
    }

    /**
     * 
     * @param {ArrayBuffer} d 
     * @returns {[Uint8Array | null, Object]}
     */
    function parseData(d) {
        var blob, jArray;
        var dArray = new Uint8Array(d);
        var nullIndex = dArray.indexOf(0);
        if (nullIndex === -1) {
            blob = null;
            jArray = dArray;
        } else {
            blob = dArray.slice(nullIndex + 1);
            jArray = dArray.slice(0, nullIndex)
        }

        return [blob, JSON.parse(new TextDecoder().decode(jArray))]
    }

    async function generateHostName() { return location.host };
    /**
     * @type {string}
     */
    var hostName;

    function connect() {
        var protocol = '3'
        var ws = new WebSocket("ws://127.0.0.1:9404/ws");
        ws.binaryType = "arraybuffer";

        ws.onopen = async () => {
            if (!hostName) {
                hostName = await generateHostName();
            }
            ws.send(protocol + ' ' + hostName);
        }

        ws.onclose = () => {
            console.error('WebSocket was closed; will retry in 5 seconds');
            setTimeout(connect, 5000);
        };

        ws.onmessage = async (evt) => {
            var /**@type {Uint8Array | Blob} */ result, /**@type {any} */ j, b;
            [b, j] = parseData(evt.data);
            switch (j['action']) {
                case 'close_ws':
                    console.debug(`websocket closed. reason: ${j["reason"]}`);
                    ws.onclose = null;
                    ws.close();
                    return;
                case 'fetch':
                    result = await doFetch(j, b);
                    break;
                case 'eval':
                    result = await doEval(j);
                    break;
                default:
                    result = new TextEncoder().encode(JSON.stringify({
                        'event_id': j['event_id'],
                        'error': `Action ${j['action']} is not defined.`
                    }));
                    break;
            }
            ws.send(result);
        }
    };

    // @ts-ignore
    if (window.GM_registerMenuCommand) {
        // @ts-ignore
        GM_registerMenuCommand(
            'connect to browserfetch',
            connect
        );
    } else {
        connect();
    }
})();
