---
description: Define or extend a CAN message and generate matching C + Python codecs
---
Use the `can-protocol` skill. For the message described in $ARGUMENTS: confirm it fits the ID
block convention (don't break schema v1), define the byte layout, then generate byte-for-byte
matching encode/decode in both STM32 C and Python, plus a round-trip + bit-flip test. Bump
proto_version if the change is protocol-level.
