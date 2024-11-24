import os
import datetime
import subprocess
import threading
import time
import traceback

# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Create a log file with timestamp
timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
log_file = f'logs/glances_log_{timestamp}.txt'

def log_output(process, log_file):
    """Log output from process to file in real-time"""
    with open(log_file, 'a') as f:
        # Create buffers for stdout and stderr
        stdout_buffer = []
        stderr_buffer = []
        
        while True:
            # Read output lines
            stdout_line = process.stdout.readline()
            stderr_line = process.stderr.readline()
            
            if stdout_line:
                stdout_buffer.append(stdout_line)
                if stdout_line.endswith('\n'):
                    f.write(f"[STDOUT] {''.join(stdout_buffer)}")
                    f.flush()
                    stdout_buffer = []
            
            if stderr_line:
                stderr_buffer.append(stderr_line)
                if stderr_line.endswith('\n'):
                    f.write(f"[STDERR] {''.join(stderr_buffer)}")
                    f.flush()
                    stderr_buffer = []
            
            # Write any remaining buffered content
            if process.poll() is not None:
                if stdout_buffer:
                    f.write(f"[STDOUT] {''.join(stdout_buffer)}")
                if stderr_buffer:
                    f.write(f"[STDERR] {''.join(stderr_buffer)}")
                break
            
            # If no new output and process ended, break
            if process.poll() is not None and not stdout_line and not stderr_line:
                break

# Initialize log file
with open(log_file, 'w') as f:
    f.write(f"=== Glances Log Started at {datetime.datetime.now()} ===\n\n")

try:
    # Set PYTHONPATH to include the current directory
    env = os.environ.copy()
    env['PYTHONPATH'] = os.getcwd()
    
    # Run glances from venv with debug logging
    glances_path = './venv/bin/glances'
    process = subprocess.Popen(
        [glances_path, '--debug'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,  # Line buffered
        env=env
    )
    
    print(f"Glances started with debug logging. Log file: {log_file}")
    
    # Start logging thread
    log_thread = threading.Thread(target=log_output, args=(process, log_file))
    log_thread.daemon = True
    log_thread.start()
    
    # Wait for process to complete
    process.wait()
    
except Exception as e:
    with open(log_file, 'a') as f:
        f.write(f"\n=== EXCEPTION ===\n{traceback.format_exc()}\n")
finally:
    with open(log_file, 'a') as f:
        f.write(f"\n=== Log Ended at {datetime.datetime.now()} ===\n")
