#!/usr/bin/env python

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "ای بابا "
            "فکر کنم یا جنگو نصب نکردی  "
            "یا محیط مجازی ات لالا کرده"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
