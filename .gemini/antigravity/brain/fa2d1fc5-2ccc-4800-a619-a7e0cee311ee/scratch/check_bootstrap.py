import sys

try:
    import paramiko
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

def grant_schema_fix():
    host = "43.98.188.191"
    user = "root"
    secret = "CosmosQPass123!"
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=user, password=secret, timeout=10)
        
        pg_host = "pgm-gs5gg835teb7r0on.pgsql.singapore.rds.aliyuncs.com"
        pg_pass = "ChooseAStrongDbPassword12345741!"
        
        commands = [
            f"PGPASSWORD='{pg_pass}' psql -h {pg_host} -U cosmos -d cosmos_q -c 'CREATE SCHEMA IF NOT EXISTS cosmos AUTHORIZATION cosmos; ALTER ROLE cosmos SET search_path TO cosmos, public;'",
            "docker restart cosmos-q",
            "sleep 3",
            "docker ps -a",
            "docker logs cosmos-q",
            "curl -s http://localhost:8765/health"
        ]
        
        for cmd in commands:
            print(f"\n=== Executing: {cmd} ===")
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
    grant_schema_fix()
