# nginx-from-scratch — CN & Scaler, Session 4
#
#   make            build everything
#   make run-fork   (etc.) build and run one server on its default port
#   make bigfile    make www/big.bin for the sendfile demo
#   make clean

CC      ?= cc
CFLAGS  ?= -O2 -g -Wall -Wextra -Wno-unused-result -std=gnu11
LDLIBS_THREAD = -pthread

BINS = 01-fork/forkd \
       02-thread/threadd \
       03-select/selectd \
       04-epoll/epolld \
       05-sendfile/sendfiled \
       06-fastcgi/fcgi_responder \
       06-fastcgi/fcgi_client

all: $(BINS)

01-fork/forkd:              01-fork/forkd.c common.h
	$(CC) $(CFLAGS) -o $@ $<
02-thread/threadd:          02-thread/threadd.c common.h
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS_THREAD)
03-select/selectd:          03-select/selectd.c common.h
	$(CC) $(CFLAGS) -o $@ $<
04-epoll/epolld:            04-epoll/epolld.c common.h
	$(CC) $(CFLAGS) -o $@ $<
05-sendfile/sendfiled:      05-sendfile/sendfiled.c common.h
	$(CC) $(CFLAGS) -o $@ $<
06-fastcgi/fcgi_responder:  06-fastcgi/fcgi_responder.c 06-fastcgi/fastcgi.h common.h
	$(CC) $(CFLAGS) -o $@ $<
06-fastcgi/fcgi_client:     06-fastcgi/fcgi_client.c 06-fastcgi/fastcgi.h common.h
	$(CC) $(CFLAGS) -o $@ $<

bigfile: www/big.bin
www/big.bin:
	dd if=/dev/urandom of=$@ bs=1M count=256 status=none
	@echo "made $@ ($$(du -h $@ | cut -f1))"

run-fork:     01-fork/forkd            ; ./01-fork/forkd 8001
run-thread:   02-thread/threadd        ; ./02-thread/threadd 8002
run-select:   03-select/selectd        ; ./03-select/selectd 8003
run-epoll:    04-epoll/epolld          ; ./04-epoll/epolld 8004
run-sendfile: 05-sendfile/sendfiled www/big.bin ; ./05-sendfile/sendfiled 8005 www/big.bin
run-fcgi:     06-fastcgi/fcgi_responder ; ./06-fastcgi/fcgi_responder 9000

clean:
	rm -f $(BINS)

distclean: clean
	rm -f www/big.bin

.PHONY: all clean distclean bigfile run-fork run-thread run-select run-epoll run-sendfile run-fcgi
