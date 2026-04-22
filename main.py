"""
DeepDive - Multi-Agent News Analysis Tool
Run with: streamlit run dashboard.py
"""
import subprocess
import sys


def main():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py"], cwd=".")


if __name__ == "__main__":
    main()
