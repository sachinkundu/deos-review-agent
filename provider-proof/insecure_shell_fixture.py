"""Controlled unsafe fixture used only to prove provider-originated review comments."""

import subprocess


def run_user_command(user_input: str) -> None:
    """Deliberately vulnerable: the review bot must flag this changed line."""
    subprocess.run(f"sh -c '{user_input}'", shell=True, check=True)
