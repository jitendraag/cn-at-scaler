#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/select.h>

int main() {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(2026);
    bind(server_fd, (struct sockaddr*)&addr, sizeof(addr));
    listen(server_fd, 16);

    int clients[FD_SETSIZE];
    int nclients = 0;

    while (1) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(server_fd, &readfds);
        int maxfd = server_fd;

        for (int i = 0; i < nclients; i++) {
            FD_SET(clients[i], &readfds);
            if (clients[i] > maxfd) maxfd = clients[i];
        }

        select(maxfd + 1, &readfds, NULL, NULL, NULL);

        if (FD_ISSET(server_fd, &readfds)) {
            clients[nclients++] = accept(server_fd, NULL, NULL);
        }

        for (int i = 0; i < nclients; i++) {
            int fd = clients[i];
            if (!FD_ISSET(fd, &readfds)) continue;

            char buf[4096];
            int n = read(fd, buf, sizeof(buf));
            if (n <= 0) {
                close(fd);
                clients[i] = clients[--nclients];
                i--;
            } else {
                write(fd, buf, n);
            }
        }
    }
}
