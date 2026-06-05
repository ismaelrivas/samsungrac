import re

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

print(repr(strip_ansi('\033[91m-hello\033[0m')))
