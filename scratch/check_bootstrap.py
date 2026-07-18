import sys

try:
    import paramiko
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

def reset_db_only():
    host = "43.98.188.191"
    user = "root"
    secret = "CosmosQPass123!"
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=user, password=secret, timeout=10)
        
        reset_sql = "UPDATE memories SET status='ACTIVE', schema_id=NULL; DELETE FROM schemas;"
        cmd = f"PGPASSWORD='ChooseAStrongDbPassword12345741!' psql -h pgm-gs5gg835teb7r0on.pgsql.singapore.rds.aliyuncs.com -U cosmos -d cosmos_q -c \"{reset_sql}\""
        
        print(f"Executing database reset: {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')
        if out:
            print(out.strip())
        if err:
            print(f"ERR/LOG: {err.strip()}")
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    reset_db_only()
