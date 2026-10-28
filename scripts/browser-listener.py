#!/usr/bin/env python3
import datetime, fcntl, os, pathlib, shutil, signal, subprocess, time, urllib.parse
runtime = pathlib.Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
queue = runtime / 'autodesk-fusion-browser'
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
                try:
                    with logfile.open('a') as log:
                        stamp = datetime.datetime.now().isoformat(timespec='seconds')
                        host = urllib.parse.urlsplit(url).hostname
                        log.write(f'{stamp} Browser request for {host}\n')
                        log.flush()
                        opener = shutil.which('xdg-open')
                        if opener is None:
                            raise FileNotFoundError('xdg-open is not available on PATH')
                        subprocess.Popen([opener, url], env=browser_env,
                                         stdout=subprocess.DEVNULL, stderr=log,
                                         start_new_session=True)
                except OSError as error:
                    with logfile.open('a') as log:
                        log.write(f'Browser handoff failed: {type(error).__name__}\n')
                finally:
                    # A failed handoff must not be retried forever.
                    request.unlink(missing_ok=True)
            else:
                request.rename(request.with_suffix('.unsupported'))
        except OSError as error:
            with logfile.open('a') as log:
                log.write(f'Browser request failed: {type(error).__name__}\n')
    time.sleep(0.25)
