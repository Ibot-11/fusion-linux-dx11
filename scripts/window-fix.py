#!/usr/bin/env python3
from Xlib import X, display


def is_problematic(win, connection):
    try:
        attrs = win.get_attributes()
        if not attrs.override_redirect:
            return False

        name = win.get_wm_name()
        if name != "Fusion360":
            return False

        type_atom = connection.intern_atom('_NET_WM_WINDOW_TYPE')
        dialog_atom = connection.intern_atom('_NET_WM_WINDOW_TYPE_DIALOG')

        wtype = win.get_full_property(type_atom, X.AnyPropertyType)
        if wtype is None or dialog_atom not in wtype.value:
            return False

        hints = win.get_wm_hints()
        if hints is None or not hasattr(hints, 'input'):
            return False
        if hints.input:
            return False

        transient = win.get_wm_transient_for()
        if transient is None:
            return False

        try:
            parent_win = transient
            # Real dropdowns are transient for a tool panel. Comparing their
            # area with that small panel can mistake them for a large phantom
            # dialog. Only a direct transient of the managed main window is
            # eligible for this workaround.
            if parent_win.get_attributes().override_redirect or parent_win.get_wm_transient_for() is not None:
                return False
            normal_atom = connection.intern_atom('_NET_WM_WINDOW_TYPE_NORMAL')
            parent_type = parent_win.get_full_property(type_atom, X.AnyPropertyType)
            if parent_type is None or normal_atom not in parent_type.value:
                return False
            parent_geom = parent_win.get_geometry()
            popup_geom = win.get_geometry()

            parent_area = parent_geom.width * parent_geom.height
            popup_area = popup_geom.width * popup_geom.height

            if parent_area == 0:
                return False

            coverage = popup_area / parent_area

            print(f"[Fusion Linux][debug] win={win.id:#x} "
                  f"popup={popup_geom.width}x{popup_geom.height} "
                  f"parent={parent_geom.width}x{parent_geom.height} "
                  f"coverage={coverage:.2f}")

            if coverage < 0.8:
                return False
        except Exception as e:
            print(f"[Fusion Linux][debug] geometry check failed for {win.id:#x}: {e}")
            return False

        if attrs.map_state != X.IsViewable:
            return False

        return True
    except Exception:
        return False


def main():
    connection = display.Display()
    root = connection.screen().root
    root.change_attributes(event_mask=X.SubstructureNotifyMask)
    print("[Fusion Linux] Event-driven watcher started", flush=True)
    try:
        while True:
            ev = connection.next_event()
            if ev.type == X.MapNotify and is_problematic(ev.window, connection):
                print(f"[Fusion Linux] Problematic dialog detected (event-driven): {ev.window.id:#x}", flush=True)
                ev.window.unmap()
                connection.sync()
    finally:
        connection.close()


if __name__ == '__main__':
    main()
