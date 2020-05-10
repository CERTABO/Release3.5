import logging
import time

import utils_shared

assert utils_shared.DEBUG_LED, 'DEBUG_LED is set to FALSE!'

port = utils_shared.find_port()
utils_shared.usbtool(port, buffer_ms=0)
led_manager = utils_shared.LedManager()

ranges_ms = (10, 50, 100, 150, 200, 250, 500, 750, 1000)
logging.info(f'Testing gaps of {ranges_ms} ms')

print(f'Testing gaps of {ranges_ms} ms')
print('')
print('Answer 0 for failures and 1 for successes.')
print('Press 5 to skip to next time gap during test (if needed).')
print('Press Enter to confirm response')

for i, gap_ms in enumerate(ranges_ms, 1):
    logging.info(f'Testing gap of {gap_ms}ms')
    print('')
    print(f'>>> Testing gap of {gap_ms}ms')

    gap_s = gap_ms / 1000
    for j in range(10):
        logging.info(f'{j}/10')

        led_manager.set_leds('thinking')
        time.sleep(gap_s)
        led_manager.set_leds('e2e4')
        time.sleep(.5)

        skip = False
        while True:
            try:
                success = int(input(f'({j}/10) Did leds e2e4 light up?'))
                assert success in (0, 1, 5), "Invalid Number"
            except Exception as e:
                print(e)
                print('Answer with 0 or 1 (or 5 to skip range).')
            else:
                if success == 5:
                    logging.info('Skipping this range')
                    print('Skipping this range')
                    skip = True
                else:
                    logging.info(f'Answer: {success}')
                break

        led_manager.set_leds()
        time.sleep(1.5)

        if skip:
            break
