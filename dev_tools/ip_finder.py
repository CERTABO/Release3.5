import subprocess
import PySimpleGUI as sg

prc = subprocess.run(['hostname', '-I'], stdout=subprocess.PIPE)
out = prc.stdout.decode('utf-8')
ip = out.split()[0]

sg.theme('Reddit')
layout = [
	[sg.Text(f'Your IP address is: {ip}', font=('Helvetica', 14))],
	[sg.Ok('Close')]
]
window = sg.Window('Certabo', layout, keep_on_top=True, auto_size_buttons=False)
event, values = window.read()
window.close()
