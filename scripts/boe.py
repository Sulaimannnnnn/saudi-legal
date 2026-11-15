#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""boe.py — نصوص الأنظمة السعودية من مصدرها الرسمي (هيئة الخبراء بمجلس الوزراء laws.boe.gov.sa).

الأوامر:
  find  <كلمات>                 ابحث في الفهرس المرفق عن نظام باسمه (لا يحتاج شبكة)
  info  <نظام>                  بيانات النظام من الموقع: الحالة، أدوات الإصدار، التواريخ، عدد المواد
  toc   <نظام>                  هيكل النظام: الأبواب والفصول ونطاق موادها
  article <نظام> <أرقام>        نص المادة حرفياً مع حالتها وكل تعديلاتها. أمثلة: 77   74-77   5 9 12
  search <نظام> <كلمات>         المواد التي وردت فيها كل الكلمات (أضف --full للنص الكامل)

<نظام> = اسم النظام (أو جزء مميز منه) أو معرّفه (GUID) من الفهرس.
لا يعتمد إلا على مكتبة بايثون القياسية. عند تعذر الاتصال يخرج برسالة واضحة ورمز 3.
آداب الاستعمال: اجلب النظام الذي تحتاجه فقط؛ الصفحات تُخزَّن أسبوعاً. لا تجلب أنظمة كثيرة دفعة واحدة
ولا بالتوازي — الموقع يحجب الطلبات الآلية المتتابعة (403).
"""
import html
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = "https://laws.boe.gov.sa/BoeLaws/Laws/LawDetails/{}/1"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "..", "references", "fihris-al-anzimah.tsv")
CACHE = os.path.join(tempfile.gettempdir(), "saudi-legal-boe")
GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# ---------------------------------------------------------------- تطبيع النص
_TASHKEEL = re.compile(r"[ً-ْٰـ]")


def norm(s):
    s = _TASHKEEL.sub("", s)
    s = re.sub("[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip().lower()


# ------------------------------------------------- رقم المادة من لفظها الترتيبي
_UNITS = {"اولي": 1, "اول": 1, "حاديه": 1, "حادي": 1, "ثانيه": 2, "ثاني": 2, "ثالثه": 3, "ثالث": 3,
          "رابعه": 4, "رابع": 4, "خامسه": 5, "خامس": 5, "سادسه": 6, "سادس": 6, "سابعه": 7, "سابع": 7,
          "ثامنه": 8, "ثامن": 8, "تاسعه": 9, "تاسع": 9, "عاشره": 10, "عاشر": 10, "عشره": 10, "عشر": 10}
_TENS = {"عشرون": 20, "عشرين": 20, "ثلاثون": 30, "ثلاثين": 30, "اربعون": 40, "اربعين": 40,
         "خمسون": 50, "خمسين": 50, "ستون": 60, "ستين": 60, "سبعون": 70, "سبعين": 70,
         "ثمانون": 80, "ثمانين": 80, "تسعون": 90, "تسعين": 90}
_HUND = {"مايه": 100, "ميه": 100, "مايتان": 200, "مايتين": 200, "ميتان": 200, "ميتين": 200,
         "ثلاثمايه": 300, "ثلاثميه": 300, "اربعمايه": 400, "اربعميه": 400, "خمسمايه": 500,
         "خمسميه": 500, "ستمايه": 600, "ستميه": 600, "سبعمايه": 700, "سبعميه": 700,
         "ثمانمايه": 800, "ثمانميه": 800, "ثمانيمايه": 800, "تسعمايه": 900, "تسعميه": 900}
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def article_number(heading):
    """يحوّل «المادة الثالثة والخمسون بعد المائة» إلى 153. يرجع None إن تعذر."""
    h = norm(heading).translate(_DIG)
    if "الماده" in h and "حالي" not in h:
        h = h[h.rfind("الماده"):]
    m = re.search(r"\d+", h)
    if m:
        return int(m.group())
    total, hit = 0, False
    for w in re.split(r"[\s\-–:()]+", h):
        w = w.lstrip("و") if w not in ("واحد",) else w
        if w.startswith("ال"):
            w = w[2:]
        for table in (_UNITS, _TENS, _HUND):
            if w in table:
                total += table[w]
                hit = True
                break
    return total if hit else None


# --------------------------------------------------------------------- الفهرس
def load_index():
    rows = []
    try:
        with open(INDEX, encoding="utf-8") as f:
            head = f.readline().rstrip("\n").split("\t")
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) == len(head):
                    rows.append(dict(zip(head, p)))
    except OSError:
        pass
    return rows


def find(words, rows=None):
    rows = rows if rows is not None else load_index()
    ws = [norm(w) for w in words]
    return [r for r in rows if all(w in norm(r["الاسم"]) for w in ws)]


def resolve(arg):
    if GUID_RE.match(arg):
        return arg, None
    rows = load_index()
    exact = [r for r in rows if norm(r["الاسم"]) == norm(arg)]
    hits = exact or find(arg.split(), rows)
    live = [r for r in hits if r["الحالة"] == "ساري"]
    if len(hits) > 1 and len(live) == 1:
        hits = live
    if len(hits) == 1:
        return hits[0]["المعرف"], hits[0]
    if not hits:
        sys.exit("لم أجد نظاماً بهذا الاسم في الفهرس. جرّب: boe.py find <كلمة من الاسم>")
    print("أكثر من نظام يطابق — حدّد بالاسم الكامل أو بالمعرّف:")
    for r in hits[:25]:
        print("  {الاسم} | {الحالة} | {الأداة} | {المعرف}".format(**r))
    sys.exit(2)


# ---------------------------------------------------------------------- الجلب
def fetch(guid):
    """يجلب صفحة النظام مع تخزين مؤقت أسبوعاً. طلب واحد في كل مرة، وبلا إلحاح على الموقع."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, guid + ".html")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 7 * 86400:
        return open(path, encoding="utf-8", errors="ignore").read()
    url, page = BASE.format(guid), ""
    for attempt in range(2):  # محاولة ثانية واحدة عند انقطاع عابر فقط
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
        except Exception:
            try:
                page = subprocess.run(["curl", "-s", "-m", "60", "-L", "-A", UA, url],
                                      capture_output=True).stdout.decode("utf-8", "ignore")
            except Exception:
                page = ""
        if page.strip():
            break
        time.sleep(3)
    ok = "article_item" in page or "تاريخ الإصدار" in page
    if not ok:
        if "403" in page[:400] or "restricted by policy" in page:
            why = ("الموقع رفض الطلب الآلي (403). هذا حجب مقصود من الموقع: لا تُعد المحاولة ولا تلتفّ عليه؛ "
                   "افتح الرابط بالمتصفح أو انتظر.")
        elif "غير موجود" in page:
            why = "الصفحة غير موجودة في الموقع (قد يكون النظام قيد التحديث)."
        else:
            why = "لا اتصال بالموقع من هذه البيئة."
        sys.stderr.write("تعذّر فتح المصدر الرسمي: {}\n{}\nلا تنقل النص من الذاكرة؛ استعمل أداة تصفح أخرى "
                         "أو أنزل الاستشهاد إلى الدرجة (ب).\n".format(url, why))
        sys.exit(3)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    time.sleep(1)  # مهلة بين الطلبات الشبكية
    return page


