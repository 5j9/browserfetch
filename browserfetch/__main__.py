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
        copy((Path(__file__).parent / 'browserfetch.js').read_bytes().decode())


if __name__ == '__main__':
    main()
