#!/bin/bash
watch -n1 'echo "[CMD[proclist showdead]CMD]" | nc 127.0.0.1 5555 -q 1 '



