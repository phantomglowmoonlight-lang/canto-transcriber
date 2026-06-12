"""
PyInstaller 啟動包裝器：修復 Python 3.10.0 的 dis.py bytecode 掃描 bug
"""
import dis
import sys

# Monkey-patch _get_const_info to handle out-of-range constant indices
_original_get_const_info = dis._get_const_info

def _patched_get_const_info(arg, constants):
    try:
        return _original_get_const_info(arg, constants)
    except IndexError:
        # Python 3.10.0 bug: EXTENDED_ARG with invalid const index
        return (None, "<?>")


dis._get_const_info = _patched_get_const_info

# Now run PyInstaller
if __name__ == "__main__":
    from PyInstaller.__main__ import run as pyi_run
    sys.argv = [sys.argv[0]] + sys.argv[1:] if len(sys.argv) > 1 else sys.argv
    pyi_run()
