from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from pathlib import Path

from pyperclip import copy


def main():
    parser = ArgumentParser(
        description='The command-line entry for browserfetch.',
        formatter_class=ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        'copyjs', help='copy contents of browserfetch.js to clipboard'
    )
    args = parser.parse_args()

    if args.copyjs:
        with (Path(__file__).parent / 'browserfetch.js').open() as f:
            copy(f.read())


if __name__ == '__main__':
    main()
