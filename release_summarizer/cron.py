"""Bağımlılıksız 5 alanlı cron: dakika saat gün ay haftanın-günü (*, */n, a-b, a,b)."""
from datetime import timedelta


def _field(spec, lo, hi):
    vals = set()
    for part in spec.split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = map(int, rng.split("-"))
        else:
            a = b = int(rng)
            if step:  # "5/15" = 5'ten başlayıp 15'er
                b = hi
        vals.update(range(a, b + 1, int(step or 1)))
    if not vals or min(vals) < lo or max(vals) > hi:
        raise ValueError(f"Geçersiz cron alanı: {spec!r}")
    return vals


def parse_cron(expr):
    f = expr.split()
    if len(f) != 5:
        raise ValueError(f"Cron 5 alanlı olmalı (dakika saat gün ay haftanın-günü): {expr!r}")
    minute, hour, dom, month, dow = (_field(s, lo, hi) for s, (lo, hi) in
                                     zip(f, [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]))
    return minute, hour, dom, month, {d % 7 for d in dow}, f[2] != "*" and f[4] != "*"


def next_run(cron, after):
    minute, hour, dom, month, dow, either_day = cron
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):  # ponytail: dakika dakika tarama, en kötü ~0.5 sn; yeter
        d, w = t.day in dom, t.isoweekday() % 7 in dow
        if t.minute in minute and t.hour in hour and t.month in month and ((d or w) if either_day else (d and w)):
            return t
        t += timedelta(minutes=1)
    raise ValueError("Cron bir yıl içinde hiç tetiklenmiyor")
