loadenv() { eval "$(python3 -I -c 'import shlex,sys
for l in open(sys.argv[1]).read().splitlines():
    s=l.strip()
    if s and not s.startswith("#") and "=" in s:
        k,v=s.split("=",1); v=v.strip()
        if len(v)>=2 and v[0]==v[-1] and v[0] in "\"'"'"'": v=v[1:-1]
        print("export %s=%s" % (k.strip(), shlex.quote(v)))' "$1")"; }
