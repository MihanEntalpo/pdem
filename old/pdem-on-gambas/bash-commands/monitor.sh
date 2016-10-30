#!/bin/bash
watch -n1 'echo "name | title | type | command"; echo "[CMD[proclist showdead]CMD][CMD[disconnect]CMD]" | nc 127.0.0.1 5555 | sed "s/\[ANS\[//g;s/\]ANS\]//g"'



