#!/bin/bash
sleep 5
export DISPLAY=:0
cd /home/project/Desktop/chicken
exec /usr/bin/python3 main.py >> /home/project/Desktop/chicken/run.log 2>&1
