#pragma once

#include <winsock2.h>
#include <stddef.h>

SOCKET sock_connect(const char* host, unsigned short port);
int sock_read(SOCKET fd, char* buf, size_t count);
void sock_shutdown(SOCKET fd);
void sock_close(SOCKET fd);
