"""تفقيط المبالغ بالعربية — «أربعة وأربعون مليوناً وسبعمائة وخمسة وثلاثون ألف ريال سعودي فقط».

يتبع الصيغة المتداولة في العقود والفواتير السعودية: الأعداد بالمذكر، ومن ثلاثة
إلى عشرة يُجمع المعدود (آلاف/ملايين)، ومن أحد عشر إلى تسعة وتسعين يُفرد منصوباً
(ألفاً/مليوناً)، ومن مئة فما فوق يُفرد (ألف/مليون).
"""

_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة",
         "عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر",
         "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة",
             "ثمانمائة", "تسعمائة"]

# (مفرد، مثنى، جمع 3-10، مفرد منصوب 11-99)
_SCALES = [
    ("ألف", "ألفان", "آلاف", "ألفاً"),
    ("مليون", "مليونان", "ملايين", "مليوناً"),
    ("مليار", "ملياران", "مليارات", "ملياراً"),
]


def _below_thousand(n: int) -> str:
    parts = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if rest:
        if rest < 20:
            parts.append(_ONES[rest])
        else:
            t, o = divmod(rest, 10)
            parts.append(f"{_ONES[o]} و{_TENS[t]}" if o else _TENS[t])
    return " و".join(parts)


def _scaled(n: int, scale: tuple, last: bool = False) -> str:
    """last: آخر مكوّن قبل اسم العملة يُضاف إليها فلا يُنصب («ألف ريال» لا «ألفاً ريال»)."""
    one, two, plural, accusative = scale
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n <= 10:
        return f"{_below_thousand(n)} {plural}"
    rest = n % 100
    word = accusative if 11 <= rest <= 99 and not last else one
    return f"{_below_thousand(n)} {word}"


def int_to_words(n: int) -> str:
    if n == 0:
        return "صفر"
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    parts = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        last = not any(groups[:i])
        parts.append(_below_thousand(g) if i == 0 else _scaled(g, _SCALES[i - 1], last))
    return " و".join(parts)


def amount_in_words(amount: float, currency: str = "ريال سعودي", sub: str = "هللة") -> str:
    """المبلغ كتابةً بصيغة العقود: «... ريال سعودي فقط» مع الهللات إن وُجدت."""
    amount = round(float(amount or 0), 2)
    riyals = int(amount)
    halalas = int(round((amount - riyals) * 100))
    text = f"{int_to_words(riyals)} {currency}"
    if halalas:
        text += f" و{int_to_words(halalas)} {sub}"
    return text + " فقط"
