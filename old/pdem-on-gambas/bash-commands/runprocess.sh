#!/bin/bash
echo "[CMD[runprocess $1 $2 local $3]CMD][CMD[disconnect]CMD]" | nc 127.0.0.1 5555
echo ""