# ------------------------------------------------------------- HTML إلى نص
def to_text(h):
    def number_list(m):
        items = re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.S)
        return "\n" + "\n".join("{}- {}".format(i, x) for i, x in enumerate(items, 1)) + "\n"
    for _ in range(4):  # القوائم المتداخلة من الداخل إلى الخارج
        h2 = re.sub(r"<ol[^>]*>((?:(?!<ol).)*?)</ol>", number_list, h, flags=re.S)
        if h2 == h:
            break
        h = h2
    h = re.sub(r"<li[^>]*>", "\n• ", h)
    h = re.sub(r"<(br|/p|/li|/tr|/h\d|/div)[^>]*>", "\n", h)
    h = re.sub(r"</t[dh]>", " | ", h)
    h = re.sub(r"<[^>]*$", "", re.sub(r"<[^>]+>", "", h))
    h = html.unescape(h).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in h.split("\n")]
    return "\n".join(l for l in lines if l)


def meta(page):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    L = [l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if l.strip()]

    def after(key, stop=None):
        if key not in L:
            return "" if stop is None else []
        i = L.index(key)
        if stop is None:
            return L[i + 1]
        out = []
        for l in L[i + 1:i + 14]:
            if l in stop:
                break
            out.append(l)
        return out
    return {"الاسم": after("الاسم"), "الإصدار": after("تاريخ الإصدار"), "النشر": after("تاريخ النشر"),
            "الحالة": after("الحالة"), "الأدوات": after("أدوات إصدار النظام", {"البحث في النظام"})}


