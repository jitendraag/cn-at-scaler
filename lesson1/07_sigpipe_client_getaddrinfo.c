#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netdb.h>

int main() {
    struct addrinfo hints = {0};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    struct addrinfo *res;
    getaddrinfo("localhost", "2026", &hints, &res);

    int fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    connect(fd, res->ai_addr, res->ai_addrlen);
    freeaddrinfo(res);

    write(fd, "hello", 5);

    struct linger l = {1, 0}; // abortive close: sends RST instead of FIN
    setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof(l));
    close(fd);

    return 0;
}
