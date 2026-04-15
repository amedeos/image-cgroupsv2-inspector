package main

import (
	"fmt"
	"os"
	"os/signal"
	"runtime"
	"syscall"
)

func main() {
	fmt.Printf("go-v2-compliant-runtime: Go %s, GOMAXPROCS=%d\n", runtime.Version(), runtime.GOMAXPROCS(0))
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
	<-sig
}
