"""Hue Entertainment streaming: DTLS-PSK over UDP via the system libssl (ctypes)."""
import ctypes
import ctypes.util
import socket
import struct

_ssl = ctypes.CDLL(ctypes.util.find_library("ssl") or "libssl.so.3")
_vp = ctypes.c_void_p
for name, res, args in [
    ("DTLS_client_method", _vp, []),
    ("SSL_CTX_new", _vp, [_vp]),
    ("SSL_CTX_free", None, [_vp]),
    ("SSL_CTX_set_cipher_list", ctypes.c_int, [_vp, ctypes.c_char_p]),
    ("SSL_CTX_set_psk_client_callback", None, [_vp, _vp]),
    ("SSL_new", _vp, [_vp]),
    ("SSL_free", None, [_vp]),
    ("SSL_set_bio", None, [_vp, _vp, _vp]),
    ("SSL_connect", ctypes.c_int, [_vp]),
    ("SSL_write", ctypes.c_int, [_vp, ctypes.c_char_p, ctypes.c_int]),
    ("SSL_shutdown", ctypes.c_int, [_vp]),
    ("SSL_get_error", ctypes.c_int, [_vp, ctypes.c_int]),
    ("BIO_new_dgram", _vp, [ctypes.c_int, ctypes.c_int]),
    ("BIO_ctrl", ctypes.c_long, [_vp, ctypes.c_int, ctypes.c_long, _vp]),
    ("BIO_ADDR_new", _vp, []),
    ("BIO_ADDR_free", None, [_vp]),
    ("BIO_ADDR_rawmake", ctypes.c_int, [_vp, ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_ushort]),
]:
    fn = getattr(_ssl, name)
    fn.restype, fn.argtypes = res, args

BIO_CTRL_DGRAM_SET_CONNECTED = 32

_PSK_CB = ctypes.CFUNCTYPE(
    ctypes.c_uint, _vp, ctypes.c_char_p, ctypes.POINTER(ctypes.c_char), ctypes.c_uint,
    ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint,
)


class HueStream:
    """Send frames to an entertainment area. Call start_area via REST first."""

    def __init__(self, bridge, username, clientkey, area_id):
        self.area = area_id.encode()
        identity = username.encode()
        psk = bytes.fromhex(clientkey)

        def cb(ssl, hint, ident_out, max_ident, psk_out, max_psk):
            if len(identity) + 1 > max_ident or len(psk) > max_psk:
                return 0
            ctypes.memmove(ident_out, identity + b"\0", len(identity) + 1)
            ctypes.memmove(psk_out, psk, len(psk))
            return len(psk)

        self._cb = _PSK_CB(cb)  # keep a reference so it isn't garbage collected
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Keep the socket blocking: OpenSSL's datagram BIO handles retransmits and timeouts.
        self.sock.connect((bridge, 2100))
        self.ctx = _ssl.SSL_CTX_new(_ssl.DTLS_client_method())
        _ssl.SSL_CTX_set_cipher_list(self.ctx, b"PSK-AES128-GCM-SHA256")
        _ssl.SSL_CTX_set_psk_client_callback(self.ctx, ctypes.cast(self._cb, _vp))
        self.ssl = _ssl.SSL_new(self.ctx)
        bio = _ssl.BIO_new_dgram(self.sock.fileno(), 0)  # BIO_NOCLOSE: socket owns the fd
        # Tell the BIO the socket is connected and to which peer (a NULL peer means "unconnected").
        peer = _ssl.BIO_ADDR_new()
        _ssl.BIO_ADDR_rawmake(peer, socket.AF_INET, socket.inet_aton(socket.gethostbyname(bridge)),
                              4, socket.htons(2100))
        _ssl.BIO_ctrl(bio, BIO_CTRL_DGRAM_SET_CONNECTED, 0, peer)
        _ssl.BIO_ADDR_free(peer)
        _ssl.SSL_set_bio(self.ssl, bio, bio)
        rc = _ssl.SSL_connect(self.ssl)
        if rc != 1:
            err = _ssl.SSL_get_error(self.ssl, rc)
            self.close()
            raise ConnectionError(f"DTLS handshake failed (SSL error {err})")
        self.seq = 0

    def send(self, colors):
        """colors: {channel_id: (x, y, brightness)} with each value 0.0-1.0 (CIE xy + brightness)."""
        hdr = b"HueStream" + bytes([2, 0, self.seq & 0xFF, 0, 0, 1, 0]) + self.area  # 1 = xy+bri
        body = b"".join(
            struct.pack(">BHHH", ch, *(int(max(0.0, min(1.0, v)) * 65535) for v in xyb))
            for ch, xyb in colors.items()
        )
        msg = hdr + body
        self.seq += 1
        if _ssl.SSL_write(self.ssl, msg, len(msg)) != len(msg):
            raise ConnectionError("DTLS write failed")

    def close(self):
        if self.ssl:
            _ssl.SSL_shutdown(self.ssl)
            _ssl.SSL_free(self.ssl)  # also frees the BIO
            self.ssl = None
        if self.ctx:
            _ssl.SSL_CTX_free(self.ctx)
            self.ctx = None
        self.sock.close()
