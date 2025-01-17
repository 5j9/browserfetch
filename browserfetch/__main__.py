from pathlib import Path


def read_js(host_name_generator: str | None):
    js = (Path(__file__).parent / 'browserfetch.js').read_bytes().decode()
    if host_name_generator is not None:
        return js.replace(
            'async function generateHostName() { return location.host };',
            host_name_generator,
            1,
        )
    return js


def copyjs(*, host_name_generator: str | None = None):
    """Copy contents of browserfetch.js to clipboard.

    `host_name_generator` should be a string containing
    an async JavaScript function named `generateHostName()`. This file's
    contents will be copied into the generated js script and will be used
    to generate a host name for connections. The default
    `generateHostName` function returns `location.host`.
    """
    from pyperclip import copy

    copy(read_js(host_name_generator))


if __name__ == '__main__':
    from cyclopts import App

    from browserfetch import __version__

    app = App(version=__version__)
    app.command(copyjs)
    app()
