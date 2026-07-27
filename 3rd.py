import sys

md = 998244353

def ck(nn, ar):
    vv = nn - 1
    mx = max(ar)

    if mx != vv:
        return 0

    lf = ar.index(mx)
    rg = vv - 1 - ar[::-1].index(mx)

    for ii in range(1, rg + 1):
        if ar[ii] < ar[ii - 1]:
            return 0

    for ii in range(lf + 1, vv):
        if ar[ii] > ar[ii - 1]:
            return 0

    lb = []
    ii = 0
    while ii < lf:
        jj = ii
        while jj < lf and ar[jj] == ar[ii]:
            jj += 1
        lb.append((ar[ii], jj - ii - 1))
        ii = jj

    rb = []
    ii = rg + 1
    while ii < vv:
        jj = ii
        while jj < vv and ar[jj] == ar[ii]:
            jj += 1
        rb.append((ar[ii], jj - ii - 1))
        ii = jj

    rb.reverse()

    fm = rg - lf

    ow = [0] * (mx + 1)

    for aa, bb in lb:
        ow[aa] = 1

    for aa, bb in rb:
        if ow[aa]:
            return 0
        ow[aa] = 2

    fc = [-1] * (vv + 1)

    for aa, bb in lb:
        fc[aa] = bb

    for aa, bb in rb:
        fc[aa] = bb

    fc[mx] = fm

    an = 1
    av = 0

    for xx in range(vv, 0, -1):
        if fc[xx] != -1:
            av += fc[xx]
        else:
            an = (an * av) % md
            av -= 1

    return (2 * an) % md


def sl():
    dt = sys.stdin.buffer.read().split()
    ps = 0
    tt = int(dt[ps])
    ps += 1
    ot = []

    for _ in range(tt):
        nn = int(dt[ps])
        ps += 1
        ar = list(map(int, dt[ps:ps + nn - 1]))
        ps += nn - 1
        ot.append(str(ck(nn, ar)))

    sys.stdout.write("\n".join(ot))


sl()