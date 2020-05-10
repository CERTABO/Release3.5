"""
Includes globals that are shared across modules
"""
import argparse

APPLICATION = 'OFFLINE'
VERSION = '22.04.2020'
MAX_DEPTH_DEFAULT = 20

parser = argparse.ArgumentParser()
parser.add_argument("--port")
parser.add_argument("--publish", help="URL to publish data")
parser.add_argument("--game-id", help="Game ID")
parser.add_argument("--game-key", help="Game key")
parser.add_argument("--robust", help="Robust", action="store_true")
parser.add_argument("--syzygy", help="Syzygy path")
parser.add_argument("--hide-cursor", help="Hide cursor", action="store_true")
parser.add_argument("--max-depth", help="Maximum depth", type=int, default=MAX_DEPTH_DEFAULT)
parser.add_argument('--debug', help='Debug mode (additional options: {led, pystockfish})', nargs='*')
parser.add_argument('--port-not-strict', help='Whether find_port runs in strict mode', action='store_false')
args = parser.parse_args()
args.picochess = False

DEBUG = False
DEBUG_LED = False
DEBUG_PYSTOCKFISH = False
if args.debug is not None:
    DEBUG = True
    for narg in args.debug:
        if narg == 'led':
            DEBUG_LED = True
        elif narg == 'pystockfish':
            DEBUG_PYSTOCKFISH = True
        else:
            print(f'Debug optional narg not recognized: {narg}')
            print('Valid options are: {led, pystockfish}')
            raise SystemError

scr = None
x_multiplier = None
y_multiplier = None
font = None
font_large = None
