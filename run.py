# import argparse
import logging
import os
import queue
import sys
import time
from datetime import datetime, timedelta

import chess
import chess.pgn
import pygame

import stockfish

import cfg
import utils
import utils_shared
import pypolyglot
from messchess import RomEngineThread
from publish import Publisher
from cfg import args
from utils import button, coords_in, SPRITE_NAMES, SOUND_NAMES, COLORS, CERTABO_SAVE_PATH
from utils_shared import FEN_SPRITE_MAPPING, COLUMNS_LETTERS, CERTABO_DATA_PATH

utils_shared.set_logger()

pgn_queue = None
publisher = None

# Use stockfish.exe if running built. Not sure if needed
TO_EXE = getattr(sys, "frozen", False)
stockfish.TO_EXE = TO_EXE


def make_publisher():
    global pgn_queue, publisher
    if publisher:
        publisher.stop()
    pgn_queue = queue.Queue()
    publisher = Publisher(args.publish, pgn_queue, args.game_id, args.game_key)
    publisher.start()
    return pgn_queue, publisher


def publish():
    global pgn_queue
    pgn_queue.put(generate_pgn())


def do_poweroff(method=None):
    if method == 'logo':
        logging.info('Closing program: banner click')
    elif method == 'key':
        logging.info('Closing program: q key')
    elif method == 'window':
        logging.info('Closing program: window closed')
    elif method == 'picochess':
        logging.info('Closing program: picochess')
    else:
        logging.warning('Closing program: unknown method')
    pygame.display.quit()
    pygame.quit()
    sys.exit()


# ----------- Read screen.ini info
XRESOLUTION = 1920
with open("screen.ini", "r") as f:
    try:
        XRESOLUTION = int(f.readline().split(" #")[0])
    except Exception as e:
        logging.info(f"Cannot read resolution from screen.ini: {e}")

    if XRESOLUTION not in (480, 1366, 1920):
        logging.info(f"Wrong value xscreensize.ini = {XRESOLUTION}, setting to 1366")
        XRESOLUTION = 1366

    try:
        s = f.readline().split(" #")[0]
        if s == "fullscreen":
            fullscreen = True
        else:
            fullscreen = False
    except Exception as e:
        fullscreen = False
        logging.info(f"Cannot read 'fullscreen' or 'window' as second line from screen.ini: {e}")


# ----------- Start PyGame
icon = pygame.image.load('certabo.png')
pygame.display.set_icon(icon)

os.environ["SDL_VIDEO_WINDOW_POS"] = "90,50"
try:
    pygame.mixer.init()
except pygame.error as e:
    logging.error(f'Failed to load audio driver {e}')
pygame.init()

# auto reduce a screen's resolution
infoObject = pygame.display.Info()
xmax, ymax = infoObject.current_w, infoObject.current_h
logging.info(f"Xmax = {xmax}")
logging.info(f"XRESOLUTION = {XRESOLUTION}")
if xmax < XRESOLUTION:
    XRESOLUTION = 1366
if xmax < XRESOLUTION:
    XRESOLUTION = 480

if XRESOLUTION == 480:
    screen_width, screen_height = 480, 320
elif XRESOLUTION == 1920:
    screen_width, screen_height = 1500, 1000
else:  # 1366
    screen_width, screen_height = 900, 600

cfg.x_multiplier, cfg.y_multiplier = float(screen_width) / 480, float(screen_height) / 320

# TODO: Simplify this
if fullscreen:
    cfg.scr = pygame.display.set_mode(
        (screen_width, screen_height),
        pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.FULLSCREEN, 32,
    )
else:
    cfg.scr = pygame.display.set_mode(
        (screen_width, screen_height), pygame.HWSURFACE | pygame.DOUBLEBUF, 32
    )

cfg.font = pygame.font.Font("Fonts//OpenSans-Regular.ttf", int(13 * cfg.y_multiplier))
cfg.font_large = pygame.font.Font("Fonts//OpenSans-Regular.ttf", int(19 * cfg.y_multiplier))

pygame.display.set_caption("Chess software")
cfg.scr.fill(COLORS['black'])  # clear screen
pygame.display.flip()  # copy to screen

# change mouse cursor to be invisible - not needed for Windows!
if args.hide_cursor:
    mc_strings = '        ', '        ', '        ', '        ', '        ', '        ', '        ', '        '
    cursor, mask = pygame.cursors.compile(mc_strings)
    cursor_sizer = ((8, 8), (0, 0), cursor, mask)
    pygame.mouse.set_cursor(*cursor_sizer)

# ----------- load sprites and sounds
sprite = {}
if XRESOLUTION == 480:
    sprite_path = os.path.join('sprites', 'sprites_480')
elif XRESOLUTION == 1920:
    sprite_path = os.path.join('sprites', 'sprites_1920')
else:  # 1366
    sprite_path = path = os.path.join('sprites', 'sprites_1366')

for name in SPRITE_NAMES:
    sprite[name] = pygame.image.load(os.path.join(sprite_path, f'{name}.png'))

sound = {}
for _sound_name in SOUND_NAMES:
    try:
        sound[_sound_name] = pygame.mixer.Sound('sounds/{}.wav'.format(_sound_name))
    except Exception as e:
        logging.error(f'Unable to load "{_sound_name}" sound: {e}')


