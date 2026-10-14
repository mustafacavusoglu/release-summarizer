"""Sürüm tag'lerini tanıma, sıralama ve izlenecekleri seçme."""
import re

# stable (v1.2.3) ve rc (v1.2.3-rc.1, v1.2.3rc1); dev/ea/nightly/model-catalog gibi tag'ler elenir
TAG = re.compile(r"^v?(\d+(?:\.\d+)+)(?:-?rc\.?(\d+))?$", re.I)


def vkey(tag):
    """Sürüm sıralama anahtarı: 1.106.0-rc.2 < 1.106.0 < 1.106.1"""
    m = TAG.match(tag)
    return tuple(map(int, m[1].split("."))), m[2] is None, int(m[2] or 0)


def is_rc(tag):
    return TAG.match(tag)[2] is not None


def split(tags):
    """Tag'leri yeniden eskiye sıralar: (stable'lar, n'den yeni rc'ler)."""
    tags = sorted((t for t in tags if TAG.match(t)), key=vkey, reverse=True)
    stable = [t for t in tags if not is_rc(t)]
    n = vkey(stable[0]) if stable else ((0,), True, 0)
    return stable, [t for t in tags if is_rc(t) and vkey(t) > n]


def pick(rels, keep):
    """n..n-(keep-1) stable + n'den yeni rc'ler."""
    stable, rcs = split(r["tag"] for r in rels)
    wanted = set(stable[:keep] + rcs)
    return [r for r in rels if r["tag"] in wanted]
