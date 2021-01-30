#!/bin/sh
grep -lZRPi '^kind:\s+secret' $1 | xargs -r0 grep -L 'ENC.AES256'
