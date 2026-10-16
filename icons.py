"""Monochrome line icons for the interface.

Every icon is a 24×24 outline drawn with ``currentColor``, so it takes the
colour of the text around it — white in the menu, gold when active, grey when
muted.  No emoji, no colour of their own.  Templates call
``{{ icon("inventory") }}``; the function is registered as a Jinja global in
``app.py``.
"""
from markupsafe import Markup, escape

# name -> inner SVG markup (paths drawn on a 24×24 grid)
ICONS = {
    # --- navigation ---------------------------------------------------------
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                 '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "analytics": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
    "reports": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
               '<polyline points="14 3 14 8 19 8"/><line x1="9" y1="13" x2="15" y2="13"/>'
               '<line x1="9" y1="17" x2="13" y2="17"/>',
    "receiving": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
                 '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "honey": '<path d="M12 2.7c3.5 4 6 7.4 6 10.3a6 6 0 0 1-12 0c0-2.9 2.5-6.3 6-10.3z"/>'
             '<path d="M9.2 14.2a2.8 2.8 0 0 0 2.8 2.8"/>',
    "production": '<path d="M3 21V10l5 3.5V10l5 3.5V5h4l1.2 16"/><line x1="2" y1="21" x2="22" y2="21"/>'
                  '<line x1="7" y1="17.5" x2="8" y2="17.5"/><line x1="12" y1="17.5" x2="13" y2="17.5"/>',
    "recipes": '<rect x="8" y="2" width="8" height="4" rx="1"/>'
               '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
               '<line x1="9" y1="11" x2="15" y2="11"/><line x1="9" y1="15" x2="15" y2="15"/>',
    "inventory": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><polyline points="3 8 12 13 21 8"/>'
                 '<line x1="12" y1="13" x2="12" y2="21"/>',
    "qr": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
          '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
          '<rect x="7" y="7" width="4" height="4" rx=".5"/><rect x="13" y="13" width="4" height="4" rx=".5"/>'
          '<line x1="13" y1="7.5" x2="17" y2="7.5"/><line x1="7" y1="15" x2="10" y2="15"/>',
    "packing": '<path d="M6 7h12l-1 13H7z"/><path d="M9 7a3 3 0 0 1 6 0"/>',
    "platforms": '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/>'
                 '<path d="M2 3h3l2.7 12.4a2 2 0 0 0 2 1.6h7.6a2 2 0 0 0 2-1.6L21 7H6"/>',
    "orders": '<path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z"/>'
              '<line x1="9" y1="8" x2="15" y2="8"/><line x1="9" y1="12" x2="15" y2="12"/>',
    "release": '<polyline points="17 2 21 6 17 10"/><path d="M3 12v-2a4 4 0 0 1 4-4h14"/>'
               '<polyline points="7 22 3 18 7 14"/><path d="M21 12v2a4 4 0 0 1-4 4H3"/>',
    "deliveries": '<rect x="2" y="6" width="12" height="10" rx="1"/><path d="M14 9h4l3 3v4h-7"/>'
                  '<circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
    "customers": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
                 '<path d="M16 4.3a3.5 3.5 0 0 1 0 6.4"/><path d="M21.5 20a6.5 6.5 0 0 0-4-6"/>',
    "assets": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "suppliers": '<path d="M3 21h18"/><path d="M5 21V8l7-5 7 5v13"/><path d="M9 21v-6h6v6"/>',
    "requests": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "approvals": '<circle cx="12" cy="12" r="9"/><polyline points="8 12 11 15 16 9"/>',
    "notifications": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
                     '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "users": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>'
                '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/>'
              '<line x1="21" y1="12" x2="9" y2="12"/>',
    "assistant": '<path d="M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8z"/>'
                 '<path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    # --- interface ----------------------------------------------------------
    "search": '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "menu": '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/>'
            '<line x1="3" y1="18" x2="21" y2="18"/>',
    "arrow-up-right": '<line x1="7" y1="17" x2="17" y2="7"/><polyline points="8 7 17 7 17 16"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12.5"/>'
             '<line x1="12" y1="16" x2="12.01" y2="16"/>',
    "close": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "check": '<polyline points="5 12 10 17 19 8"/>',
    # --- flows & records ----------------------------------------------------
    "inspect": '<path d="M9 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5"/><path d="M15 3h3a2 2 0 0 1 2 2v5"/>'
               '<rect x="8" y="2" width="8" height="4" rx="1"/><circle cx="16.5" cy="16.5" r="3.5"/>'
               '<line x1="19" y1="19" x2="22" y2="22"/>',
    "retention": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9"/>'
                 '<line x1="10" y1="13" x2="14" y2="13"/>',
    "swap": '<polyline points="16 3 20 7 16 11"/><line x1="20" y1="7" x2="4" y2="7"/>'
            '<polyline points="8 21 4 17 8 13"/><line x1="4" y1="17" x2="20" y2="17"/>',
    "sparkle": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4"/><path d="M6.3 6.3l2.1 2.1M15.6 15.6l2.1 2.1'
               'M6.3 17.7l2.1-2.1M15.6 8.4l2.1-2.1"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><polyline points="9 12 11 14 15 10"/>',
    "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><polyline points="3 8 12 13 21 8"/>'
           '<line x1="12" y1="13" x2="12" y2="21"/><line x1="7.5" y1="5.5" x2="16.5" y2="10.5"/>',
    "scale": '<path d="M12 3v18"/><path d="M5 21h14"/><path d="M4 7h16"/><path d="M4 7l-3 7a3.5 3.5 0 0 0 6 0z"/>'
             '<path d="M20 7l-3 7a3.5 3.5 0 0 0 6 0z"/>',
    "truck": '<rect x="1" y="5" width="14" height="11" rx="1"/><path d="M15 9h4l3 3v4h-7"/>'
             '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
    "hand": '<path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v6"/>'
            '<path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2'
            'c-2.8 0-4.5-.9-5.9-2.4L3.3 16.8a2 2 0 0 1 2.8-2.8L8 16"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/>'
              '<line x1="12" y1="3" x2="12" y2="15"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/>'
                '<line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "clipboard": '<rect x="8" y="2" width="8" height="4" rx="1"/>'
                 '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>'
                 '<polyline points="9 14 11 16 15 12"/>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "arrow-right": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "printer": '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16'
               'a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>'
              '<circle cx="12" cy="13" r="4"/>',
    "in": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/>'
          '<line x1="12" y1="15" x2="12" y2="3"/>',
    "out": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/>'
           '<line x1="12" y1="3" x2="12" y2="15"/>',
    "x-circle": '<circle cx="12" cy="12" r="9"/><line x1="15" y1="9" x2="9" y2="15"/>'
                '<line x1="9" y1="9" x2="15" y2="15"/>',
    "pause": '<circle cx="12" cy="12" r="9"/><line x1="10" y1="9" x2="10" y2="15"/>'
             '<line x1="14" y1="9" x2="14" y2="15"/>',
    "tools": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "count": '<path d="M4 6h16M4 12h16M4 18h10"/><polyline points="16 16 18 18 22 14"/>',
    "chart": '<line x1="4" y1="20" x2="20" y2="20"/><rect x="6" y="11" width="3" height="7"/>'
             '<rect x="11" y="6" width="3" height="12"/><rect x="16" y="13" width="3" height="5"/>',
    "drop": '<path d="M12 2.7c3.5 4 6 7.4 6 10.3a6 6 0 0 1-12 0c0-2.9 2.5-6.3 6-10.3z"/>',
    "info": '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/>'
            '<line x1="12" y1="7.5" x2="12.01" y2="7.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z"/>',
    "monitor": '<rect x="2" y="4" width="20" height="13" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/>'
               '<line x1="12" y1="17" x2="12" y2="21"/>',
}


def icon(name, size=18, cls=""):
    """Render one icon as inline SVG (decorative: hidden from screen readers)."""
    body = ICONS.get(name)
    if body is None:
        return Markup("")
    return Markup(
        '<svg class="ico%s" width="%d" height="%d" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true" focusable="false">%s</svg>'
        % ((" " + escape(cls)) if cls else "", int(size), int(size), body))