def parse(page):
    """يرجع قائمة عناصر: ('sec', عنوان) أو ('art', dict). يتعامل مع تنسيقَي الموقع القديم والجديد."""
    out = []
    start = page.find('class="system_title"')
    body = page[start if start > 0 else 0:]
    for stop in ('id="divReportIssueContainer"', 'class="white_gradient"'):
        k = body.find(stop)
        if k > 0:
            body = body[:k]
    h3 = re.compile(r'<h3 class="center">(.*?)</h3>', re.S)
    divs = list(re.finditer(r'<div class="(article_item no_alternate[^"]*)">', body))
    first = divs[0].start() if divs else len(body)
    for m in h3.finditer(body[:first]):
        out.append(("sec", to_text(m.group(1)).replace("\n", " ")))
    for i, d in enumerate(divs):
        block = body[d.end():divs[i + 1].start() if i + 1 < len(divs) else len(body)]
        cls = d.group(1)
        heads = list(h3.finditer(block))
        marks = [x for x in (block.find("HTMLContainer"), block.find("article_btns")) if x >= 0]
        cstart = min(marks) if marks else len(block)
        before = [x for x in heads if x.start() < cstart]
        for x in before[:-1]:
            out.append(("sec", to_text(x.group(1)).replace("\n", " ")))
        head = to_text(before[-1].group(1)).replace("\n", " ") if before else ""
        hend = before[-1].end() if before else 0
        # منطقة التعديلات
        amends, ps, pe = [], -1, -1
        pl = block.find("popup-list")
        if pl >= 0:
            ps = block.rfind("<div", 0, pl)
            mainA = block.rfind('<p><div class="HTMLContainer">')
            if mainA > pl:
                pe = mainA
            else:
                after = [x.start() for x in heads if x.start() > pl]
                pe = after[0] if after else len(block)
            for a in block[ps:pe].split('<div class="article_item_popup">')[1:]:
                c = a.find('<div class="HTMLContainer">')
                a = a[c:] if c >= 0 else a
                amends.append(to_text(re.split(r'<a href="/BoeLaws/Laws/Viewer', a)[0]))
        trailing = [x for x in heads if x.start() >= cstart and not (ps <= x.start() < pe)]
        mend = trailing[0].start() if trailing else len(block)
        if ps >= 0:
            main = block[hend:min(ps, mend)] + (block[pe:mend] if pe < mend else "")
        else:
            main = block[hend:mend]
        main = re.sub(r'<a [^>]*ancArticlePrevVersions.*?</a>', "", main, flags=re.S)
        state = "ملغاة" if "canceled" in cls else ("معدّلة" if "changed" in cls else "أصلية لم تُعدَّل")
        num, old = article_number(head), None
        if "حالي" in head and "سابق" in head:
            parts = re.findall(r"\(([^()]*)\)", head)
            cur = [p for p in parts if "حالي" in p]
            prev = [p for p in parts if "سابق" in p]
            num = article_number(cur[0]) if cur else num
            old = article_number(prev[0]) if prev else None
        out.append(("art", {"عنوان": head, "رقم": num, "رقم_سابق": old, "مكرر": "مكرر" in head,
                            "حالة": state, "نص": to_text(main), "تعديلات": amends}))
        for x in trailing:
            out.append(("sec", to_text(x.group(1)).replace("\n", " ")))
    return out


def show_article(a, name):
    print("=" * 70)
    print("{} — {}".format(a["عنوان"], name))
    print("حالة المادة: " + a["حالة"])
    if a.get("رقم_سابق"):
        print("تنبيه ترقيم: هذه المادة أُعيد ترقيمها (رقمها السابق {}، الحالي {}). اذكر الرقمين عند الاستشهاد.".format(a["رقم_سابق"], a["رقم"]))
    if a["تعديلات"]:
        print("تنبيه: النص الأول أدناه هو الأصل كما يعرضه الموقع؛ والساري هو ما آلت إليه المادة بعد "
              "تطبيق التعديلات بترتيبها الزمني.")
    print("--- النص كما في الموقع:")
    print(a["نص"] or "(لا نص ظاهر)")
    for k, t in enumerate(a["تعديلات"], 1):
        print("--- تعديل/ملاحظة ({}):".format(k))
        print(t)


