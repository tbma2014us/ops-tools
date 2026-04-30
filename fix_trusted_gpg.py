#!/usr/bin/env python3
# Fixes: Warning: Key is stored in legacy trusted.gpg keyring (/etc/apt/trusted.gpg), see the DEPRECATION section in apt-key(8) for details.

import subprocess
import os
import re

def run_command(command):
    """
    Runs a shell command and returns its output.
    Raises an exception if the command fails.
    """
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"Successfully executed: {command}")
        print(result.stdout)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        print(f"Error output: {e.stderr}")
        raise

def get_deprecated_trusted_gpg_short_keys():
    """
    Parses apt-key list output and returns the last 64-bit segment of
    all fingerprints from the deprecated /etc/apt/trusted.gpg section.
    """
    output = subprocess.check_output(['apt-key', 'list'], stderr=subprocess.STDOUT, text=True)
    lines = output.splitlines()

    keys = []
    in_deprecated_section = False

    for line in lines:
        if line.strip() == "/etc/apt/trusted.gpg":
            in_deprecated_section = True
            continue
        elif line.startswith("/etc/apt/trusted.gpg.d/"):
            in_deprecated_section = False

        if in_deprecated_section:
            # Match full fingerprint (10 groups of 4 hex digits)
            match = re.search(r'((?:[A-F0-9]{4}\s+){9}[A-F0-9]{4})', line.strip().upper())
            if match:
                groups = match.group(0).split()
                short_key = ''.join(groups[-4:])  # concatenate last 4 groups
                keys.append(short_key)

    return keys

def fix_apt_error():
    """
    Automates the process of fixing the apt trusted.gpg error by moving
    a key to trusted.gpg.d and deleting it from trusted.gpg.
    """
    print("Starting APT key fix process...")

    # Step 1: Make a backup of trusted.gpg
    print("\nStep 1: Backing up /etc/apt/trusted.gpg...")
    try:
        os.chdir("/etc/apt")
        run_command("cp trusted.gpg trusted.gpg.bak")
        print("Backup created: /etc/apt/trusted.gpg.bak")
    except Exception as e:
        print(f"Failed to create backup: {e}")
        return

    # Step 2: Extract key IDs from deprecated trusted.gpg section
    print("\nStep 2: Extracting keys from deprecated trusted.gpg...")
    try:
        deprecated_keys = get_deprecated_trusted_gpg_short_keys()
    except Exception as e:
        print(f"Failed to parse deprecated keys: {e}")
        return

    if not deprecated_keys:
        print("No keys found in /etc/apt/trusted.gpg. Exiting.")
        return

    # Pick the first key found
    key_id = deprecated_keys[0]
    print(f"Found deprecated key: {key_id}")

    # Step 3: Export the key
    print(f"\nStep 3: Exporting key {key_id} to /etc/apt/trusted.gpg.d/migrated-key-{key_id}.gpg...")
    export_command = f"apt-key export {key_id} | gpg --dearmor -o /etc/apt/trusted.gpg.d/migrated-key-{key_id}.gpg"
    try:
        run_command(export_command)
        print(f"Key exported to /etc/apt/trusted.gpg.d/migrated-key-{key_id}.gpg")
    except Exception:
        print("Failed to export key. Exiting.")
        return

    # Step 4: Delete the key from trusted.gpg
    print(f"\nStep 4: Deleting key {key_id} from /etc/apt/trusted.gpg...")
    delete_command = f"apt-key --keyring /etc/apt/trusted.gpg del {key_id}"
    try:
        run_command(delete_command)
        print(f"Key {key_id} deleted from /etc/apt/trusted.gpg")
    except Exception:
        print("Failed to delete key from trusted.gpg. Please check manually. Exiting.")
        return

    # Step 5: Verify the warning is gone
    print("\nStep 5: Verifying apt update (checking if warning is gone)...")
    try:
        run_command("apt update")
        print("\nAPT update completed. If no warnings related to the key appeared, the fix was successful.")
    except Exception:
        print("\nAPT update still showing errors or warnings. Please check manually.")

    print("\nAPT key fix process completed.")

if __name__ == "__main__":
    # Ensure the script is run as root
    if os.geteuid() != 0:
        print("This script must be run as root. Please use 'sudo python3 fix_trusted_gpg.py'")
    else:
        fix_apt_error()

