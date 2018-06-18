"""
Field types used in
https://www.brultech.com/software/files/downloadSoft/GEM-PKT_Packet_Format_2_1.pdf
"""
from datetime import datetime


class ByteField(object):
    size = 1

    def read(self, buffer, offset):
        return buffer[offset:offset + self.size]


class BytesField(object):
    def __init__(self, size):
        self.size = size

    def read(self, buffer, offset):
        return buffer[offset:offset + self.size]


class NumericField(object):
    def __init__(self, size, order_fn):
        self.size = size
        self.order_fn = order_fn

    def read(self, buffer, offset):
        return self.order_fn(buffer[offset : offset + self.size])

    @property
    def max(self):
        return 2 ** self.size


class FloatingPointField(object):
    def __init__(self, size, order_fn, divisor):
        self.raw_field = NumericField(size, order_fn)
        self.divisor = divisor

    @property
    def size(self):
        return self.raw_field.size

    def read(self, buffer, offset):
        return self.raw_field.read(buffer, offset) / self.divisor


class DateTimeField(object):
    size = 6

    def read(self, buffer, offset):
        year, month, day, hour, minute, second = \
            buffer[offset : offset + self.size]
        return datetime(2000 + year, month, day, hour, minute, second)


class ArrayField(object):
    def __init__(self, num_elems, elem_field):
        self.elem_field = elem_field
        self.num_elems = num_elems

    @property
    def size(self):
        return self.num_elems * self.elem_field.size

    def read(self, buffer, offset):
        return [
            self.elem_field.read(buffer, offset + i * self.elem_field.size)
            for i in range(self.num_elems)]


def hi_to_lo(octets):
    """Reads the given octets as a big-endian value. The function name comes
    from how such values are described in the packet format spec."""
    result = 0
    for octet in octets:
        result = (result << 8) + octet
    return result


def lo_to_hi(octets):
    """Reads the given octets as a little-endian value. The function name comes
    from how such values are described in the packet format spec."""
    return hi_to_lo(reversed(octets))