def wanted_numbers(args):
    nums = []
    for a in args:
        a = a.translate(_DIG)
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", a)
        if m:
            nums += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif a.isdigit():
            nums.append(int(a))
        else:
            n = article_number(a)
            if n:
                nums.append(n)
    return nums


def main(argv):
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "find":
        order = {"أنظمة أساسية": 0, "أنظمة عادية": 1, "لوائح وما في حكمها": 2}
        hits = sorted(find(rest), key=lambda r: (order.get(r["النوع"], 3), r["الحالة"] != "ساري", len(r["الاسم"])))
        for r in hits[:60]:
            print("{الاسم} | {النوع} | {الحالة} | {الأداة} | صدر {الإصدار_هجري} | {المعرف}".format(**r))
        print("({} نتيجة)".format(len(hits)))
        return 0
    guid, row = resolve(rest[0])
    page = fetch(guid)
    m = meta(page)
    name = m["الاسم"] or (row or {}).get("الاسم", guid)
    items = parse(page)
    arts = [x for k, x in items if k == "art"]
    if cmd == "info":
        print("الاسم: " + name)
        print("الحالة: " + m["الحالة"])
        print("أدوات الإصدار: " + " ؛ ".join(m["الأدوات"]))
        print("تاريخ الإصدار: " + m["الإصدار"])
        print("تاريخ النشر: " + m["النشر"])
        print("عدد المواد: {} (معدّلة {}، ملغاة {})".format(
            len(arts), sum(a["حالة"] == "معدّلة" for a in arts), sum(a["حالة"] == "ملغاة" for a in arts)))
        print("الرابط الرسمي: " + BASE.format(guid))
        pre = page[page.find("نـــص النظـــام"):page.find('class="system_title"')]
        if len(pre) > 200:
            print("--- ديباجة أداة الإصدار (فيها النفاذ والإلغاءات):")
            print(to_text(pre)[:3500])
        return 0
    if cmd == "toc":
        print(name + " — " + m["الحالة"])
        last = None
        for k, x in items:
            if k == "sec":
                if last:
                    print("    ↳ حتى " + last)
                    last = None
                print("■ " + x)
            else:
                if last is None:
                    print("    من " + x["عنوان"])
                last = x["عنوان"]
        if last:
            print("    ↳ حتى " + last)
        return 0
    if cmd == "article":
        nums = wanted_numbers(rest[1:])
        if not nums:
            sys.exit("اذكر رقم المادة: boe.py article <نظام> 77   أو   74-77")
        for n in nums:
            got = [a for a in arts if a["رقم"] == n or a.get("رقم_سابق") == n]
            if not got and 1 <= n <= len(arts) and all(a["رقم"] is None for a in arts):
                got = [arts[n - 1]]
            if not got:
                print("لا توجد مادة برقم {} في {} (عدد المواد {}).".format(n, name, len(arts)))
            for a in got:
                show_article(a, name)
        print("\nالمصدر: " + BASE.format(guid) + " — حالة النظام: " + m["الحالة"])
        return 0
    if cmd == "search":
        full = "--full" in rest
        ws = [norm(w) for w in rest[1:] if w != "--full"]
        hits = [a for a in arts if all(w in norm(a["نص"] + " " + " ".join(a["تعديلات"])) for w in ws)]
        for a in hits[:40]:
            if full:
                show_article(a, name)
            else:
                t = (a["نص"] + " ‖ " + " ‖ ".join(a["تعديلات"])).replace("\n", " ")
                p = norm(t).find(ws[0]) if ws else 0
                s = max(0, p - 90)
                print("{} [{}]: …{}…".format(a["عنوان"], a["حالة"], t[s:s + 260]))
        print("({} مادة) — {}".format(len(hits), name))
        return 0
    sys.exit("أمر غير معروف: " + cmd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
