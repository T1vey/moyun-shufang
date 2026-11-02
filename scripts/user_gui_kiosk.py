"""Local WebKitGTK kiosk for the existing Xvfb/MD0700R display bridge.

Uses the distro Python with python3-gi and gir1.2-webkit2-4.0. All drawing
requests remain in the HTTP workflow; this process only displays its pages.
"""
import argparse
import json
import os
import signal
import threading
import time
from pathlib import Path
import urllib.parse
import urllib.request


def allowed_navigation(uri, port):
    try:
        parsed = urllib.parse.urlsplit(uri)
        return (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
                and parsed.port == port and not parsed.username and not parsed.password)
    except (ValueError, TypeError):
        return False

class ViewPoller:
    """Network IO never runs in GTK's event/paint loop; retain the last good mode."""
    def __init__(self,opener,url,interval=.35):
        self.opener=opener;self.url=url;self.interval=interval;self.mode=None
        self.stopping=threading.Event()
        self.worker=threading.Thread(target=self._run,name='kiosk-view-state',daemon=True)
    def start(self):self.worker.start()
    def close(self):self.stopping.set()
    def _run(self):
        while not self.stopping.is_set():
            try:
                with self.opener.open(self.url,timeout=1) as response:mode=json.load(response).get('view')
                if mode in ('settings','user'):self.mode=mode
            except (OSError,ValueError):pass
            if self.stopping.wait(self.interval):break


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error('Invalid user interface port')
    # There is no DRM/GPU display on this path; pixels are read from Xvfb.
    os.environ.setdefault('GDK_BACKEND', 'x11')
    os.environ.setdefault('WEBKIT_DISABLE_COMPOSITING_MODE', '1')
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.0')
    from gi.repository import GLib, Gtk, WebKit2

    window = Gtk.Window()
    window.set_title('SO-101 用户界面')
    window.set_decorated(False)
    window.set_default_size(1024, 600)
    window.set_size_request(1024, 600)
    window.move(0, 0)
    view = WebKit2.WebView()
    settings = view.get_settings()
    settings.set_enable_developer_extras(False)
    if hasattr(settings, 'set_hardware_acceleration_policy'):
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.NEVER)
    window.add(view)
    window.connect('delete-event', lambda *_: True)
    view.connect('context-menu', lambda *_: True)
    view.connect('permission-request', lambda _view, request: (request.deny(), True)[1])

    def decide(_view, decision, kind):
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                    WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION or not allowed_navigation(uri, args.port):
                decision.ignore()
                return True
        return False
    view.connect('decide-policy', decide)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = 'http://127.0.0.1:%d' % args.port
    visible = [True]
    view_state=ViewPoller(opener,base+'/api/view')
    view_state.start()

    def refresh_view():
        mode=view_state.mode
        if mode == 'settings' and visible[0]:
            # Keep painted pixels beneath Tk until its window is ready.
            # Tk maps above this window; do not hide or raise the WebView.
            visible[0] = False
        elif mode == 'user' and not visible[0]:
            window.show_all()
            window.move(0, 0)
            window.present()
            visible[0] = True
        return True

    def quit_main(*_):
        Gtk.main_quit()
        return False
    failed = [False]
    def renderer_failed(*_):
        failed[0] = True
        print('USER_GUI_WEB_PROCESS_EXITED', flush=True)
        Gtk.main_quit()
    view.connect('web-process-terminated', renderer_failed)
    # Low-rate local diagnostics distinguish a stalled renderer from lost touch
    # events. No URLs, form contents, tokens or robot commands are recorded.
    health = Path.home() / '.cache/tcb705/kiosk_health.json'
    health.parent.mkdir(parents=True,exist_ok=True)
    pending_health = [False]
    def probe_health():
        if pending_health[0]:
            return True
        pending_health[0] = True
        started = time.monotonic()
        code = '''(function(){
          if(!window.__panelHealth){
            window.__panelHealth={events:0,lastEvent:null};
            ['mousedown','mouseup','click'].forEach(function(type){
              document.addEventListener(type,function(e){
                var s=window.__panelHealth;s.events++;
                s.lastEvent={type:type,id:e.target.id||e.target.tagName,x:e.clientX,y:e.clientY};
              },true);
            });
          }
          var s=window.__panelHealth,m=document.getElementById('calligraphy-modal'),b=document.getElementById('brush-write');
          return JSON.stringify({events:s.events,lastEvent:s.lastEvent,brushOpen:!!m&&!m.hidden,
            writeEnabled:!!b&&!b.disabled,writeLabel:b?b.textContent:null,
            nodes:document.getElementsByTagName('*').length});
        })()'''
        def done(webview, result, unused):
            try:
                data=json.loads(webview.run_javascript_finish(result).get_js_value().to_string())
                data.update(timestamp=time.time(),roundtrip_s=round(time.monotonic()-started,3))
                health.with_suffix('.tmp').write_text(json.dumps(data))
                health.with_suffix('.tmp').replace(health)
            except Exception:
                pass
            finally:
                pending_health[0]=False
        view.run_javascript(code,None,done,None)
        return True
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, quit_main)
    view.load_uri(base + '/?kiosk=1')
    window.show_all()
    GLib.timeout_add(350, refresh_view)
    GLib.timeout_add_seconds(2, probe_health)
    try:Gtk.main()
    finally:view_state.close()
    return 1 if failed[0] else 0


if __name__ == '__main__':
    raise SystemExit(main())
