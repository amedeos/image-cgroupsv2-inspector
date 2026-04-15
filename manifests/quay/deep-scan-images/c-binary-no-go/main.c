#include <stdio.h>
#include <unistd.h>
#include <signal.h>

volatile sig_atomic_t running = 1;

void handle_signal(int sig) {
    running = 0;
}

int main() {
    signal(SIGTERM, handle_signal);
    signal(SIGINT, handle_signal);
    printf("c-binary-no-go: non-Go binary for testing\n");
    fflush(stdout);
    while(running) { sleep(3600); }
    return 0;
}
