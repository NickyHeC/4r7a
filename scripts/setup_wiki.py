#!/usr/bin/env python3
"""Standalone entry point for wiki initialization.

Can be run directly: python scripts/setup_wiki.py
Or through the CLI: company-brain init
"""

from company_brain.wiki.setup import run_init

if __name__ == "__main__":
    run_init()
