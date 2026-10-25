/* SpaceMouse Wine relay; GPL-3.0-or-later, derived from Lolig4/DD1984 spconvd.
 * Both peers use eight little-endian int32s. Preserve complete packets,
 * their period, and zero-motion events unchanged.
 */
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping = 1; }

static int connect_driver(void)
{
    const char *path = getenv("SPNAV_SOCKET");
    if (!path || !*path) path = "/var/run/spnav.sock";
    struct sockaddr_un addr = {.sun_family = AF_UNIX};
    if (strlen(path) >= sizeof(addr.sun_path)) { errno = ENAMETOOLONG; return -1; }
    strcpy(addr.sun_path, path);
    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd >= 0 && connect(fd, (struct sockaddr *)&addr, sizeof(addr))) {
        close(fd); return -1;
    }
    return fd;
}

static int send_packet(int fd, const void *packet, size_t size)
{
    size_t offset = 0;
    while (offset < size && !stopping) {
        struct pollfd p = {.fd = fd, .events = POLLOUT};
        int rc = poll(&p, 1, 500);
        if (rc < 0 && errno == EINTR) continue;
        if (rc <= 0 || (p.revents & (POLLERR | POLLHUP | POLLNVAL))) return -1;
        ssize_t n = send(fd, (const char *)packet + offset, size - offset,
                         MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) return -1;
        offset += (size_t)n;
    }
    return offset == size ? 0 : -1;
}

static void relay(int client, int driver)
{
    uint8_t packet[8 * sizeof(int32_t)];
    size_t used = 0;
    struct pollfd fds[] = {{client, POLLIN, 0}, {driver, POLLIN, 0}};
    while (!stopping) {
        int rc = poll(fds, 2, -1);
        if (rc < 0 && errno == EINTR) continue;
        if (rc < 0 || fds[0].revents) break;
        if (fds[1].revents & POLLIN) {
            ssize_t n = read(driver, packet + used, sizeof(packet) - used);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            used += (size_t)n;
            if (used == sizeof(packet)) {
                if (send_packet(client, packet, sizeof(packet))) break;
                used = 0;
            }
        } else if (fds[1].revents & (POLLHUP | POLLERR | POLLNVAL)) break;
    }
}

int main(int argc, char **argv)
{
    int ready_fd = -1;
    if (argc == 3 && !strcmp(argv[1], "--ready-fd")) {
        char *end;
        long value = strtol(argv[2], &end, 10);
        if (*end || value < 0 || value > 1024) return 2;
        ready_fd = (int)value;
    } else if (argc != 1) return 2;
    struct sigaction action = {.sa_handler = stop};
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    signal(SIGPIPE, SIG_IGN);
    int server = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (server < 0) { perror("socket"); return 1; }
    int reuse = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(11111),
                              .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    if (bind(server, (struct sockaddr *)&addr, sizeof(addr)) || listen(server, 4)) {
        perror("SpaceMouse listen 127.0.0.1:11111"); close(server); return 1;
    }
    int probe = connect_driver();
    if (probe < 0) { perror("SpaceMouse driver"); close(server); return 1; }
    close(probe);
    if (ready_fd >= 0) {
        if (write(ready_fd, "R", 1) != 1) { close(server); return 1; }
        close(ready_fd);
    }
    while (!stopping) {
        struct pollfd p = {server, POLLIN, 0};
        int rc = poll(&p, 1, -1);
        if (rc < 0 && errno == EINTR) continue;
        if (rc <= 0 || !(p.revents & POLLIN)) break;
        int client = accept(server, NULL, NULL);
        if (client < 0) continue;
        int driver = connect_driver();
        if (driver >= 0) { relay(client, driver); close(driver); }
        close(client);
    }
    close(server);
    return 0;
}
