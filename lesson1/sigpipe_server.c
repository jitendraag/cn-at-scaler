#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>

int main() {
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(2026);
    bind(server_fd, (struct sockaddr*)&addr, sizeof(addr));
    listen(server_fd, 1);

    int client_fd = accept(server_fd, NULL, NULL);
    char buf[4096];
    int n = read(client_fd, buf, sizeof(buf));

    sleep(1); // give the client time to force-close the connection (RST)

    write(client_fd, buf, n); // peer already reset -> SIGPIPE here
    write(client_fd, buf, n); // not reached: SIGPIPE's default action kills the process

    return 0;
}
