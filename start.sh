#!/bin/sh

# 优先运行已编译字节码，其次运行源码（便于生产加固与开发调试）
if [ -f "start.pyc" ]; then
  python3 start.pyc
else
  python3 start.py
fi
