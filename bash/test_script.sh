#!/bin/bash
echo "[PDEM[progressenabled]PDEM]"
LIMIT=30
for ((A=0 ; A<=LIMIT; A++)) ; do

sleep 3

echo $A

#echo "[PROGRESS[";

PROGRESS=$(echo "$A*100/$LIMIT" | bc);

echo "[PDEM[progress=$PROGRESS]PDEM]";

echo "[PDEM[var:Preved=medved]PDEM]";
echo "[PDEM[var:A=$A]PDEM]";

done
echo "[PDEM[done]PDEM]"
