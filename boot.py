# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
#import webrepl
#webrepl.start()


# Double RESET press -> setup WiFi network, see WlanNetwork/doublereset.py
from WlanNetwork.doublereset import check_double_reset
check_double_reset()
