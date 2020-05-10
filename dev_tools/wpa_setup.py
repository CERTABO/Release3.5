import pathlib
import hashlib
import binascii
import PySimpleGUI as sg


def wpa_passphrase(ssid, pwd):
	"""
	Encodes wifi password into psk for enhanced privacy
	Equivalent to the wpa_passphrase utility in linux
	"""
	if len(pwd) < 8:
		return pwd, False

	var = hashlib.pbkdf2_hmac(
		'sha1',
		str.encode(pwd),
		str.encode(ssid),
		4096,
		32
	)
	return binascii.hexlify(var).decode("utf-8"), True


def save(values):
	country = values['country'].strip().upper()

	ssid = values['ssid'].strip()
	pwd = values['pwd'].strip()
	psk, success = wpa_passphrase(ssid, pwd)

	# If password cannot be hashed, it needs to be saved with quotation marks
	if not success:
		psk = f'"{psk}"'

	content = f'''ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country={country}

network={{
	ssid="{ssid}"
	scan_ssid=1
	psk={psk}
	key_mgmt=WPA-PSK
}}
'''

	path = pathlib.Path(values['directory'].strip())
	wpa_pf = path / 'wpa_supplicant.conf'
	with wpa_pf.open('w', encoding='utf-8') as f:
		f.write(content)


def main():
	sg.theme('Reddit')

	tooltip_directory = 'Example: "E:\\boot" (Windows) or "/media/usr/boot" (Linux)'
	tooltip_country = 'Example: US, GB, FR, DE, IT'

	layout = [
		[sg.Frame('Memory card location', [
			[sg.Text('Please, select the boot folder of the raspberry memory SD card')],
			[sg.Text('Folder:', key='directory_label', tooltip=tooltip_directory), sg.InputText(size=(33, 1), key='directory', tooltip=tooltip_directory), sg.FolderBrowse(tooltip=tooltip_directory)]
		], pad=(5, 10))],
		[sg.Frame('Wifi settitngs', [
			[sg.Text('WiFi Network Name (SSID):', key='ssid_label'), sg.InputText(key='ssid', size=(30, 1))],
			[sg.Text('WiFi Password: ', key='pwd_label'), sg.InputText(key='pwd', size=(40, 1))],
			[sg.Text('Country Code (2 letters):', key='country_label', tooltip=tooltip_country), sg.InputText(key='country', size=(4, 1), tooltip=tooltip_country)]])],
		[sg.Button('Save', pad=(5, 10)), sg.Button('Exit'), sg.Text('Please fill in all fields correctly', text_color='red', visible=False, key='status', pad=(5, 12))]
	]
	window = sg.Window('Certabo', layout, keep_on_top=True, auto_size_buttons=False)

	while True:
		event, values = window.read()
		if event in (None, 'Exit'):
			break
		if event == 'Save':
			window['status'].Update(visible=True)
			directory = pathlib.Path(values['directory'].strip())

			missing = (not all(v.strip() for k, v in values.items() if not k == 'Browse')
					   or not len(values['country'].strip()) == 2
					   or not directory.is_dir())

			window['directory_label'].Update(text_color='black' if directory.is_dir() and values['directory'].strip() else 'red')
			window['ssid_label'].Update(text_color='black' if values['ssid'].strip() else 'red')
			window['pwd_label'].Update(text_color='black' if values['pwd'].strip() else 'red')
			window['country_label'].Update(text_color='black' if len(values['country'].strip()) == 2 else 'red')

			if not missing:
				save(values)
				window['status'].Update('Saved successfully')
				window['status'].Update(text_color='black')

	window.close()


if __name__ == '__main__':
	main()
