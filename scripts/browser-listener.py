#!/usr/bin/env python3
import datetime, fcntl, os, pathlib, signal, subprocess, time, urllib.parse
queue = pathlib.Path('/run/user') / str(os.getuid()) / 'autodesk-fusion-browser'
queue.mkdir(mode=0o700, exist_ok=True)
lock = (queue/'listener.lock').open('w')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit(0)
running = True
def stop(*args):
    global running
    running = False
signal.signal(signal.SIGTERM, stop)
browser_env = os.environ.copy()
browser_env.pop('GDK_BACKEND', None)
app = pathlib.Path(os.environ.get('FUSION_APP_DIR', str(pathlib.Path(__file__).resolve().parent)))
logfile = app/'logs/browser.log'
while running:
    for request in queue.glob('*.request'):
        try:
            url = request.read_text()
            if urllib.parse.urlsplit(url).scheme in ('https', 'http'):
                with logfile.open('a') as log:
                    stamp = datetime.datetime.now().isoformat(timespec='seconds')
                    host = urllib.parse.urlsplit(url).hostname
                    log.write(f'{stamp} Browser-Anfrage für {host}\n')
                    log.flush()
                    subprocess.Popen(['/usr/bin/firefox', '--new-window', url],
                                     env=browser_env, stdout=subprocess.DEVNULL,
                                     stderr=log, start_new_session=True)
                request.unlink()
            else:
                request.rename(request.with_suffix('.unsupported'))
        except OSError as error:
            with logfile.open('a') as log:
                log.write(f'Browser-Übergabe fehlgeschlagen: {type(error).__name__}\n')
    time.sleep(0.25)
