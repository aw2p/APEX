#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin ctypes bindings to libhidapi-hidraw.

Only the handful of calls the Apex Mini tool needs:
    init / exit / enumerate / open_path / close / write / read_timeout
    send_feature_report / get_feature_report

HID report notes used throughout the project:

    Linux hidraw feature report buffers include a leading *report id* byte.
    Our keyboard uses report id 0x00 for all of the lighting/control
    reports, so a "64-byte output report" is kept as a 65-byte buffer whose
    first byte is 0x00, and a "512-byte feature report" is a 513-byte buffer
    whose first byte is 0x00.  (Same convention OpenRGB uses.)

    Interrupt output reports via hid_write() on Linux need the buffer to be
    ``report_len + 1`` bytes as well (id byte first).
"""

import ctypes
import ctypes.util
import os
import struct

_STEELSERIES_VID = 0x1038


class HidError(RuntimeError):
    pass


def _load_library():
    for name in ("hidapi-hidraw", "hidapi"):
        path = ctypes.util.find_library(name)
        if path:
            lib = ctypes.CDLL(path)
            lib.hid_init.restype = ctypes.c_int
            lib.hid_init.argtypes = []
            if lib.hid_init() == 0:
                return lib, name
            raise HidError("hid_init() failed for %s" % name)
    raise HidError(
        "libhidapi-hidraw not found; install hidapi (e.g. "
        "'sudo apt install libhidapi-hidraw0' or the equivalent package for your distro)"
    )


_LIB, _LIB_NAME = _load_library()


class HidDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("path", ctypes.c_char_p),
        ("vendor_id", ctypes.c_ushort),
        ("product_id", ctypes.c_ushort),
        ("release_number", ctypes.c_ushort),
        ("serial_number", ctypes.c_wchar_p),
        ("release_string", ctypes.c_wchar_p),
        ("manufacturer_string", ctypes.c_wchar_p),
        ("product_string", ctypes.c_wchar_p),
        ("usage_page", ctypes.c_ushort),
        ("usage", ctypes.c_ushort),
        ("interface_number", ctypes.c_int),
        ("next", ctypes.c_void_p),
    ]


# --- prototype bindings -------------------------------------------------
_LIB.hid_exit.restype = ctypes.c_int
_LIB.hid_exit.argtypes = []

_LIB.hid_enumerate.restype = ctypes.POINTER(HidDeviceInfo)
_LIB.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]

_LIB.hid_free_enumeration.restype = None
_LIB.hid_free_enumeration.argtypes = [ctypes.POINTER(HidDeviceInfo)]

_LIB.hid_open_path.restype = ctypes.c_void_p
_LIB.hid_open_path.argtypes = [ctypes.c_char_p]

_LIB.hid_close.restype = None
_LIB.hid_close.argtypes = [ctypes.c_void_p]

_LIB.hid_write.restype = ctypes.c_int
_LIB.hid_write.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]

_LIB.hid_read.restype = ctypes.c_int
_LIB.hid_read.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]

_LIB.hid_read_timeout.restype = ctypes.c_int
_LIB.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t, ctypes.c_int]

_LIB.hid_send_feature_report.restype = ctypes.c_int
_LIB.hid_send_feature_report.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]

_LIB.hid_get_feature_report.restype = ctypes.c_int
_LIB.hid_get_feature_report.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]

_LIB.hid_set_nonblocking.restype = ctypes.c_int
_LIB.hid_set_nonblocking.argtypes = [ctypes.c_void_p, ctypes.c_int]

_LIB.hid_error.restype = ctypes.c_wchar_p
_LIB.hid_error.argtypes = [ctypes.c_void_p]


def _error(dev=None):
    try:
        msg = _LIB.hid_error(dev)
        return str(msg) if msg else "<no error>"
    except Exception:
        return "<no error>"


def enumerate_devices(vid=0, pid=0):
    """Return a list of dicts for every HID top-level collection visible to us."""
    out = []
    head = _LIB.hid_enumerate(vid, pid)
    try:
        cur = head
        while cur and cur[0]:
            d = cur[0]
            out.append(
                {
                    "path": d.path.decode("utf-8", "replace") if d.path else "",
                    "vendor_id": d.vendor_id,
                    "product_id": d.product_id,
                    "serial_number": d.serial_number or "",
                    "manufacturer": d.manufacturer_string or "",
                    "product": d.product_string or "",
                    "usage_page": d.usage_page,
                    "usage": d.usage,
                    "interface_number": d.interface_number,
                }
            )
            cur = ctypes.cast(d.next, ctypes.POINTER(HidDeviceInfo))
    finally:
        _LIB.hid_free_enumeration(head)
    return out


def open_path(path):
    dev = _LIB.hid_open_path(path.encode("utf-8"))
    if not dev:
        raise HidError(
            "failed to open %r: %s\n"
            "    hint: grant access with  sudo bash setup/00-grant-access.sh\n"
            "    (installs a udev rule for the steelseries vendor keyboard sink + reloads)"
            % (path, _error(None)))
    return dev


def close(dev):
    if dev:
        _LIB.hid_close(dev)


def write_output(dev, data):
    """Write an output (interrupt) report.  ``data[0]`` must be the report id."""
    buf = (ctypes.c_char * len(data))(*data)
    n = _LIB.hid_write(dev, buf, len(data))
    if n == -1:
        raise HidError("hid_write failed: %s" % _error(dev))
    return n


def read_timeout(dev, size, try_ms):
    buf = (ctypes.c_char * size)()
    n = _LIB.hid_read_timeout(dev, buf, size, try_ms)
    if n == -1:
        raise HidError("hid_read failed: %s" % _error(dev))
    return bytes(bytearray(buf)[:n]) if n > 0 else bytes()


def send_feature(dev, data):
    """Send a feature report.  ``data[0]`` must be the report id (0x00 here)."""
    buf = (ctypes.c_char * len(data))(*data)
    n = _LIB.hid_send_feature_report(dev, buf, len(data))
    if n == -1:
        raise HidError("hid_send_feature_report failed: %s" % _error(dev))
    return n


def get_feature(dev, size):
    """Read a feature report; the first byte of ``buffer`` is the report id to fetch."""
    buf = (ctypes.c_char * size)(0)
    n = _LIB.hid_get_feature_report(dev, buf, size)
    if n == -1:
        raise HidError("hid_get_feature_report failed: %s" % _error(dev))
    return bytes(bytearray(buf)[:n]) if n > 0 else bytes()


def le16(v):
    return struct.pack("<H", v)


def report_len_of_feature_from_sysfs(devpath_or_bus_path):
    """Optional helper stub; real parser lives in ``apexmini.reportdesc``."""
    raise NotImplementedError
