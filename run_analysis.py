#!/usr/bin/env python3
import subprocess
import sys
import os

# Change to the project directory
project_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_dir)

# Run the video analyzer
url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=rf_EQvubKlk"
result = subprocess.run([sys.executable, "tools/video-analyzer.py", url], 
                       capture_output=True, text=True, cwd=project_dir)

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print("\nReturn code:", result.returncode)