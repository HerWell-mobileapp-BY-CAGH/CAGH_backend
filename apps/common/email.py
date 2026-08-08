import socket
from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend


class IPv4EmailBackend(DjangoEmailBackend):
    """
    Custom SMTP Email Backend that forces IPv4 (socket.AF_INET) socket resolution.
    Fixes '[Errno 101] Network is unreachable' on cloud hosts (Render, AWS, DigitalOcean)
    where outbound IPv6 routing is disabled or blocked.
    """

    def open(self):
        if self.connection:
            return False

        orig_getaddrinfo = socket.getaddrinfo

        def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            # Force AF_INET (IPv4)
            return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

        socket.getaddrinfo = ipv4_getaddrinfo
        try:
            return super().open()
        finally:
            socket.getaddrinfo = orig_getaddrinfo