def show_sprite(name, x, y):
    """
    Show sprite, by name
    """
    img = sprite[name]
    cfg.scr.blit(img, (x * cfg.x_multiplier, y * cfg.y_multiplier))
    widget_width, widget_height = img.get_size()
    return (
        x,
        y,
        x + int(widget_width // cfg.x_multiplier),
        y + int(widget_height // cfg.y_multiplier)
    )


def play_sound(sound_name):
    global sound
    try:
        s = sound[sound_name]
    except KeyError:
        return
    s.play()


def txt(s, x, y, color):
    img = cfg.font.render(s, 22, color)  # string, blend, color, background color
    pos = x * cfg.x_multiplier, y * cfg.y_multiplier
    cfg.scr.blit(img, pos)
    text_width, text_height = img.get_size()
    return (
        x + int(text_width // cfg.x_multiplier),
        y + int(text_height // cfg.y_multiplier)
    )


def txt_large(s, x, y, color):
    img = cfg.font_large.render(s, 22, color)  # string, blend, color, background color
    pos = x * cfg.x_multiplier, y * cfg.y_multiplier
    cfg.scr.blit(img, pos)
    text_width, text_height = img.get_size()
    return (
        x + int(text_width // cfg.x_multiplier),
        y + int(text_height // cfg.y_multiplier)
    )


def show_board(FEN_string, x0, y0):
    # Show chessboard using FEN string like
    # "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    show_sprite("chessboard_xy", x0, y0)
    if game_settings['rotate180']:
        FEN_string = "/".join(
            row[::-1] for row in reversed(FEN_string.split(" ")[0].split("/"))
        )
    x, y = 0, 0
    for c in FEN_string:
        if c in FEN_SPRITE_MAPPING:
            show_sprite(FEN_SPRITE_MAPPING[c], x0 + 26 + 31.8 * x, y0 + 23 + y * 31.8)
            x += 1
        elif c == "/":  # new line
            x = 0
            y += 1
        elif c == " ":
            break
        else:
            x += int(c)


def show_board_and_animated_move(FEN_string, move, x0, y0):
    piece = ""
    if game_settings['rotate180']:
        FEN_string = "/".join(
            row[::-1] for row in reversed(FEN_string.split(" ")[0].split("/"))
        )

    xa = COLUMNS_LETTERS.index(move[0])
    ya = 8 - int(move[1])
    xb = COLUMNS_LETTERS.index(move[2])
    yb = 8 - int(move[3])

    if game_settings['rotate180']:
        xa = 7 - xa
        ya = 7 - ya
        xb = 7 - xb
        yb = 7 - yb

    xstart, ystart = x0 + 26 + 31.8 * xa, y0 + 23 + ya * 31.8
    xend, yend = x0 + 26 + 31.8 * xb, y0 + 23 + yb * 31.8

    show_sprite("chessboard_xy", x0, y0)
    x, y = 0, 0
    for c in FEN_string:

        if c in FEN_SPRITE_MAPPING:
            if x != xa or y != ya:
                show_sprite(FEN_SPRITE_MAPPING[c], x0 + 26 + 31.8 * x, y0 + 23 + y * 31.8)
            else:
                piece = FEN_SPRITE_MAPPING[c]
            x += 1
        elif c == "/":  # new line
            x = 0
            y += 1
        elif c == " ":
            break
        else:
            x += int(c)
            # pygame.display.flip() # copy to screen
    if piece == "":
        return
    # logging.debug(f'Animating {piece}')
    for i in range(20):
        x, y = 0, 0
        show_sprite("chessboard_xy", x0, y0)
        for c in FEN_string:
            if c in FEN_SPRITE_MAPPING:
                if x != xa or y != ya:
                    show_sprite(FEN_SPRITE_MAPPING[c], x0 + 26 + 31.8 * x, y0 + 23 + y * 31.8)
                x += 1
            elif c == "/":  # new line
                x = 0
                y += 1
            elif c == " ":
                break
            else:
                x += int(c)

        xp = xstart + (xend - xstart) * i / 20.0
        yp = ystart + (yend - ystart) * i / 20.0
        show_sprite(piece, xp, yp)
        pygame.display.flip()  # copy to screen
        time.sleep(0.01)


def terminal_print(s, newline=True):
    """
    Print lines in virtual terminal. Does not repeat previous line
    """
    global terminal_lines
    if newline:
        # If line is different than previous
        if s != terminal_lines[1]:
            terminal_lines = [terminal_lines[1], s]
    else:
        terminal_lines[1] = "{}{}".format(terminal_lines[1], s)


def generate_pgn():
    move_history = [_move.uci() for _move in chessboard.move_stack]
    game = chess.pgn.Game()
    game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
    if game_settings['play_white']:
        game.headers["White"] = "Human"
        game.headers["Black"] = "Computer" if not game_settings['human_game'] else "Human"
    else:
        game.headers["White"] = "Computer" if not game_settings['human_game'] else "Human"
        game.headers["Black"] = "Human"
    game.headers["Result"] = chessboard.result()
    game.setup(chess.Board(starting_position, chess960=game_settings['chess960']))
    if len(move_history) > 2:
        node = game.add_variation(chess.Move.from_uci(move_history[0]))
        for move in move_history[1:]:
            node = node.add_variation(chess.Move.from_uci(move))
    exporter = chess.pgn.StringExporter()
    return game.accept(exporter)


def take_back_steps():
    """
    Helper function to set settings after take back was confirmed
    """
    global game_settings
    global waiting_for_user_move
    global do_user_move
    global banner_right_places
    global banner_place_pieces
    global hint_text

    logging.debug(f'Take back: Before - {chessboard.fen()}')
    logging.info(f'Take back: Before - {str([_move.uci() for _move in chessboard.move_stack])}')
    chessboard.pop()
    if not game_settings['human_game']:
        chessboard.pop()
    logging.info(f'Take back: After - {str([_move.uci() for _move in chessboard.move_stack])}')
    logging.debug(f'Take back: After - {chessboard.fen()}')
    waiting_for_user_move = False
    do_user_move = False
    banner_right_places = True
    banner_place_pieces = True
    hint_text = ""


# ------------- Define initial variables
if args.syzygy is None:
    args.syzygy = os.path.join(CERTABO_DATA_PATH, 'syzygy')
syzygy_available = os.path.exists(args.syzygy)
game_settings = {'human_game': False,
                 'rotate180': False,
                 'use_board_position': False,
                 'side_to_move': 'white',
                 'time_constraint': 'unlimited',
                 'time_total_minutes': 5,
                 'time_increment_seconds': 8,
                 'chess960': False,
                 'enable_syzygy': syzygy_available,
                 'engine': 'stockfish',
                 'book': '',
                 'difficulty': 0,
                 'play_white': True}

old_left_click = 0
x, y = 0, 0
move = []

terminal_lines = ["Game started", "Terminal text here"]
dialog = ""  # dialog inside the window
hint_text = ""
name_to_save = ""

saved_files = []
saved_files_time = []
resume_file_selected = 0
resume_file_start = 0  # starting filename to show
current_engine_page = 0

move_detect_tries = 0
move_detect_max_tries = 3

left_click = False

new_setup = False
start_game = False
rom = False

# game_process_just_started = True  # Not sure if this was needed
banner_right_places = False
resuming_new_game = False

waiting_for_user_move = False
do_ai_move = True
do_user_move = False
conversion_dialog = False
hint_request = False

window = "home"  # name of current page
chessboard = chess.Board()
board_state = chessboard.fen()
starting_position = chess.STARTING_FEN

# ------------- Start
cfg.scr.fill(COLORS['white'])  # clear screen
show_sprite("start-up-logo", 7, 0)
pygame.display.flip()  # copy to screen
time.sleep(.5)

while True:
    port_chessboard = utils_shared.find_port() if args.port is None else args.port
    if port_chessboard is not None:
        break
    else:
        print('Did not find serial port, make sure Certabo board is connected')
        time.sleep(.1)

utils_shared.start_usbtool_thread(port_chessboard)
usb_reader = utils_shared.UsbReader(port_chessboard)
usb_reader.ignore_missing(args.picochess)
led_manager = utils_shared.LedManager()
game_clock = utils.GameClock()
picochess = utils.PicoChess(led_manager, args.picochess)
calibration = usb_reader.needs_calibration

led_manager.set_leds('all')
led_manager.set_leds()

poweroff_time = datetime.now()
while True:
    # event from system & keyboard
    for event in pygame.event.get():  # all values in event list
        if event.type == pygame.QUIT:
            do_poweroff(method='window')
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_q:
                do_poweroff(method='key')
            if event.key == pygame.K_h:
                window = "home"
            if event.key == pygame.K_a:
                pass

    # usb_reader.update()
    if picochess.check_exit(usb_reader.read_board(), type_='application') == 2:
        do_poweroff(method='picochess')

    x, y = pygame.mouse.get_pos()  # mouse position
    x = x / cfg.x_multiplier
    y = y / cfg.y_multiplier

    mbutton = pygame.mouse.get_pressed()
    # if cfg.DEBUG:
    #     txt(str((x, y)), 80, 300, COLORS['black'])
    if mbutton[0] == 1 and old_left_click == 0:
        left_click = True
    else:
        left_click = False

    # Long click on banner exits program
    if x < 110 and y < 101 and mbutton[0] == 1:
        if datetime.now() - poweroff_time >= timedelta(seconds=2):
            do_poweroff(method='logo')
    else:
        poweroff_time = datetime.now()

    cfg.scr.fill(COLORS['white'])  # clear screen
    show_sprite("logo", 8, 6)
    # -------------- home ----------------
    if window == "home":
        if calibration:
            calibration_done = usb_reader.calibration(new_setup, verbose=False)
            led_manager.set_leds('setup')
            if calibration_done:
                calibration = False
                led_manager.set_leds()

        board_state = usb_reader.read_board()
        window, pico_calibration = picochess.update(window, board_state)
        if pico_calibration:
            usb_reader.ignore_missing(False)
            calibration = True

        # txt(f'Version: {cfg.VERSION}', 12, 149 - 20, COLORS['lightestgrey'])

        # if left_click:
        #     if coords_in(x, y, minutes_less_button_area):

        first_button_y = 125
        button_spacing_y = 38
        new_game_button_area = show_sprite("new_game", 5, first_button_y)
        resume_game_button_area = show_sprite("resume_game", 5, first_button_y + button_spacing_y * 1)
        add_piece_button_area = show_sprite("setup", 5, first_button_y + button_spacing_y * 2)
        setup_button_area = show_sprite("new-setup", 5, first_button_y + button_spacing_y * 3)
        play_online_button_area = show_sprite("lichess", 5, first_button_y + button_spacing_y * 4)

        show_board(board_state, 178, 40)
        show_sprite("welcome", 111, 6)
        if calibration:
            show_sprite("please-wait", 253, 170)

        if left_click:
            if coords_in(x, y, new_game_button_area):
                window = "new game"
                led_manager.set_leds()

            elif coords_in(x, y, resume_game_button_area):
                window = "resume"
                # update saved files list to load
                files = os.listdir(CERTABO_SAVE_PATH)
                saved_files = [v for v in files if ".pgn" in v]
                saved_files_time = [time.gmtime(os.stat(os.path.join(CERTABO_SAVE_PATH, name)).st_mtime) for name in saved_files]
                terminal_lines = ["", ""]

            elif coords_in(x, y, add_piece_button_area):
                logging.info("Calibration: add piece - collecting samples")
                calibration = True
                new_setup = False
                calibration_samples = []

            elif coords_in(x, y, setup_button_area):
                logging.info("Calibration: new setup - collecting samples")
                calibration = True
                new_setup = True
                calibration_samples = []

            elif coords_in(x, y, play_online_button_area):
                logging.info('Switching to Online Application')
                os.execl(sys.executable, sys.executable, 'online_gui.py', *sys.argv[1:], '--port', port_chessboard)

    # ---------------- Resume game dialog ----------------
    elif window == "resume":
        txt_large("Select game name to resume", 159, 1, COLORS['black'])
        show_sprite("resume_back", 107, 34)
        show_sprite("resume_game", 263, 283)
        show_sprite("back", 3, 146)
        show_sprite("delete-game", 103, 283)

        pygame.draw.rect(
            cfg.scr,
            COLORS['lightestgrey'],
            (
                113 * cfg.x_multiplier,
                41 * cfg.y_multiplier + resume_file_selected * 29 * cfg.y_multiplier,
                330 * cfg.x_multiplier,
                30 * cfg.y_multiplier,
            ),
        )  # selection

        for i in range(len(saved_files)):
            if i > 7:
                break
            txt_large(saved_files[i + resume_file_start][:-4], 117, 41 + i * 29, COLORS['grey'])
            v = saved_files_time[i]

            txt_large(
                "%d-%d-%d  %d:%d"
                % (v.tm_year, v.tm_mon, v.tm_mday, v.tm_hour, v.tm_min),
                300,
                41 + i * 29,
                COLORS['lightgrey'],
            )

        if dialog == "delete":
            show_sprite("hide_back", 0, 0)

            pygame.draw.rect(cfg.scr, COLORS['lightgrey'], (200 + 2, 77 + 2, 220, 78))
            pygame.draw.rect(cfg.scr, COLORS['white'], (200, 77, 220, 78))
            txt_large("Delete the game ?", 200 + 32, 67 + 15, COLORS['grey'])
            show_sprite("back", 200 + 4, 77 + 40)
            show_sprite("confirm", 200 + 4 + 112, 77 + 40)

            if left_click:
                if (77 + 40 - 5) < y < (77 + 40 + 30):
                    dialog = ""
                    if x > (200 + 105):  # confirm button
                        logging.info("do delete")
                        os.unlink(
                            os.path.join(
                                CERTABO_SAVE_PATH,
                                saved_files[resume_file_selected + resume_file_start],
                            )
                        )

                        # update saved files list to load

                        files = os.listdir(CERTABO_SAVE_PATH)
                        saved_files = [v for v in files if ".pgn" in v]
                        saved_files_time = [time.gmtime(os.stat(os.path.join(CERTABO_SAVE_PATH, name)).st_mtime) for name in saved_files]
                        resume_file_selected = 0
                        resume_file_start = 0

        if left_click:

            if 7 < x < 99 and 150 < y < 179:  # back button
                window = "home"

            if 106 < x < 260 and 287 < y < 317:  # delete button
                dialog = "delete"  # start delete confirm dialog on the page

            if 107 < x < 442 and 40 < y < 274:  # pressed on file list
                i = int((int(y) - 41) / 29)
                if i < len(saved_files):
                    resume_file_selected = i

            if 266 < x < 422 and 286 < y < 316:  # Resume button
                logging.info("Resuming game")
                with open(
                        os.path.join(
                            CERTABO_SAVE_PATH,
                            saved_files[resume_file_selected + resume_file_start],
                        ),
                        "r",
                ) as f:
                    _game = chess.pgn.read_game(f)
                if _game:
                    chessboard = _game.end().board()
                    _node = _game
                    while _node.variations:
                        _node = _node.variations[0]
                    game_settings['play_white'] = _game.headers["White"] == "Human"
                    starting_position = _game.board().fen()

                    logging.info(f"Resuming game: Move history - {[_move.uci() for _move in _game.mainline_moves()]}")
                    do_ai_move = False
                    do_user_move = False
                    conversion_dialog = False
                    waiting_for_user_move = False
                    banner_place_pieces = True
                    resuming_new_game = True

                    window = "new game"
            if 448 < x < 472:  # arrows
                if 37 < y < 60:  # arrow up
                    if resume_file_start > 0:
                        resume_file_start -= 1
                elif 253 < y < 284:
                    if (resume_file_start + 8) < len(saved_files):
                        resume_file_start += 1

    # ---------------- Save game dialog ----------------
    elif window == "save":

        txt_large("Enter game name to save", 159, 41, COLORS['grey'])
        show_sprite("terminal", 139, 80)
        txt_large(
            name_to_save, 273 - len(name_to_save) * (51 / 10.0), 86, COLORS['terminal_text_color']
        )

        # show keyboard
        keyboard_buttons = (
            ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-"),
            ("q", "w", "e", "r", "t", "y", "u", "i", "o", "p"),
            ("a", "s", "d", "f", "g", "h", "j", "k", "l"),
            ("z", "x", "c", "v", "b", "n", "m"),
        )

        lenx = 42  # size of buttons
        leny = 38  # size of buttons

        ky = 128
        x0 = 11

        hover_key = ""

        pygame.draw.rect(
            cfg.scr,
            COLORS['lightgrey'],
            (
                431 * cfg.x_multiplier,
                81 * cfg.y_multiplier,
                lenx * cfg.x_multiplier - 2,
                leny * cfg.y_multiplier - 2,
            ),
        )  # back space
        txt_large("<", (431 + 14), (81 + 4), COLORS['black'])

        for row in keyboard_buttons:
            kx = x0
            for key in row:
                pygame.draw.rect(
                    cfg.scr,
                    COLORS['lightgrey'],
                    (
                        kx * cfg.x_multiplier,
                        ky * cfg.y_multiplier,
                        lenx * cfg.x_multiplier - 2,
                        leny * cfg.y_multiplier - 2,
                    ),
                )
                txt_large(key, kx + 14, ky + 4, COLORS['black'])
                if kx < x < (kx + lenx) and ky < y < (ky + leny):
                    hover_key = key
                kx += lenx
            ky += leny
            x0 += 20

        pygame.draw.rect(
            cfg.scr,
            COLORS['lightgrey'],
            (
                x0 * cfg.x_multiplier + lenx * cfg.x_multiplier,
                ky * cfg.y_multiplier,
                188 * cfg.x_multiplier,
                leny * cfg.y_multiplier - 2,
            ),
        )  # spacebar
        if (x0 + lenx) < x < (x0 + lenx + 188) and ky < y < (ky + leny):
            hover_key = " "
        show_sprite("save", 388, 264)
        if 388 < x < (388 + 100) and 263 < y < (263 + 30):
            hover_key = "save"
        if 431 < x < (431 + lenx) and 81 < y < (81 + leny):
            hover_key = "<"

            # ----- process buttons -----
        if left_click:

            if hover_key != "":
                if hover_key == "save":
                    OUTPUT_PGN = os.path.join(
                        CERTABO_SAVE_PATH, "{}.pgn".format(name_to_save)
                    )
                    with open(OUTPUT_PGN, "w") as f:
                        f.write(generate_pgn())
                    window = "game"
                    # banner_do_move = False
                    left_click = False
                    conversion_dialog = False

                elif hover_key == "<":
                    if len(name_to_save) > 0:
                        name_to_save = name_to_save[: len(name_to_save) - 1]
                else:
                    if len(name_to_save) < 22:
                        name_to_save += hover_key

    # ---------------- game dialog ----------------
    elif window == "game":
        # If kings are placed in the central diagonal, skip game logic and eventually exit game into new game
        exit_game_state, hint_request_pico = picochess.update(window, usb_reader.read_board(), game_settings, chessboard)
        if exit_game_state:
            if exit_game_state == 2:
                window = 'new game'
            continue

        board_state = usb_reader.read_board(game_settings['rotate180'])
        # game_process_just_started = False

        # Get hint
        if hint_request or hint_request_pico:
            hint_request = False

            logging.info('Getting hint')
            got_polyglot_result = False
            if not game_settings['book']:
                got_polyglot_result = False
            else:
                finder = pypolyglot.Finder(game_settings['book'], chessboard, game_settings['difficulty'] + 1)
                best_move = finder.bestmove()
                got_polyglot_result = (best_move is not None)

            if got_polyglot_result:
                hint_text = best_move
            else:
                proc = stockfish.EngineThread(
                    [_move.uci() for _move in chessboard.move_stack],
                    game_settings['difficulty'] + 1,
                    engine=game_settings['engine'],
                    starting_position=starting_position,
                    chess960=game_settings['chess960'],
                    syzygy_path=args.syzygy if game_settings['enable_syzygy'] else None,
                )
                proc.start()

                show_board(chessboard.fen(), 178, 40)
                pygame.draw.rect(
                    cfg.scr,
                    COLORS['lightgrey'],
                    (
                        229 * cfg.x_multiplier,
                        79 * cfg.y_multiplier,
                        200 * cfg.x_multiplier,
                        78 * cfg.y_multiplier,
                    ),
                )
                pygame.draw.rect(
                    cfg.scr,
                    COLORS['white'],
                    (
                        227 * cfg.x_multiplier,
                        77 * cfg.y_multiplier,
                        200 * cfg.x_multiplier,
                        78 * cfg.y_multiplier,
                    ),
                )
                txt_large("Analysing...", 227 + 55, 77 + 8, COLORS['grey'])
                show_sprite("force-move", 247, 77 + 39)
                pygame.display.flip()  # copy to screen

                got_fast_result = False
                while proc.is_alive():  # thinking
                    # event from system & keyboard
                    for event in pygame.event.get():  # all values in event list
                        if event.type == pygame.QUIT:
                            publisher.stop()
                            do_poweroff(method='window')

                    x, y = pygame.mouse.get_pos()  # mouse position
                    x = x / cfg.x_multiplier
                    y = y / cfg.y_multiplier

                    # Check if pressed Force move button
                    board_state = usb_reader.read_board(game_settings['rotate180'])
                    force_hint = picochess.update('thinking', board_state, virtual_board=chessboard)
                    mbutton = pygame.mouse.get_pressed()
                    if (mbutton[0] == 1 and 249 < x < 404 and 120 < y < 149) or force_hint:
                        proc.stop()
                        proc.join()
                        hint_text = proc.best_move
                        got_fast_result = True
                        mbutton = (0, 0, 0)
                        logging.info('Forcing hint move')
                        break

                    led_manager.flash_leds('thinking')
                    time.sleep(.001)
                    # led_manager.set_leds('thinking')

                if not got_fast_result:
                    hint_text = proc.best_move

            terminal_print(f'hint: {hint_text}')
            logging.info(f'Hint: {hint_text}')
            led_manager.flash_leds(hint_text)
            continue

        # If physical board is different than virtual board
        if chessboard.board_fen() != board_state:
            if waiting_for_user_move:
                try:
                    move_detect_tries += 1
                    move = utils.get_moves(chessboard, board_state)
                except utils.InvalidMove:
                    if move_detect_tries > move_detect_max_tries:
                        # Check if take back
                        if not rom:
                            temp_board = chessboard.copy()
                            try:
                                temp_board.pop()
                            except IndexError:
                                pass
                            else:  # No exception
                                if temp_board.board_fen() == board_state:
                                    logging.info('Implicit take back recognized')
                                    take_back_steps()
                                    continue

                        highligted_leds = led_manager.highlight_misplaced_pieces(board_state, chessboard, game_settings['rotate180'])
                        if highligted_leds:
                            terminal_print("Invalid move", True)

                else:  # No exception
                    move_detect_tries = 0
                    if move:
                        waiting_for_user_move = False
                        do_user_move = True
            else:
                # if cfg.DEBUG:
                #     logging.info("Place pieces on their places")
                banner_right_places = True
                if not game_settings['human_game']:
                    if game_settings['play_white'] != chessboard.turn:
                        banner_place_pieces = True
                else:
                    banner_place_pieces = True

        # If physical board is equal to virtual board
        else:
            # LEDS
            # Show leds for king in check
            if chessboard.is_check():
                # Find king on check
                checked_king_square = chess.SQUARE_NAMES[chessboard.king(chessboard.turn)]
                led_manager.set_leds(checked_king_square, game_settings['rotate180'])

            # Show time warning leds
            elif game_clock.time_warning(chessboard):
                led_manager.flash_leds('corners')

            # Show hint leds
            elif hint_text:
                led_manager.flash_leds(hint_text)
            # no leds
            else:
                led_manager.set_leds()

            # BANNERS
            banner_right_places = False
            banner_place_pieces = False

            if not game_settings['human_game']:
                if chessboard.turn != game_settings['play_white']:
                    do_ai_move = True
                else:
                    do_ai_move = False

            if (#not game_process_just_started and
                    not do_user_move
                    and not do_ai_move):
                banner_place_pieces = False
                waiting_for_user_move = True

        game_overtime = game_clock.update(chessboard)
        game_clock.display()
        show_sprite("terminal", 179, 3)

        txt(terminal_lines[0], 183, 3, COLORS['terminal_text_color'])
        txt(terminal_lines[1], 183, 18, COLORS['terminal_text_color'])
        txt_large(hint_text, 96, 185 + 22, COLORS['grey'])

        # BUTTONS
        if not rom:
            show_sprite("take_back", 5, 140 + 22)
        if not game_settings['human_game'] and not rom:
            show_sprite("hint", 5, 140 + 40 + 22)
        show_sprite("save", 5, 140 + 100)
        show_sprite("exit", 5, 140 + 140)

        if dialog == "exit":
            show_board(chessboard.fen(), 178, 40)
            pygame.draw.rect(
                cfg.scr,
                COLORS['lightgrey'],
                (
                    229 * cfg.x_multiplier,
                    79 * cfg.y_multiplier,
                    200 * cfg.x_multiplier,
                    78 * cfg.y_multiplier,
                ),
            )
            pygame.draw.rect(
                cfg.scr,
                COLORS['white'],
                (
                    227 * cfg.x_multiplier,
                    77 * cfg.y_multiplier,
                    200 * cfg.x_multiplier,
                    78 * cfg.y_multiplier,
                ),
            )
            txt("Save the game or not ?", 227 + 37, 77 + 15, COLORS['grey'])
            show_sprite("save", 238, 77 + 40)
            show_sprite("exit", 238 + 112, 77 + 40)

            if left_click:
                if (77 + 40 - 5) < y < (77 + 40 + 30):
                    if x > (238 + 105):  # exit button
                        chessboard = chess.Board()
                        dialog = ""
                        window = "home"
                        terminal_lines = ["", ""]
                        hint_text = ""
                        if rom:
                            rom_engine.kill()
                    else:  # save button
                        dialog = ""
                        window = "save"

        else:
            # AI MOVE
            if not game_settings['human_game'] and do_ai_move and not chessboard.is_game_over() and not game_overtime:
                do_ai_move = False
                got_polyglot_result = False
                if not game_settings['book']:
                    got_polyglot_result = False
                else:
                    finder = pypolyglot.Finder(game_settings['book'], chessboard, game_settings['difficulty'] + 1)
                    best_move = finder.bestmove()
                    got_polyglot_result = (best_move is not None)

                if got_polyglot_result:
                    ai_move = best_move.lower()
                else:
                    move_list = [_move.uci() for _move in chessboard.move_stack]
                    if not rom:
                        proc = stockfish.EngineThread(
                            move_list,
                            game_settings['difficulty'] + 1,
                            engine=game_settings['engine'],
                            starting_position=starting_position,
                            chess960=game_settings['chess960'],
                            syzygy_path=args.syzygy if game_settings['enable_syzygy'] else None,
                        )
                        proc.start()
                    else:
                        rom_engine.go(move_list)

                    got_fast_result = False
                    waiting_ai_move = True
                    ai_move_duration = game_clock.sample_ai_move_duration()
                    ai_move_start_time = time.time()
                    while waiting_ai_move or ai_move_start_time + ai_move_duration > time.time():
                        if not rom:
                            waiting_ai_move = proc.is_alive()
                        else:
                            waiting_ai_move = rom_engine.waiting_ai_move()

                        # Event from system & keyboard
                        for event in pygame.event.get():  # all values in event list
                            if event.type == pygame.QUIT:
                                if args.publish:
                                    publisher.stop()
                                if rom: 
                                    rom_engine.kill()
                                do_poweroff(method='window')

                        # Display board
                        show_board(chessboard.fen(), 178, 40)
                        pygame.draw.rect(cfg.scr, COLORS['lightgrey'], (229 * cfg.x_multiplier, 79 * cfg.y_multiplier,
                                                                        200 * cfg.x_multiplier, 78 * cfg.y_multiplier))
                        pygame.draw.rect(cfg.scr, COLORS['white'], (227 * cfg.x_multiplier, 77 * cfg.y_multiplier,
                                                                    200 * cfg.x_multiplier, 78 * cfg.y_multiplier))
                        game_overtime = game_clock.update(chessboard)
                        game_clock.display()

                        txt_large("Analysing...", 227 + 55, 77 + 8, COLORS['grey'])
                        if not rom:
                            show_sprite("force-move", 247, 77 + 39)
                        pygame.display.flip()  # copy to screen

                        x, y = pygame.mouse.get_pos()  # mouse position
                        x = x / cfg.x_multiplier
                        y = y / cfg.y_multiplier

                        # Force move
                        board_state = usb_reader.read_board(game_settings['rotate180'])
                        force_picochess = picochess.update('thinking', board_state, virtual_board=chessboard)
                        mbutton = pygame.mouse.get_pressed()
                        force_mbutton = mbutton[0] == 1 and 249 < x < 404 and 120 < y < 149
                        if (not rom and (force_mbutton or force_picochess)) or game_overtime:
                            logging.info('Forcing AI move')
                            if not rom:
                                proc.stop()
                                proc.join()
                                ai_move = proc.best_move
                                got_fast_result = True
                            break

                        led_manager.flash_leds('thinking')
                        time.sleep(.001)

                    if not got_fast_result:
                        if not rom:
                            ai_move = proc.best_move.lower()
                        else:
                            ai_move = rom_engine.best_move

                if not game_overtime:
                    logging.info(f"AI move: {ai_move}")
                    led_manager.set_leds(ai_move, game_settings['rotate180'])
                    play_sound('move')

                    # banner_do_move = True
                    if not args.robust:
                        show_board_and_animated_move(chessboard.fen(), ai_move, 178, 40)

                    try:
                        chessboard.push_uci(ai_move)
                        logging.debug(f"after AI move: {chessboard.fen()}")
                        side = ('white', 'black')[int(chessboard.turn)]
                        terminal_print("{} move: {}".format(side, ai_move))
                        if args.publish:
                            publish()
                    except Exception as e:
                        logging.warning(f"   ----invalid chess_engine move! ---- {ai_move}")
                        logging.warning(f"Exception: {e}")
                        terminal_print(ai_move + " - invalid move !")

                    if chessboard.is_check():  # AI CHECK
                        terminal_print(" check!", False)

                    if chessboard.is_checkmate():
                        logging.info("mate!")

                    if chessboard.is_stalemate():
                        logging.info("stalemate!")

            # USER MOVE
            if do_user_move and not chessboard.is_game_over() and not game_overtime:
                do_user_move = False
                try:
                    for m in move:
                        chessboard.push_uci(m)
                        logging.info(f'User move: {m}')
                        side = ('white', 'black')[int(chessboard.turn)]
                        terminal_print("{} move: {}".format(side, m))
                        if not game_settings['human_game']:
                            do_ai_move = True
                            hint_text = ""
                        if args.publish:
                            publish()
                except Exception as e:
                    logging.info(f"   ----invalid user move! ---- {move}")
                    logging.exception(f"Exception: {e}")
                    terminal_print("%s - invalid move !" % move)
                    waiting_for_user_move = True

                if chessboard.is_check():
                    terminal_print(" check!", False)

                if chessboard.is_checkmate():
                    logging.info("mate! we won!")

                if chessboard.is_stalemate():
                    logging.info("stalemate!")

            show_board(chessboard.fen(), 178, 40)

            # -------------------- SHOW BANNERS -------------------------
            x0, y0 = 5, 127
            if banner_right_places:
                if not chessboard.move_stack or banner_place_pieces:
                    show_sprite("place-pieces", x0 + 2, y0 + 2)
                else:
                    show_sprite("move-certabo", x0, y0 + 2)

            if waiting_for_user_move:
                show_sprite("do-your-move", x0 + 2, y0 + 2)

            # Endgame banners
            if game_overtime:
                if game_clock.game_overtime_winner == 1:
                    button('White wins', 270, 97, color=COLORS['grey'], text_color=COLORS['white'])
                else:
                    button('Black wins', 270, 97, color=COLORS['grey'], text_color=COLORS['white'])
            elif chessboard.is_game_over():
                if chessboard.is_checkmate():
                    gameover_banner = "check-mate-banner"
                elif chessboard.is_stalemate():
                    gameover_banner = "stale-mate-banner"
                elif chessboard.is_fivefold_repetition():
                    gameover_banner = "five-fold-repetition-banner"
                elif chessboard.is_seventyfive_moves():
                    gameover_banner = "seventy-five-moves-banner"
                elif chessboard.is_insufficient_material():
                    gameover_banner = "insufficient-material-banner"
                show_sprite(gameover_banner, 227, 97)

            if conversion_dialog:
                pygame.draw.rect(cfg.scr, COLORS['lightgrey'], (227 + 2, 77 + 2, 200, 78))
                pygame.draw.rect(cfg.scr, COLORS['white'], (227, 77, 200, 78))
                txt("Select conversion to:", 227 + 37, 77 + 7, COLORS['grey'])
                if game_settings['play_white']:  # show four icons
                    icons = "white_bishop", "white_knight", "white_queen", "white_rook"
                    icon_codes = "B", "N", "Q", "R"
                else:
                    icons = "black_bishop", "black_knight", "black_queen", "black_rook"
                    icon_codes = "b", "n", "q", "r"
                i = 0
                for icon in icons:
                    show_sprite(icon, 227 + 15 + i, 77 + 33)
                    i += 50

            if left_click:
                if conversion_dialog:
                    if (227 + 15) < x < (424) and (77 + 33) < y < (77 + 33 + 30):
                        i = (x - (227 + 15 - 15)) / 50
                        if i < 0:
                            i = 0
                        if i > 3:
                            i = 3
                        icon = icon_codes[i]
                        if len(move[0]) == 4:
                            move[0] += icon
                            logging.info(f"move for conversion: {move[0]}", )
                            conversion_dialog = False
                            do_user_move = True
                else:
                    # Exit button
                    if 6 < x < 123 and (140 + 140) < y < (140 + 140 + 40):
                        dialog = "exit"  # start dialog inside Game page

                    # Take back button
                    if 6 < x < 127 and (143 + 22) < y < (174 + 22):
                        if ((game_settings['human_game'] and len(chessboard.move_stack) >= 1)
                                or (not game_settings['human_game'] and not rom and len(chessboard.move_stack) >= 2)):
                            take_back_steps()
                        else:
                            logging.info(f'Cannot do takeback, move count = {len(chessboard.move_stack)}')

                    # Hint button
                    if (6 < x < 89 and (183 + 22) < y < (216 + 22)) and (not game_settings['human_game'] and not rom):
                        hint_request = True

                    # Save button
                    if 6 < x < 78 and 244 < y < 272:
                        window = "save"

    # ---------------- new game dialog ----------------
    elif window == "new game":
        board_state = usb_reader.read_board()
        settings, start_game = picochess.update(window, board_state, game_settings)

        if dialog == "select time":

            time_total_minutes = game_settings['time_total_minutes']
            time_increment_seconds = game_settings['time_increment_seconds']

            cols = [150, 195]
            rows = [15, 70, 105, 160, 200]

            show_sprite("hide_back", 0, 0)
            button("Custom Time Settings", cols[0], rows[0], color=COLORS['green'], text_color=COLORS['white'])
            txt_large("Minutes per side:", cols[0], rows[1], COLORS['black'])
            minutes_button_area = button('{}'.format(time_total_minutes), cols[1], rows[2], color=COLORS['grey'], text_color=COLORS['white'])
            minutes_less_button_area = button("<", minutes_button_area[0] - 5, rows[2], text_color=COLORS['grey'], color=COLORS['white'], align='right', padding=(5, 2, 5, 2))
            minutes_less2_button_area = button("<<", minutes_less_button_area[0] - 5, rows[2], text_color=COLORS['grey'], color=COLORS['white'], align='right', padding=(5, 0, 5, 0))
            minutes_more_button_area = button(">", minutes_button_area[2] + 5, rows[2], text_color=COLORS['grey'], color=COLORS['white'], padding=(5, 2, 5, 2))
            minutes_more2_button_area = button(">>", minutes_more_button_area[2] + 5, rows[2], text_color=COLORS['grey'], color=COLORS['white'], padding=(5, 0, 5, 0))

            txt_large("Increment in seconds:", cols[0], rows[3], COLORS['black'])
            seconds_button_area = button('{}'.format(time_increment_seconds), cols[1], rows[4], color=COLORS['grey'], text_color=COLORS['white'])
            seconds_less_button_area = button("<", seconds_button_area[0] - 5, rows[4], text_color=COLORS['grey'], color=COLORS['white'], align='right', padding=(5, 2, 5, 2))
            seconds_less2_button_area = button("<<", seconds_less_button_area[0] - 5, rows[4], text_color=COLORS['grey'], color=COLORS['white'], align='right', padding=(5, 0, 5, 0))
            seconds_more_button_area = button(">", seconds_button_area[2] + 5, rows[4], text_color=COLORS['grey'], color=COLORS['white'], padding=(5, 2, 5, 2))
            seconds_more2_button_area = button(">>", seconds_more_button_area[2] + 5, rows[4], text_color=COLORS['grey'],  color=COLORS['white'], padding=(5, 0, 5, 0))
            done_button_area = button("Done", 415, 275, color=COLORS['darkergreen'], text_color=COLORS['white'])

            if left_click:
                if coords_in(x, y, minutes_less_button_area):
                    time_total_minutes -= 1
                elif coords_in(x, y, minutes_less2_button_area):
                    time_total_minutes -= 10
                elif coords_in(x, y, minutes_more_button_area):
                    time_total_minutes += 1
                elif coords_in(x, y, minutes_more2_button_area):
                    time_total_minutes += 10
                elif coords_in(x, y, seconds_less_button_area):
                    time_increment_seconds -= 1
                elif coords_in(x, y, seconds_less2_button_area):
                    time_increment_seconds -= 10
                elif coords_in(x, y, seconds_more_button_area):
                    time_increment_seconds += 1
                elif coords_in(x, y, seconds_more2_button_area):
                    time_increment_seconds += 10

                game_settings['time_total_minutes'] = max(time_total_minutes, 1)
                game_settings['time_increment_seconds'] = max(time_increment_seconds, 0)

                if coords_in(x, y, done_button_area):
                    dialog = ""
        elif dialog == "select_engine":
            engines_per_page = 6
            show_sprite("hide_back", 0, 0)
            engines = utils.get_engine_list()
            txt_large("Select game engine:", 250, 20, COLORS['black'])
            # draw game_settings['engine'] buttons
            button_coords = []
            engine_button_x = 250
            engine_button_y = 50
            engine_button_vertical_margin = 5
            engine_list = utils.get_engine_list()
            if (current_engine_page + 1) * engines_per_page > len(engine_list):
                current_engine_page = len(engine_list) // engines_per_page
            page_engines = engine_list[
                           current_engine_page
                           * engines_per_page: (current_engine_page + 1)
                                               * engines_per_page
                           ]
            has_next = len(engine_list) > (current_engine_page + 1) * engines_per_page
            has_prev = current_engine_page > 0
            for engine_name in page_engines:
                engine_button_area = button(
                    engine_name,
                    engine_button_x,
                    engine_button_y,
                    text_color=COLORS['white'],
                    color=COLORS['darkergreen'] if game_settings['engine'] == engine_name else COLORS['grey'],
                )
                button_coords.append(("select_engine", engine_name, engine_button_area))
                _, _, _, engine_button_y = engine_button_area
                engine_button_y += engine_button_vertical_margin
            done_button_area = button(
                "Done", 415, 275, color=COLORS['darkergreen'], text_color=COLORS['white']
            )
            button_coords.append(("select_engine_done", None, done_button_area))
            if has_next:
                next_page_button_area = button(
                    " > ", 415, 150, color=COLORS['darkergreen'], text_color=COLORS['white']
                )
                button_coords.append(("next_page", None, next_page_button_area))
            if has_prev:
                prev_page_button_area = button(
                    " < ", 200, 150, color=COLORS['darkergreen'], text_color=COLORS['white']
                )
                button_coords.append(("prev_page", None, prev_page_button_area))
            if left_click:
                for action, value, (lx, ty, rx, by) in button_coords:
                    if lx < x < rx and ty < y < by:
                        if action == "select_engine":
                            game_settings['engine'] = value
                        elif action == "select_engine_done":
                            dialog = ""
                        elif action == "next_page":
                            current_engine_page += 1
                        elif action == "prev_page":
                            current_engine_page -= 1
                        break
        elif dialog == "select_book":
            show_sprite("hide_back", 0, 0)
            txt_large("Select game_settings['book']:", 250, 20, COLORS['black'])
            button_coords = []
            book_button_x = 250
            book_button_y = 50
            book_button_vertical_margin = 5
            book_list = utils.get_book_list()
            for book_name in book_list:
                book_button_area = button(
                    book_name,
                    book_button_x,
                    book_button_y,
                    text_color=COLORS['white'],
                    color=COLORS['darkergreen'] if game_settings['book'] == book_name else COLORS['grey'],
                )
                button_coords.append(("select_book", book_name, book_button_area))
                _, _, _, book_button_y = book_button_area
                book_button_y += book_button_vertical_margin
            done_button_area = button(
                "Done", 415, 275, color=COLORS['darkergreen'], text_color=COLORS['white']
            )
            button_coords.append(("select_book_done", None, done_button_area))
            if left_click:
                for action, value, (lx, ty, rx, by) in button_coords:
                    if lx < x < rx and ty < y < by:
                        if action == "select_book":
                            game_settings['book'] = value
                        elif action == "select_book_done":
                            dialog = ""
                        break
        else:
            cols = [20, 150, 190, 280, 460]
            rows = [15, 60, 105, 150, 195, 225, 255, 270]

            txt_x, _ = txt_large("Mode:", cols[1], rows[0] + 5, COLORS['grey'])
            human_game_button_area = button(
                "Human",
                txt_x + 15,
                rows[0],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if game_settings['human_game'] else COLORS['grey'],
            )
            _, _, human_game_button_x, _ = human_game_button_area
            computer_game_button_area = button(
                "Engine",
                human_game_button_x + 5,
                rows[0],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if not game_settings['human_game'] else COLORS['grey'],
            )
            _, _, computer_game_button_x, _ = computer_game_button_area
            flip_board_button_area = button(
                "Flip board",
                computer_game_button_x + 5,
                rows[0],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if game_settings['rotate180'] else COLORS['grey'],
            )
            use_board_position_button_area = button(
                "Use board position",
                cols[1],
                rows[1],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if game_settings['use_board_position'] else COLORS['grey'],
            )
            # txt_large("Time:", 150, use_board_position_button_area[3]+5, COLORS['grey'])

            txt_x, _ = txt_large("Time:", cols[1], rows[2] + 5, COLORS['grey'])

            time_constraint = game_settings['time_constraint']
            time_unlimited_button_area = button(
                u"\u221E",
                txt_x + 5,
                rows[2],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if time_constraint == 'unlimited' else COLORS['grey'],
                padding=(5, 10, 5, 10)
            )
            h_gap = 4
            time_blitz_button_area = button(
                "5+0",
                time_unlimited_button_area[2] + h_gap,
                rows[2],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if time_constraint == 'blitz' else COLORS['grey'],
            )
            time_rapid_button_area = button(
                "10+0",
                time_blitz_button_area[2] + h_gap,
                rows[2],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if time_constraint == 'rapid' else COLORS['grey'],
            )
            time_classical_button_area = button(
                "15+15",
                time_rapid_button_area[2] + h_gap,
                rows[2],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if time_constraint == 'classical' else COLORS['grey'],
            )

            time_custom_button_area = button(
                "Other",
                time_classical_button_area[2] + h_gap,
                rows[2],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if time_constraint == 'custom' else COLORS['grey'],
            )

            chess960_button_area = button(
                "Chess960",
                cols[1],
                rows[3],
                text_color=COLORS['white'],
                color=COLORS['darkergreen'] if game_settings['chess960'] else COLORS['grey'],
            )

            if syzygy_available:
                syzygy_button_area = button(
                    "Syzygy",
                    chess960_button_area[2] + 5,
                    rows[3],
                    text_color=COLORS['white'],
                    color=COLORS['darkergreen'] if game_settings['enable_syzygy'] else COLORS['grey'],
                )

            if game_settings['use_board_position']:
                _, _, use_board_position_button_x, _ = use_board_position_button_area
                side_to_move_button_area = button(
                    "White to move" if game_settings['side_to_move'] == "white" else "Black to move",
                    use_board_position_button_x + 5,
                    rows[1],
                    text_color=COLORS['white'] if game_settings['side_to_move'] == 'black' else COLORS['black'],
                    color=COLORS['black'] if game_settings['side_to_move'] == 'black' else COLORS['lightestgrey'],
                )
            else:
                side_to_move_button_area = None
            if game_settings['human_game']:
                depth_less_button_area = None
                depth_more_button_area = None
            else:
                txt_large("Engine: {}".format(game_settings['engine']), cols[1], rows[4] + 5, COLORS['grey'])
                select_engine_button_area = button(
                    '...',
                    cols[-1],
                    rows[4],
                    text_color=COLORS['white'],
                    color=COLORS['darkergreen'],
                    padding=(0, 5, 0, 5),
                    align='right'
                )

                book_repr = game_settings['book']
                if len(book_repr) > 20:
                    book_repr = "{}...".format(book_repr[:20])
                _, _ = txt_large("Book: {}".format(book_repr), cols[1], rows[5] + 5, COLORS['grey'])
                select_book_button_area = button(
                    '...',
                    cols[-1],
                    rows[5],
                    text_color=COLORS['white'],
                    color=COLORS['darkergreen'],
                    padding=(0, 5, 0, 5),
                    align='right'
                )

                txt_x, _ = txt("Depth:", cols[0], rows[4] + 8, COLORS['green'])
                difficulty_button_area = button('{:02d}'.format(game_settings['difficulty'] + 1), cols[0] + 20, rows[5], color=COLORS['grey'],
                                                text_color=COLORS['white'])
                depth_less_button_area = button("<", difficulty_button_area[0] - 5, rows[5], text_color=COLORS['grey'],
                                                color=COLORS['white'], align='right')
                depth_more_button_area = button(">", difficulty_button_area[2] + 5, rows[5], text_color=COLORS['grey'],
                                                color=COLORS['white'])

                x0 = txt_x + 5
                y0 = rows[4] + 8
                if not game_settings['human_game']:
                    if game_settings['difficulty'] == 0:
                        txt("Easiest", x0, y0, COLORS['grey'])
                    elif game_settings['difficulty'] < 4:
                        txt("Easy", x0, y0, COLORS['grey'])
                    elif game_settings['difficulty'] > 18:
                        txt("Hardest", x0, y0, COLORS['grey'])
                    elif game_settings['difficulty'] > 10:
                        txt("Hard", x0, y0, COLORS['grey'])
                    else:
                        txt("Normal", x0, y0, COLORS['grey'])

            if not game_settings['human_game']:
                txt_x, _ = txt_large("Play as:", cols[1], rows[6] + 5, COLORS['green'])
                sprite_color = "black"
                if game_settings['play_white']:
                    sprite_color = "white"
                color_button_area = show_sprite(sprite_color, txt_x + 5, rows[6])

            back_button_area = show_sprite("back", cols[0], rows[-1])
            start_button_area = show_sprite("start", cols[-1] - 100, rows[-1])

            if left_click:
                if coords_in(x, y, human_game_button_area):
                    game_settings['human_game'] = True
                if coords_in(x, y, computer_game_button_area):
                    game_settings['human_game'] = False
                if coords_in(x, y, flip_board_button_area):
                    game_settings['rotate180'] = not game_settings['rotate180']
                if coords_in(x, y, use_board_position_button_area):
                    game_settings['use_board_position'] = not game_settings['use_board_position']
                for time_button, time_string in zip((time_unlimited_button_area, time_blitz_button_area,
                                                     time_rapid_button_area, time_classical_button_area),
                                                    ('unlimited', 'blitz', 'rapid', 'classical')):
                    if coords_in(x, y, time_button):
                        game_settings['time_constraint'] = time_string
                if coords_in(x, y, time_custom_button_area):
                    dialog = "select time"
                    game_settings['time_constraint'] = 'custom'
                if coords_in(x, y, chess960_button_area):
                    game_settings['chess960'] = not game_settings['chess960']
                if syzygy_available and coords_in(x, y, syzygy_button_area):
                    game_settings['enable_syzygy'] = not game_settings['enable_syzygy']
                if coords_in(x, y, depth_less_button_area):
                    if game_settings['difficulty'] > 0:
                        game_settings['difficulty'] -= 1
                    else:
                        game_settings['difficulty'] = args.max_depth - 1
                if coords_in(x, y, depth_more_button_area):
                    if game_settings['difficulty'] < args.max_depth - 1:
                        game_settings['difficulty'] += 1
                    else:
                        game_settings['difficulty'] = 0
                if game_settings['use_board_position']:
                    if coords_in(x, y, side_to_move_button_area):
                        game_settings['side_to_move'] = 'white' if game_settings['side_to_move'] == 'black' else 'black'
                if coords_in(x, y, select_engine_button_area):
                    dialog = "select_engine"
                    current_engine_page = 0
                if coords_in(x, y, select_book_button_area):
                    dialog = "select_book"

                if coords_in(x, y, color_button_area):
                    game_settings['play_white'] = not game_settings['play_white']

                if coords_in(x, y, back_button_area):
                    window = "home"

                if coords_in(x, y, start_button_area):
                    start_game = True

        # Initialize game settings
        if start_game:
            logging.info('Starting game')
            start_game = False
            window = "game"
            if resuming_new_game:
                resuming_new_game = False
            else:
                if not game_settings['use_board_position']:
                    chessboard = chess.Board()
                    starting_position = chessboard.fen()
                else:
                    chessboard = chess.Board(fen=board_state.split()[0],
                                             chess960=game_settings['chess960'])
                    chessboard.turn = game_settings['side_to_move'] == 'white'
                    chessboard.set_castling_fen('KQkq')
                    starting_position = chessboard.fen()
                    if (not chessboard.status() == chess.STATUS_VALID
                            and chessboard.status() != chess.STATUS_BAD_CASTLING_RIGHTS):
                        logging.warning('Board position is not valid')
                        logging.warning(f'{chessboard.status().__repr__()}')
                        print('Board position is not valid')
                        print(chessboard.status())
                        window = 'new game'
                        left_click = False
                        old_left_click = mbutton[0]
                        continue

            terminal_print("New game, depth={}".format(game_settings['difficulty'] + 1))
            do_user_move = False
            do_ai_move = False
            rom = game_settings['engine'].startswith('rom')
            if rom:
                rom_engine = RomEngineThread(depth=game_settings['difficulty'] + 1, rom=game_settings['engine'].replace('rom-', ''))

            conversion_dialog = False
            waiting_for_user_move = False
            # game_process_just_started = False
            banner_place_pieces = True
            hint_request = False

            game_clock.start(chessboard, game_settings)
            if args.publish:
                make_publisher()

    left_click = False
    old_left_click = mbutton[0]
    pygame.display.flip()
    time.sleep(.001)

    if window != "home":
        usb_reader.ignore_missing(False)

