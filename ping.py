"""Checks public navigation-warning lists for new items and, if any look relevant,
starts a workflow in another (private) repository via the GitHub API.

Sources (public pages, light requests only):
  - China MSA navigational warning lists, first page of each coastal bureau (www.msa.gov.cn)
  - Japan Coast Guard NAVAREA XI in-force list (www1.kaiho.mlit.go.jp)
  - NGA HYDROPAC in-force text (msi.nga.mil)

State: seen.json (IDs already seen). Nothing else is stored here.
Secrets: DISPATCH_TOKEN (fine-grained token, Actions: read & write on the target repo), TARGET_REPO (owner/name).
"""
import hashlib, json, os, re, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, 'seen.json')
UA = 'Mozilla/5.0 (research archive; personal use)'

# China MSA navigational warning lists (one per bureau)
MSA = ['94df14ce1110415da44e67593e76619f', 'bdba5fad6e5d48679f970fcf8efb8636', 'c8896863b1014c438705536a03eb46ff',
       '93b73989d22045f9bc3270a6eba35180', '36ea3354c8f84953aba082d6d989c750', '8e10ea74eb9e4c9690f8f891968add80',
       '7b08405760384570a0fb44e9204c4b1d', '1e478d409e854918bf12478b8a19f4a8', '86de2fffff2c47f98359fd1f20d6508f',
       'd3340711057b494b8fa09eedc4c5ead9', '9340423406cc4507b2fb8af2492d2a3d', 'b5b0f3c7630d4967b1e6b06208575d15',
       '325fdc0892b44313a63ee5c165be98ec', 'fa4501f3dbe44f70bc726f27132d4e04', 'd14ed012960b4064971270459a4a0d4d']
ITEM = re.compile(r'<a href="(/html/cnmsa/hxaq/article/[^"]+)"[^>]*>\s*<span class="name">\s*(.*?)\s*</span>', re.S)
# military / exercise / firing / rocket debris / missile (Chinese and English titles)
WORDS = re.compile('军事|实弹|射击|演习|演训|火箭|导弹|残骸|落区|武器|靶|MILITARY|FIRING|ROCKET|MISSILE|EXERCISE|DEBRIS|WEAPON', re.I)
INTL = re.compile(r'SPACE DEBRIS|ROCKET|MISSILE|GUNNERY|MILITARY|FIRING|EXERCISE', re.I)


def get(url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None,
                                 headers={'User-Agent': UA})
    return urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')


def msa_one(cid):
    try:
        s = get(f'https://www.msa.gov.cn/{cid}/index.jhtml')
    except Exception as e:
        print('msa', cid[:6], 'error', type(e).__name__, file=sys.stderr)
        return []
    return [('msa:' + hashlib.sha1(h.encode()).hexdigest()[:12], bool(WORDS.search(t))) for h, t in ITEM.findall(s)]


def jcg():
    out = []
    try:
        for y in ('2025', '2026', '2027'):
            x = get('https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi//warnings.cgi', {'YEAR': y, 'TYPE': 'NAVAREA11', 'LANG': 'JP'})
            for m in re.findall(r'<Member>(.*?)</Member>', x, re.S):
                tana = re.search(r'<tana>(.*?)</tana>', m).group(1).strip()
                cat = (re.search(r'<categoly>(.*?)</categoly>', m) or [0, ''])[1]
                title = (re.search(r'<title>(.*?)</title>', m) or [0, ''])[1]
                out.append(('jcg:' + tana, bool(re.search('訓練|射撃|宇宙|ロケット|ミサイル|落下物|演習', cat + title))))
    except Exception as e:
        print('jcg error', type(e).__name__, file=sys.stderr)
    return out


def nga():
    out = []
    try:
        s = get('https://msi.nga.mil/apology_objects/DailyMemPAC.txt')
        for m in re.split(r'\n(?=\d{6}Z [A-Z]{3} \d\d\n)', s):
            h = re.match(r'\d{6}Z [A-Z]{3} \d\d\nHYDROPAC (\d+/\d\d)', m.strip())
            if h:
                out.append(('nga:' + h.group(1), bool(INTL.search(m))))
    except Exception as e:
        print('nga error', type(e).__name__, file=sys.stderr)
    return out


def dispatch(n):
    tok, repo = os.environ.get('DISPATCH_TOKEN'), os.environ.get('TARGET_REPO')
    if not (tok and repo):
        print('no DISPATCH_TOKEN/TARGET_REPO; not dispatching', file=sys.stderr)
        return False
    req = urllib.request.Request(f'https://api.github.com/repos/{repo}/actions/workflows/watch.yml/dispatches',
                                 data=json.dumps({'ref': 'main', 'inputs': {'send': 'true'}}).encode(),
                                 headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json',
                                          'User-Agent': UA}, method='POST')
    return urllib.request.urlopen(req, timeout=30).status == 204


def main():
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    first = not seen
    with ThreadPoolExecutor(max_workers=5) as ex:
        items = [x for r in ex.map(msa_one, MSA) for x in r]
    items += jcg() + nga()
    new = [(k, hit) for k, hit in dict(items).items() if k not in seen]
    hits = [k for k, hit in new if hit]
    print(f'checked {len(items)}, new {len(new)}, relevant {len(hits)}')
    if hits and not first:
        if not dispatch(len(hits)):
            return 1   # keep seen.json unchanged so the next run retries
    if new:
        seen |= {k for k, _ in new}
        json.dump(sorted(seen), open(SEEN, 'w'), indent=0)
    return 0


if __name__ == '__main__':
    sys.exit(main())
