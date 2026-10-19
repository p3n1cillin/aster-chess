# Concurrent A/B speed: every round runs all binaries at once, one per core, rotating cores.
import subprocess, sys, statistics, re
n = int(sys.argv[1]); args = sys.argv[2].split(); bins = sys.argv[3:]
cores = [0,1,2,3][:len(bins)]
ratios = {b: [] for b in bins}; raw = {b: [] for b in bins}
for r in range(n):
    procs = []
    for i, b in enumerate(bins):
        c = cores[(i + r) % len(cores)]
        procs.append(subprocess.Popen(['taskset','-c',str(c),b,'bench',*args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True))
    nps = {}
    nodes = {}
    for b, p in zip(bins, procs):
        out = p.communicate()[1]
        nodes[b] = int(re.search(r'Nodes searched\s*:\s*(\d+)', out).group(1))
        nps[b] = int(re.search(r'Nodes/second\s*:\s*(\d+)', out).group(1))
    assert len(set(nodes.values())) == 1, nodes
    for b in bins:
        ratios[b].append(nps[b] / nps[bins[0]]); raw[b].append(nps[b])
print("nodes", nodes[bins[0]])
for b in bins:
    q = statistics.quantiles(ratios[b], n=4) if n > 2 else [0,0,0]
    print(f"{b:45s} median nps {statistics.median(raw[b]):9.0f}  ratio median {statistics.median(ratios[b]):.4f}  IQR {q[0]:.4f}-{q[2]:.4f}")
