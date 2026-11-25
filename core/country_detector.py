import re

COUNTRY_PATTERNS = [
    (r"\b(de|germany|deutschland|frankfurt|berlin|munich)\b", "DE", "🇩🇪", "Германия"),
    (r"\b(nl|netherlands|holland|amsterdam|rotterdam)\b", "NL", "🇳🇱", "Нидерланды"),
    (r"\b(us|usa|united\s*states|america|new\s*york|los\s*angeles|miami|chicago|seattle|dallas|california|virginia)\b", "US", "🇺🇸", "США"),
    (r"\b(fi|finland|helsinki)\b", "FI", "🇫🇮", "Финляндия"),
    (r"\b(se|sweden|stockholm)\b", "SE", "🇸🇪", "Швеция"),
    (r"\b(tr|turkey|türkiye|istanbul|ankara|izmir)\b", "TR", "🇹🇷", "Турция"),
    (r"\b(uk|gb|united\s*kingdom|great\s*britain|england|london|manchester)\b", "GB", "🇬🇧", "Великобритания"),
    (r"\b(pl|poland|warsaw|krakow)\b", "PL", "🇵🇱", "Польша"),
    (r"\b(fr|france|paris|marseille)\b", "FR", "🇫🇷", "Франция"),
    (r"\b(kz|kazakhstan|almaty|astana)\b", "KZ", "🇰🇿", "Казахстан"),
    (r"\b(ru|russia|moscow|spb|petersburg|saint\s*petersburg)\b", "RU", "🇷🇺", "Россия"),
    (r"\b(sg|singapore)\b", "SG", "🇸🇬", "Сингапур"),
    (r"\b(jp|japan|tokyo|osaka)\b", "JP", "🇯🇵", "Япония"),
    (r"\b(hk|hong\s*kong)\b", "HK", "🇭🇰", "Гонконг"),
    (r"\b(ca|canada|toronto|montreal|vancouver)\b", "CA", "🇨🇦", "Канада"),
    (r"\b(at|austria|vienna)\b", "AT", "🇦🇹", "Австрия"),
    (r"\b(ch|switzerland|zurich|geneva)\b", "CH", "🇨🇭", "Швейцария"),
    (r"\b(es|spain|madrid|barcelona)\b", "ES", "🇪🇸", "Испания"),
    (r"\b(it|italy|milan|rome)\b", "IT", "🇮🇹", "Италия"),
    (r"\b(cz|czech|prague)\b", "CZ", "🇨🇿", "Чехия"),
    (r"\b(ae|uae|dubai)\b", "AE", "🇦🇪", "ОАЭ"),
    (r"\b(ge|georgia|tbilisi)\b", "GE", "🇬🇪", "Грузия"),
    (r"\b(am|armenia|yerevan)\b", "AM", "🇦🇲", "Армения"),
    (r"\b(ee|estonia|tallinn)\b", "EE", "🇪🇪", "Эстония"),
    (r"\b(lv|latvia|riga)\b", "LV", "🇱🇻", "Латвия"),
    (r"\b(lt|lithuania|vilnius)\b", "LT", "🇱🇹", "Литва"),
    (r"\b(by|belarus|minsk|беларусь|белоруссия|минск)\b", "BY", "🇧🇾", "Беларусь"),
    (r"\b(ua|ukraine|kyiv|kiev|украина|киев)\b", "UA", "🇺🇦", "Украина"),
    (r"\b(md|moldova|chisinau|молдова|кишинев)\b", "MD", "🇲🇩", "Молдова"),
    (r"\b(uz|uzbekistan|tashkent|узбекистан|ташкент)\b", "UZ", "🇺🇿", "Узбекистан"),
    (r"\b(kg|kyrgyzstan|bishkek|кыргызстан|бишкек)\b", "KG", "🇰🇬", "Кыргызстан"),
    (r"\b(az|azerbaijan|baku|азербайджан|баку)\b", "AZ", "🇦🇿", "Азербайджан"),
    (r"\b(kr|korea|south\s*korea|seoul|корея|сеул)\b", "KR", "🇰🇷", "Южная Корея"),
    (r"\b(in|india|mumbai|delhi|индия)\b", "IN", "🇮🇳", "Индия"),
    (r"\b(br|brazil|brasil|sao\s*paulo|бразилия)\b", "BR", "🇧🇷", "Бразилия"),
    (r"\b(au|australia|sydney|melbourne|австралия)\b", "AU", "🇦🇺", "Австралия"),
]

# Unicode flag extraction regex
EMOJI_FLAG_REGEX = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")

def detect_country(name: str, host: str = "") -> dict:
    """Detect country from node remark and host."""
    text = f"{name} {host}".lower()

    # Check for existing emoji flag in name
    flags_in_name = EMOJI_FLAG_REGEX.findall(name)
    if flags_in_name:
        flag = flags_in_name[0]
        # Calculate ISO from regional indicator symbols
        iso = "".join(chr(ord(c) - 0x1F1E6 + ord('A')) for c in flag)
        for _, code, f, ru_name in COUNTRY_PATTERNS:
            if code == iso:
                return {"code": code, "flag": flag, "name": ru_name}
        return {"code": iso, "flag": flag, "name": iso}

    # Match by regex patterns
    for pattern, code, flag, ru_name in COUNTRY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"code": code, "flag": flag, "name": ru_name}

    # Fallback to international / unknown
    return {"code": "UN", "flag": "🌐", "name": "Локация не определена"}
