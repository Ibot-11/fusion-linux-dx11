#include <winsock2.h>
#include <ws2tcpip.h>
#include <string.h>
#include "sock.h"
#include "log.h"

/* Winsock is started once and never cleaned up: the connection lives as long as
 * the DLL is loaded, and WSACleanup() during teardown would race the receive
 * thread. The reference is released when the process exits. */
static bool wsa_started = false;

SOCKET sock_connect(const char *host, unsigned short port)
{
	if (!wsa_started) {
		WSADATA wsa;
		int err = WSAStartup(MAKEWORD(2, 2), &wsa);
		if (err) {
			LOG(ERROR) << "WSAStartup() failed: " << err;
			return INVALID_SOCKET;
		}
		wsa_started = true;
	}

	LOG(INFO) << "Creating socket";

	SOCKET fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
	if (fd == INVALID_SOCKET) {
		LOG(ERROR) << "socket() failed: " << WSAGetLastError();
		LOG(ERROR) << "Failed to create socket";
		return INVALID_SOCKET;
	}

	LOG(INFO) << "fd: " << fd;

	struct sockaddr_in addr;
	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_port = htons(port);
	if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
		LOG(ERROR) << "not an IPv4 address: " << host;
		sock_close(fd);
		return INVALID_SOCKET;
	}

	LOG(INFO) << "Attempting to connect to " << host << ":" << port;

	if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) == SOCKET_ERROR) {
		LOG(ERROR) << "connect() failed: " << WSAGetLastError();
		LOG(ERROR) << "Failed to connect";
		sock_close(fd);
		return INVALID_SOCKET;
	}

	return fd;
}

/* Reads exactly count bytes. The daemon writes one event per write(), but TCP
 * is free to split it across segments, so a single recv() is not enough. */
int sock_read(SOCKET fd, char *buf, size_t count)
{
	size_t done = 0;

	while (done < count) {
		int ret = recv(fd, buf + done, (int)(count - done), 0);
		if (ret == 0)
			return 0;
		if (ret == SOCKET_ERROR) {
			LOG(ERROR) << "recv() failed: " << WSAGetLastError();
			return -1;
		}
		done += ret;
	}

	return (int)done;
}

/* Unblocks a receive thread sitting in recv(): the pending call returns 0 as if
 * the peer had closed. Closing the socket under it instead fails with
 * WSAEINVAL and leaves the thread to be killed. */
void sock_shutdown(SOCKET fd)
{
	if (fd != INVALID_SOCKET)
		shutdown(fd, SD_BOTH);
}

void sock_close(SOCKET fd)
{
	if (fd != INVALID_SOCKET)
		closesocket(fd);
}
