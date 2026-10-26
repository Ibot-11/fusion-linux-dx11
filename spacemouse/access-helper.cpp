// SPDX-License-Identifier: GPL-3.0-or-later
// No command-line options or environment-defined paths/commands are accepted.
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static constexpr const char *directory = "/etc/udev/rules.d";
static constexpr const char *filename = "70-fusion-spacemouse.rules";
static constexpr const char *rule =
    "# Fusion Manager: active-seat access to the 3Dconnexion Universal Receiver.\n"
    "SUBSYSTEM==\"hidraw\", KERNEL==\"hidraw*\", ATTRS{idVendor}==\"256f\", "
    "ATTRS{idProduct}==\"c652\", TAG+=\"uaccess\"\n";

static int fail(const char *message) {
    std::fprintf(stderr, "%s: %s\n", message, std::strerror(errno));
    return 1;
}

static int existing_rule(int dir) {
    int fd = openat(dir, filename, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return errno == ENOENT ? 0 : -1;
    struct stat info{};
    char data[1024];
    const ssize_t count = read(fd, data, sizeof(data));
    const bool valid = fstat(fd, &info) == 0 && S_ISREG(info.st_mode) && info.st_uid == 0 &&
                       !(info.st_mode & 0022) && count == static_cast<ssize_t>(std::strlen(rule)) &&
                       std::memcmp(data, rule, std::strlen(rule)) == 0;
    close(fd);
    if (!valid) {
        errno = EEXIST;
        return -1;
    }
    return 1;
}

int main(int argc, char **) {
    if (argc != 1) {
        std::fprintf(stderr, "This device-access helper accepts no arguments.\n");
        return 2;
    }
    if (geteuid() != 0) {
        std::fprintf(stderr,
                     "Administrator approval is required. Use Set up access in Fusion Manager.\n");
        return 1;
    }
    int dir = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (dir < 0)
        return fail("Could not open the udev rules folder");
    struct stat info{};
    if (fstat(dir, &info) != 0 || info.st_uid != 0 || (info.st_mode & 0022)) {
        close(dir);
        errno = EPERM;
        return fail("Unsafe udev rules folder");
    }
    int existing = existing_rule(dir);
    if (existing < 0) {
        close(dir);
        return fail("An existing unrelated or unsafe rule file was preserved");
    }
    if (!existing) {
        const std::string temporary = ".fusion-spacemouse-" + std::to_string(getpid()) + ".tmp";
        int fd = openat(dir, temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0644);
        if (fd < 0) {
            close(dir);
            return fail("Could not create the rule file");
        }
        size_t done = 0;
        const size_t length = std::strlen(rule);
        while (done < length) {
            const ssize_t count = write(fd, rule + done, length - done);
            if (count < 0 && errno == EINTR)
                continue;
            if (count <= 0)
                break;
            done += static_cast<size_t>(count);
        }
        const bool complete = done == length && fchmod(fd, 0644) == 0 && fsync(fd) == 0;
        close(fd);
        // linkat creates the final file only when its name is still free.
        const bool installed = complete && linkat(dir, temporary.c_str(), dir, filename, 0) == 0;
        const int saved = errno;
        unlinkat(dir, temporary.c_str(), 0);
        if (!installed) {
            close(dir);
            errno = saved;
            return fail("Could not safely install the rule");
        }
        fsync(dir);
    }
    close(dir);
    pid_t child = fork();
    if (child < 0)
        return fail("Could not reload udev rules");
    if (child == 0) {
        char *const arguments[] = {const_cast<char *>("udevadm"), const_cast<char *>("control"),
                                   const_cast<char *>("--reload-rules"), nullptr};
        execv("/usr/bin/udevadm", arguments);
        _exit(127);
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR)
            return fail("Could not wait for udevadm");
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        std::fprintf(stderr, "The rule was saved, but udev could not reload it. "
                             "Restart the system and reconnect the receiver.\n");
        return 1;
    }
    std::puts("Device access configured. Unplug and reconnect the Universal Receiver. An "
              "active local desktop session is required.");
    return 0;
}
