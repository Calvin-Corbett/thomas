### Changed

- **Every install of Thomas now gets his own ears.** The open-source speech engine Thomas listens with, sherpa-onnx 1.13.6 (Apache-2.0), is now listed with the server's other packages, so a new install has it without anyone adding it by hand. It is installed into Python like aiohttp and numpy, so none of its code is in this repository, which keeps the one MIT licence. The speech model it runs is never committed either; it lives in Thomas's .thomas folder, which git leaves alone.
