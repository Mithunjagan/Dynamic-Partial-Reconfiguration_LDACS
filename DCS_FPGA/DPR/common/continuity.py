"""Validate recorded static-shell observations made during a PCAP transfer."""
import struct

FIELDS = ('version','samples','error','build_token','checks_passed',
          'before','after','min_delta','max_delta')


def valid_continuity(report, token=None):
    try:
        values = tuple(report[key] for key in FIELDS)
        if any(type(value) is not int or not 0 <= value <= (0xffffffff if i < 5 else 0xffffffffffffffff)
               for i,value in enumerate(values)):
            return False
        raw = bytes.fromhex(report['raw_response_hex'])
        if raw[:4] != b'DSCR' or len(raw) != 56 or struct.unpack('<5I4Q',raw[4:]) != values:
            return False
        version,samples,error,build,flags,before,after,minimum,maximum = values
        return (version == 1 and samples >= 2 and error == 0 and flags == 3 and
                (token is None or build == token) and before < after and
                0 < minimum <= maximum and
                minimum*(samples-1) <= after-before <= maximum*(samples-1))
    except (KeyError, ValueError, TypeError, struct.error):
        return False
