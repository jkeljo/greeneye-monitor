from typing import Optional, Tuple

from siobrultech_protocols.gem.protocol import BidirectionalProtocol


class GemProtocol(BidirectionalProtocol):
    @property
    def peername(self) -> Optional[Tuple[str, int]]:
        if self._transport:
            return self._transport.get_extra_info("peername")
        return None
