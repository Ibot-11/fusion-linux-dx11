#include <winsock2.h>
#include <ws2tcpip.h>
#include <string.h>
#include "sock.h"
#include "log.h"

// Only the receive thread connects. Winsock stays live until process exit.
static bool wsa_started = false;

SOCKET sock_connect(const char *host, unsigned short port)
{
    if (!wsa_started) {
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2, 2), &wsa)) return INVALID_SOCKET;
        wsa_started = true;
    }
    SOCKET fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (fd == INVALID_SOCKET) return fd;
    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
        sock_close(fd);
        return INVALID_SOCKET;
    }
    // Bounded connection attempts keep teardown responsive even without a driver.
    u_long nonblocking = 1;
    if (ioctlsocket(fd, FIONBIO, &nonblocking) == SOCKET_ERROR) {
        sock_close(fd);
        return INVALID_SOCKET;
    }
    if (connect(fd, (sockaddr *)&addr, sizeof(addr)) == SOCKET_ERROR) {
        if (WSAGetLastError() != WSAEWOULDBLOCK) {
            sock_close(fd);
            return INVALID_SOCKET;
        }
        fd_set writable, failed;
        FD_ZERO(&writable); FD_ZERO(&failed);
        FD_SET(fd, &writable); FD_SET(fd, &failed);
        timeval timeout = {0, 200000};
        int error = 0, length = sizeof(error);
        if (select(0, NULL, &writable, &failed, &timeout) <= 0 ||
            FD_ISSET(fd, &failed) ||
            getsockopt(fd, SOL_SOCKET, SO_ERROR, (char *)&error, &length) == SOCKET_ERROR || error) {
            sock_close(fd);
            return INVALID_SOCKET;
        }
    }
    nonblocking = 0;
    if (ioctlsocket(fd, FIONBIO, &nonblocking) == SOCKET_ERROR) {
        sock_close(fd);
        return INVALID_SOCKET;
    }
    int nodelay = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, (char *)&nodelay, sizeof(nodelay));
    return fd;
}

void sock_close(SOCKET fd)
{
    if (fd != INVALID_SOCKET) closesocket(fd);
}
