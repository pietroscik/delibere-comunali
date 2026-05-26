#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compat wrapper for the maintained scraper implementation.

The production scraper logic lives in ``new_albo_scraper.py``.
This file remains as the public CLI entrypoint to preserve backward
compatibility with existing commands and automation.
"""

from new_albo_scraper import main


if __name__ == "__main__":
    main()
