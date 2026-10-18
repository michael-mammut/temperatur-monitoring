import socket

# Answers every DNS query on the setup network with the device's own IP, so
# http://captain-nemo-setup/ works without a router. Deliberately *every*
# name, not just that one: if other lookups (e.g. the phone's own
# connectivity check) went unanswered, phones would mark the network as
# "no internet" and send DNS over mobile data instead - and then
# captain-nemo-setup would not resolve either. As a side effect most
# phones open the setup page on their own after connecting.

_DNS_PORT = 53
_MAX_QUERY_BYTES = 512  # classic DNS-over-UDP limit
_TYPE_A = 1
_TTL_SECONDS = 60


def build_response(query, ip_bytes):
    """Answer to one raw DNS query, or None if it is not a usable query."""
    if len(query) < 12 or query[2] & 0x80:  # too short, or itself a response
        return None
    if ((query[4] << 8) | query[5]) < 1:  # no question
        return None
    end = 12
    while end < len(query) and query[end] != 0:
        end += query[end] + 1
    if end + 5 > len(query):  # name runs past the packet, or no type/class
        return None
    qtype = (query[end + 1] << 8) | query[end + 2]
    question = query[12:end + 5]
    answer_count = b'\x00\x01' if qtype == _TYPE_A else b'\x00\x00'
    # Same ID, flags = response + recursion desired/available, one question.
    response = query[0:2] + b'\x81\x80\x00\x01' + answer_count + b'\x00\x00\x00\x00' + question
    if qtype == _TYPE_A:
        # Pointer to the name at offset 12, type A, class IN, TTL, 4-byte IP.
        response += (b'\xc0\x0c\x00\x01\x00\x01' + _TTL_SECONDS.to_bytes(4, 'big')
                     + b'\x00\x04' + ip_bytes)
    # Anything else (e.g. AAAA): empty answer, so clients fall back to IPv4.
    return response


class CatchAllDnsServer:
    def __init__(self, ip):
        self._ip_bytes = bytes(int(part) for part in ip.split('.'))
        self._socket = None

    def start(self):
        if self._socket is not None:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', _DNS_PORT))
        s.settimeout(0)
        self._socket = s

    def stop(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def poll(self):
        """Answers all queries waiting right now, never blocks."""
        if self._socket is None:
            return
        while True:
            try:
                query, address = self._socket.recvfrom(_MAX_QUERY_BYTES)
            except OSError:
                return  # nothing (more) waiting
            response = build_response(query, self._ip_bytes)
            if response is not None:
                try:
                    self._socket.sendto(response, address)
                except OSError:
                    pass
