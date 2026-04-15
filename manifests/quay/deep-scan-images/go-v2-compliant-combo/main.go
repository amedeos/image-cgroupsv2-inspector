package main

import (
	"fmt"
	"os"
	"os/signal"
	"runtime"
	"runtime/debug"
	"syscall"

	_ "github.com/KimMachineGun/automemlimit"
	_ "go.uber.org/automaxprocs"
)

func main() {
	memlimit := debug.SetMemoryLimit(-1)
	fmt.Printf("go-v2-compliant-combo: Go %s, GOMAXPROCS=%d, GOMEMLIMIT=%d\n",
		runtime.Version(), runtime.GOMAXPROCS(0), memlimit)
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM, syscall.SIGINT)
	<-sig
}
