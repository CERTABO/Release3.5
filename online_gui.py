import tkinter as tk
from tkinter import messagebox

import logging
import os
import platform
import sys
import threading
import webbrowser

import keyring
if os.name == 'nt':
    from keyring.backends.Windows import WinVaultKeyring
    keyring.set_keyring(WinVaultKeyring())
elif os.name == 'posix':
    if platform.system() == 'Darwin':
        from keyring.backends.OS_X import Keyring
    else:
        from keyring.backends.SecretService import Keyring
    keyring.set_keyring(Keyring())

import cfg
import utils_shared
from lichess import lichess

utils_shared.set_logger()

class LoginCredentials:

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.token_lichess = tk.StringVar(value='')

        entry_width = 25

        lichess_frame = tk.LabelFrame(self.win, text='Paste your API Token below', labelanchor='n', padx=10, pady=10)
        lichess_frame.grid(row=0, columnspan=2, padx=10, pady=10, s='EW')
        self.token_lichess_entry = tk.Entry(lichess_frame, textvariable=self.token_lichess, width=entry_width)
        self.token_lichess_entry.grid(row=0, column=0)

        tk.Button(self.win, text='Save & Exit', command=self.save).grid(row=1, column=1, pady=(0, 20))
        tk.Button(self.win, text='Generate Token',
                  command=lambda: webbrowser.open('http://lichess.org/account/oauth/token/create?description=Certabo&scopes[]=board:play',
                                             new=2, autoraise=True))\
            .grid(row=1, column=0, pady=(0, 20))

        self.load()
        self.close()

    def open(self):
        self.win.deiconify()

    def close(self):
        self.win.withdraw()

    def load(self):
        token_lichess = keyring.get_password('certabo', 'token_lichess')
        self.token_lichess.set(token_lichess if token_lichess is not None else '')

    def save(self):
        keyring.set_password('certabo', 'token_lichess', self.token_lichess.get())
        self.close()


class GUI:
    def __init__(self):
        root = tk.Tk()
        root.title('Certabo Online Chess')
        if os.name == 'nt':
            root.iconbitmap('certabo.ico')
        root.protocol("WM_DELETE_WINDOW", self.close)

        login_credentials = LoginCredentials(root)

        option_frame = tk.LabelFrame(root, text='Options', labelanchor='n', padx=10, pady=10)
        option_frame.grid(row=0, padx=10, pady=10, s='EW')
        tk.Button(option_frame, text='Play Offline', command=self.play_offline).grid(row=0, column=0, s='W')

        launch_frame = tk.LabelFrame(root, text='Lichess.org', labelanchor='n', padx=10, pady=10)
        launch_frame.grid(row=1, padx=10, pady=10, s='EW')
        tk.Button(launch_frame, text='Launch Website', command=self.launch).grid(row=0, column=1, s='W', padx=5)
        tk.Button(launch_frame, text='Register token', command=login_credentials.open).grid(row=0, column=0, s='W', padx=5)

        status_frame = tk.LabelFrame(root, text='Status', labelanchor='n', padx=10, pady=10)
        status_frame.grid(row=2, padx=10, pady=10, s='EW')

        self.status_text = tk.StringVar(value=f'Version: {cfg.VERSION}')
        if os.name == 'nt':
            label_width = int(24/1.5)
        else:
            label_width = int(34/1.5)
        self.status_label = tk.Label(status_frame, textvariable=self.status_text, width=label_width, anchor='center', fg='gray', font=('Arial', 14, 'bold'))
        self.status_label.grid(s='EW')

        self.root = root
        self.port = cfg.args.port

        self.busy = False
        self.lichess_api_thread = None
        self.refresh_rate = int(1 / 60 * 1000)

        self.root.mainloop()

    @staticmethod
    def play_offline():
        logging.info('Switching to Offline Application')
        os.execl(sys.executable, sys.executable, 'run.py', *sys.argv[1:-2])  # remove the extra port argument that is passed by the offline_gui

    def close(self):
        self.root.destroy()
        raise SystemExit

    def launch(self):
        # Validate token
        token = keyring.get_password('certabo', 'token_lichess')
        if not token:
            return messagebox.showerror('Token missing', 'Please register your Lichess API token before launching')

        if self.busy:
            return messagebox.showwarning('Warning', 'Online module is already running')
        self.busy = True

        webbrowser.open('https://lichess.org/', new=2, autoraise=True)
        self.lichess_api_thread = threading.Thread(target=lichess.main, args=(self.port, token), daemon=True)
        self.lichess_api_thread.start()
        self.change_status(['Running', 'gray', 'black'])
        self.root.after(self.refresh_rate, self.check_status())

    def check_status(self):
        if self.lichess_api_thread.is_alive():
            self.root.after(self.refresh_rate, self.check_status)
        else:
            self.busy = False
            self.change_status(['Stopped unexpectedly', 'gray', 'red'])

    def change_status(self, temp):
        text = temp[0]
        bg = temp[1]
        fg = temp[2]

        if bg == 'gray':
            bg = self.root['bg']

        self.status_text.set(text)
        self.status_label.config(bg=bg, fg=fg)


if __name__ == '__main__':
    GUI()

