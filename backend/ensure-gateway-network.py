"""Restore the dedicated network attachment after gateway container recreation."""
import json,os,subprocess
from pathlib import Path
gateway=os.environ.get('ANNOTATION_GATEWAY','kurumi-production-gateway-1')
result=subprocess.run(['docker','inspect',gateway],capture_output=True,text=True)
if result.returncode==0:
    container=json.loads(result.stdout)[0]
    if 'cooking-annotation' not in container['NetworkSettings']['Networks']:
        subprocess.run(['docker','network','connect','cooking-annotation',gateway],check=True)
    source=os.environ.get('ANNOTATION_CADDY_SOURCE')
    if source and Path(source).is_file() and 'label.kurumimarket.store' in Path(source).read_text():
        active=subprocess.run(['docker','exec',gateway,'wget','-qO-','http://127.0.0.1:2019/config/'],capture_output=True,text=True,check=True)
        config=json.loads(active.stdout)
        hosts=[host for server in config.get('apps',{}).get('http',{}).get('servers',{}).values() for route in server.get('routes',[]) for match in route.get('match',[]) for host in match.get('host',[])]
        if 'label.kurumimarket.store' not in hosts:
            subprocess.run(['docker','cp',source,gateway+':/tmp/Caddyfile.annotation-current'],check=True,capture_output=True)
            subprocess.run(['docker','exec',gateway,'caddy','validate','--config','/tmp/Caddyfile.annotation-current','--adapter','caddyfile'],check=True,capture_output=True)
            subprocess.run(['docker','exec',gateway,'caddy','reload','--config','/tmp/Caddyfile.annotation-current','--adapter','caddyfile'],check=True,capture_output=True)
