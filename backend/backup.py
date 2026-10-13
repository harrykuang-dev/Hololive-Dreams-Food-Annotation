"""Daily consistent SQLite backup; retain the latest 14 daily backups."""
import os,sqlite3
from datetime import datetime,timezone
from pathlib import Path
database=Path(os.environ.get('ANNOTATION_DATABASE','/data/progress.sqlite3'))
directory=database.parent/'backups'
directory.mkdir(exist_ok=True)
target=directory/('annotation-'+datetime.now(timezone.utc).strftime('%Y-%m-%d')+'.sqlite3')
source=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
backup=sqlite3.connect(target)
try:source.backup(backup)
finally:backup.close();source.close()
target.chmod(0o600)
for old in sorted(directory.glob('annotation-????-??-??.sqlite3'))[:-14]:
    if old.resolve().parent==directory.resolve():old.unlink()
print('Database backup complete.')
