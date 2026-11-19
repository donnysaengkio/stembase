"""Tab icons (Tabler Icons, MIT licence, https://tabler.io/icons), drawn with CSS masks so they follow the text colour."""
from urllib.parse import quote

PATHS = {
    "chart-bar": '<path d="M3 13a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v6a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1z" /><path d="M15 9a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v10a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1z" /><path d="M9 5a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v14a1 1 0 0 1 -1 1h-4a1 1 0 0 1 -1 -1z" /><path d="M4 20h14" />',
    "stack-3": '<path d="M12 2l-8 4l8 4l8 -4l-8 -4" /><path d="M4 10l8 4l8 -4" /><path d="M4 18l8 4l8 -4" /><path d="M4 14l8 4l8 -4" />',
    "arrows-split": '<path d="M21 17h-8l-3.5 -5h-6.5" /><path d="M21 7h-8l-3.495 5" /><path d="M18 10l3 -3l-3 -3" /><path d="M18 20l3 -3l-3 -3" />',
    "piano": '<path d="M3 5m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v10a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z" /><path d="M9 19v-6" /><path d="M8 5v8h2v-8" /><path d="M15 19v-6" /><path d="M14 5v8h2v-8" />',
    "adjustments-horizontal": '<path d="M14 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M4 6l8 0" /><path d="M16 6l4 0" /><path d="M8 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M4 12l2 0" /><path d="M10 12l10 0" /><path d="M17 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M4 18l11 0" /><path d="M19 18l1 0" />',
    "plus-minus": '<path d="M4 7h6" /><path d="M7 4v6" /><path d="M20 18h-6" /><path d="M5 19l14 -14" />',
    "arrows-up-down": '<path d="M7 3l0 18" /><path d="M10 6l-3 -3l-3 3" /><path d="M20 18l-3 3l-3 -3" /><path d="M17 21l0 -18" />',
    "file-export": '<path d="M14 3v4a1 1 0 0 0 1 1h4" /><path d="M11.5 21h-4.5a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v5m-5 6h7m-3 -3l3 3l-3 3" />',
    "file-music": '<path d="M14 3v4a1 1 0 0 0 1 1h4" /><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z" /><path d="M11 16m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0" /><path d="M12 16l0 -5l2 1" />',
}


def svg_url(name):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round">' + PATHS[name] + '</svg>')
    return 'url("data:image/svg+xml,' + quote(svg) + '")'


def tab_css(icons):
    """Full-width tab bar, equal tabs, an icon above each name (icons: one Tabler name per tab, in order)."""
    css = ('[role=tablist],[role=tablist]>button[role=tab]{height:auto!important;overflow:visible!important}'
           '[role=tablist]{display:flex!important;width:100%;gap:0}'
           '[role=tablist]>button[role=tab]{flex:1 1 0;display:flex;flex-direction:column;align-items:center;gap:4px;'
           'padding:10px 4px 8px;font-size:var(--text-md)}'
           '[role=tablist]>button[role=tab]::before{content:"";flex:0 0 22px;width:22px;height:22px;background-color:currentColor;'
           '-webkit-mask:var(--icon) center/contain no-repeat;mask:var(--icon) center/contain no-repeat}')
    for i, name in enumerate(icons, 1):
        css += f'[role=tablist]>button[role=tab]:nth-of-type({i}){{--icon:{svg_url(name)}}}'
    return css
