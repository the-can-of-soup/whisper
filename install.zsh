#!/usr/bin/zsh

if [ -e .venv ]; then
  flit install --python .venv/bin/python;
else
  flit install;
fi
