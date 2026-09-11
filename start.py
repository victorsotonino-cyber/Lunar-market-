#!/usr/bin/env python3
"""
start.py

Buscador/launcher flexible para entornos donde el archivo principal puede tener distintos nombres
(e.g., bot.py, bot_Version3.py, main.py). El script busca un archivo .py apropiado y lo ejecuta.
"""
import os
import sys

EXCLUDE = {"start.py"}

def find_entry():
    files = [f for f in os.listdir('.') if f.endswith('.py') and f not in EXCLUDE]
    if not files:
        return None
    # prefer explicit names
    prefs = ['bot.py', 'main.py', 'app.py']
    for p in prefs:
        if p in files:
            return p
    # prefer files that start with bot
    for f in files:
        if f.lower().startswith('bot'):
            return f
    # otherwise return the first one
    return sorted(files)[0]

if __name__ == '__main__':
    entry = find_entry()
    if not entry:
        print('Error: no Python entry file found in repo. Expected bot.py, main.py o similar.')
        sys.exit(1)
    print(f"Launching entry file: {entry}")
    os.execv(sys.executable, [sys.executable, entry] + sys.argv[1:])
