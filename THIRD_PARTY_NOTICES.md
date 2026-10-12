# Licenses and attribution

Copyright 2026 p3n1cillin and Aster contributors. Original Aster source,
project-authored documentation and research material are offered under the
GNU General Public License, version 3 or any later version. See [LICENSE](LICENSE).
Existing third-party licenses and notices remain authoritative for their files.

Aster is an independent engine, not a Stockfish wrapper. The engine and play UI
do not link to or invoke Stockfish or python-chess at runtime.

`artifacts/research/conversion-stockfish19-source/` preserves the official
Stockfish 19 source distributed with the pinned release. It is copyrighted by
the Stockfish developers, derives from Glaurung, and retains its GPL-3.0-or-later
file headers and `Copying.txt`. Its manifest records source fingerprints and
the separately downloaded release binary; this publication makes no claim that
the preserved binary was rebuilt from that snapshot. Other immutable research
snapshots containing that source retain the same rights and notices.
See [Stockfish](https://github.com/official-stockfish/Stockfish).

The five tiny development-oracle tables in `tools/syzygy-development-v1/` come
from python-chess v1.11.2's test data. The manifest records each upstream URL and
SHA-256. They retain that project's GPL-3.0-or-later license, provided beside them
as `LICENSE.txt`; they are never loaded by Aster. python-chess and chess are
separately installed development dependencies under the same license.
See [python-chess](https://github.com/niklasf/python-chess/tree/v1.11.2).

.NET, Python, optional training libraries and CI actions are external dependencies
and retain their respective licenses. Project licensing does not relicense them.
