#!/bin/bash
echo "[CMD[kill $*]CMD][CMD[disconnect]CMD]" | nc 127.0.0.1 5555
echo ""

