# login_all_store_profiles.py

import subprocess
import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent


##SCRIPTS = [
##    "login_meijer_profile.py",
##    "login_aldi_profile.py",
##    "login_kroger_profile.py",
##    "login_walmart_profile.py",
##    "login_target_profile.py",
##    "login_costco_profile.py",
##]


SCRIPTS = [
    "login_meijer_profile.py",
]

def main():
    for script in SCRIPTS:
        script_path = THIS_DIR / script

        print("")
        print("=================================================")
        print(f"🚀 Running {script}")
        print("=================================================")
        print("")

        subprocess.run(
            [sys.executable, str(script_path)],
            check=False,
        )


if __name__ == "__main__":
    main()
