#pragma once

#include <winsock2.h>
#include <stddef.h>

SOCKET sock_connect(const char* host, unsigned short port);
void sock_close(SOCKET fd);
