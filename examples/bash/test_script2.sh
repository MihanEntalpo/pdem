#!/bin/bash
echo "[PDEM[progressenabled]PDEM]"
LIMIT=30
for ((A=0 ; A<=LIMIT; A++)) ; do

sleep 1

echo $A 

#echo "[PROGRESS[";

PROGRESS=$(echo "$A*100/$LIMIT" | bc);

echo "testtesttest"
echo "[PDEM[progress=$PROGRESS]PDEM]"
sleep 1

done

