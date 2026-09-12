# captain_nemo

Spring 2019 - long weekend at Triest (Italy). As we came home we saw, that it was a doomsday weekend in our aquarium. 5 fishes died, the wather was lightly green.
26°C was to warm.

So the problem was clear. This should never happen.

Project Captain-Nemo was born.

## Tests

Run the automated unit tests with plain Python 3 (no extra dependencies —
MicroPython-only modules like `machine`, `network`, `ds18x20` and
`urequests` are stubbed under `tests/micropython_mocks.py`):

```bash
python3 -m unittest discover -s tests -v
```

CI runs the same command on every push/PR (see `.github/workflows/tests.yml`).

