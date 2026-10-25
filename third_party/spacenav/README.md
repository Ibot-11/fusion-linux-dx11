# Corresponding FreeSpacenav sources

These pinned sources make the optional SpaceMouse build work without downloading
code during installation. Upstream Git metadata is omitted; spnavcfg's Git LFS
PNG resources are included as actual images.

| Component | Upstream | Commit | License |
| --- | --- | --- | --- |
| spacenavd | https://github.com/FreeSpacenav/spacenavd | 6cb68b693fc837ba33b7a2fe682f184faf501496 | GPL-3.0-or-later |
| libspnav | https://github.com/FreeSpacenav/libspnav | 476a17b6087146f95799e3a2a12b4d13cb4d2818 | BSD-3-Clause |
| spnavcfg | https://github.com/FreeSpacenav/spnavcfg | 84543beeed78c41796890b67b56b10287ad610fd | GPL-3.0-or-later |

See each component's COPYING file. Changes to the Wine SDK bridge are kept
separately under `spacemouse/bridge/`, including the MinHook license.
