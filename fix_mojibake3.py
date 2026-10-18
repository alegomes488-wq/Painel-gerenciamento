# -*- coding: utf-8 -*-
f = 'www/admin/js/modules/watch.js'
c = open(f, encoding='utf-8').read()

fix = [
    ('\u00e2\u0153\u2026', '\u2705'),      # âœ… -> ✅
    ('\u00f0\u009f\u00a4\u2013', '\U0001f916'),  # ðŸ¤– -> 🤖
    ('\u00e2\u00ac\u2027\ufeff', '\u2b07\ufe0f'),  # â¬‡ï¸. -> ⬇️
]

tot = 0
for bad, good in fix:
    n = c.count(bad)
    if n:
        c = c.replace(bad, good)
        tot += n
        print(f'  replace {bad!r} x{n}')

open(f, 'w', encoding='utf-8').write(c)
print('Total substituicoes:', tot)