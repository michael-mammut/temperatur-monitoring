# MicroPython only starts main.py automatically, and only as source code.
# The program itself lives in aquarium.py so it can be deployed precompiled
# (.mpy) like every other module instead of being compiled on the board.
#
# gc.threshold() makes the garbage collector run often while all modules
# are loaded: their bytecode then packs tightly instead of being scattered
# between leftover temporaries. Without it the heap was so fragmented after
# start-up that, with ~38 KB free in total, not even a 2 KB block was left
# for a web request or a Telegram send (MicroPython 1.16, reproduced on the
# device). Switched off again afterwards, it only costs time while loading.
import gc

gc.threshold(2048)
from aquarium import main
gc.threshold(-1)
gc.collect()
main()
