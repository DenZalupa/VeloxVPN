// SVG Country Flags for Windows Compatibility
// Windows fonts don't render flag emojis by default. This provides crisp, high-resolution SVG flags.

const SVG_FLAGS = {
    "DE": `<svg viewBox="0 0 5 3" class="svg-flag"><rect width="5" height="1" fill="#000"/><rect y="1" width="5" height="1" fill="#D00"/><rect y="2" width="5" height="1" fill="#FFCE00"/></svg>`,
    "NL": `<svg viewBox="0 0 9 6" class="svg-flag"><rect width="9" height="2" fill="#AE1C28"/><rect y="2" width="9" height="2" fill="#FFF"/><rect y="4" width="9" height="2" fill="#21468B"/></svg>`,
    "RU": `<svg viewBox="0 0 9 6" class="svg-flag"><rect width="9" height="2" fill="#FFF"/><rect y="2" width="9" height="2" fill="#0039A6"/><rect y="4" width="9" height="2" fill="#D52B1E"/></svg>`,
    "US": `<svg viewBox="0 0 19 10" class="svg-flag"><rect width="19" height="10" fill="#B22234"/><line y1="1.54" x2="19" y2="1.54" stroke="#FFF" stroke-width="0.77"/><line y1="3.08" x2="19" y2="3.08" stroke="#FFF" stroke-width="0.77"/><line y1="4.62" x2="19" y2="4.62" stroke="#FFF" stroke-width="0.77"/><line y1="6.15" x2="19" y2="6.15" stroke="#FFF" stroke-width="0.77"/><line y1="7.69" x2="19" y2="7.69" stroke="#FFF" stroke-width="0.77"/><line y1="9.23" x2="19" y2="9.23" stroke="#FFF" stroke-width="0.77"/><rect width="7.6" height="5.38" fill="#3C3B6E"/></svg>`,
    "GB": `<svg viewBox="0 0 60 30" class="svg-flag"><clipPath id="uk_clip"><path d="M0,0 v30 h60 v-30 z"/></clipPath><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M0,0 L60,30 M60,0 L0,30" clip-path="url(#uk_clip)" stroke="#cf142b" stroke-width="4"/><path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10"/><path d="M30,0 v30 M0,15 h60" stroke="#cf142b" stroke-width="6"/></svg>`,
    "FR": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="1" height="2" fill="#002395"/><rect x="1" width="1" height="2" fill="#FFF"/><rect x="2" width="1" height="2" fill="#ED2939"/></svg>`,
    "FI": `<svg viewBox="0 0 18 11" class="svg-flag"><rect width="18" height="11" fill="#FFF"/><rect x="5" width="3" height="11" fill="#002F6C"/><rect y="4" width="18" height="3" fill="#002F6C"/></svg>`,
    "SE": `<svg viewBox="0 0 16 10" class="svg-flag"><rect width="16" height="10" fill="#006AA7"/><rect x="5" width="2" height="10" fill="#FECC00"/><rect y="4" width="16" height="2" fill="#FECC00"/></svg>`,
    "TR": `<svg viewBox="0 0 30 20" class="svg-flag"><rect width="30" height="20" fill="#E30A17"/><circle cx="11" cy="10" r="5" fill="#FFF"/><circle cx="12.5" cy="10" r="4" fill="#E30A17"/><polygon points="17,10 14.5,8.8 15.3,11.5 15.3,8.5 14.5,11.2" fill="#FFF"/></svg>`,
    "PL": `<svg viewBox="0 0 8 5" class="svg-flag"><rect width="8" height="2.5" fill="#FFF"/><rect y="2.5" width="8" height="2.5" fill="#DC143C"/></svg>`,
    "KZ": `<svg viewBox="0 0 2 1" class="svg-flag"><rect width="2" height="1" fill="#00AFCA"/><circle cx="1" cy="0.5" r="0.22" fill="#FEC50C"/></svg>`,
    "SG": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="1" fill="#ED2939"/><rect y="1" width="3" height="1" fill="#FFF"/><circle cx="0.7" cy="0.5" r="0.35" fill="#FFF"/><circle cx="0.8" cy="0.5" r="0.32" fill="#ED2939"/></svg>`,
    "JP": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="2" fill="#FFF"/><circle cx="1.5" cy="1" r="0.6" fill="#BC002D"/></svg>`,
    "HK": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="2" fill="#C8102E"/><circle cx="1.5" cy="1" r="0.45" fill="#FFF"/></svg>`,
    "CA": `<svg viewBox="0 0 4 2" class="svg-flag"><rect width="1" height="2" fill="#FF0000"/><rect x="1" width="2" height="2" fill="#FFF"/><rect x="3" width="1" height="2" fill="#FF0000"/><polygon points="2,0.4 2.2,0.8 2.6,0.7 2.3,1.1 2.5,1.5 2.1,1.3 2,1.7 1.9,1.3 1.5,1.5 1.7,1.1 1.4,0.7 1.8,0.8" fill="#FF0000"/></svg>`,
    "CH": `<svg viewBox="0 0 1 1" class="svg-flag"><rect width="1" height="1" fill="#D52B1E"/><rect x="0.37" y="0.17" width="0.26" height="0.66" fill="#FFF"/><rect x="0.17" y="0.37" width="0.66" height="0.26" fill="#FFF"/></svg>`,
    "AT": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="0.67" fill="#ED2939"/><rect y="0.67" width="3" height="0.66" fill="#FFF"/><rect y="1.33" width="3" height="0.67" fill="#ED2939"/></svg>`,
    "IT": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="1" height="2" fill="#009246"/><rect x="1" width="1" height="2" fill="#FFF"/><rect x="2" width="1" height="2" fill="#CE2B37"/></svg>`,
    "ES": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="0.5" fill="#AA151B"/><rect y="0.5" width="3" height="1" fill="#F1BF00"/><rect y="1.5" width="3" height="0.5" fill="#AA151B"/></svg>`,
    "CZ": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="1" fill="#FFF"/><rect y="1" width="3" height="1" fill="#D7141A"/><polygon points="0,0 1.5,1 0,2" fill="#11457E"/></svg>`,
    "AE": `<svg viewBox="0 0 4 2" class="svg-flag"><rect x="1" width="3" height="0.67" fill="#00732F"/><rect x="1" y="0.67" width="3" height="0.66" fill="#FFF"/><rect x="1" y="1.33" width="3" height="0.67" fill="#000"/><rect width="1" height="2" fill="#FF0000"/></svg>`,
    "UA": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="1" fill="#0057B7"/><rect y="1" width="3" height="1" fill="#FFDD00"/></svg>`,
    "EE": `<svg viewBox="0 0 33 21" class="svg-flag"><rect width="33" height="7" fill="#0072CE"/><rect y="7" width="33" height="7" fill="#000"/><rect y="14" width="33" height="7" fill="#FFF"/></svg>`,
    "LV": `<svg viewBox="0 0 20 10" class="svg-flag"><rect width="20" height="4" fill="#9E3039"/><rect y="4" width="20" height="2" fill="#FFF"/><rect y="6" width="20" height="4" fill="#9E3039"/></svg>`,
    "LT": `<svg viewBox="0 0 5 3" class="svg-flag"><rect width="5" height="1" fill="#FDB913"/><rect y="1" width="5" height="1" fill="#006A44"/><rect y="2" width="5" height="1" fill="#C1272D"/></svg>`,
    "GE": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="2" fill="#FFF"/><path d="M0,0.8 h3 v0.4 h-3 z M1.3,0 v2 h0.4 v-2 z" fill="#FF0000"/></svg>`,
    "AM": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="0.67" fill="#D90012"/><rect y="0.67" width="3" height="0.66" fill="#0033A0"/><rect y="1.33" width="3" height="0.67" fill="#F2A800"/></svg>`,
    "BY": `<svg viewBox="0 0 6 3" class="svg-flag"><rect width="6" height="2" fill="#C8232A"/><rect y="2" width="6" height="1" fill="#439547"/><rect width="0.9" height="3" fill="#FFF"/><path d="M0.45,0.4 L0.2,0.8 L0.45,1.2 L0.7,0.8 Z M0.45,1.4 L0.2,1.8 L0.45,2.2 L0.7,1.8 Z M0.45,2.4 L0.2,2.8 L0.45,3.2 L0.7,2.8 Z" fill="#C8232A"/></svg>`,
    "MD": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="1" height="2" fill="#003DA5"/><rect x="1" width="1" height="2" fill="#FFD100"/><rect x="2" width="1" height="2" fill="#C8102E"/></svg>`,
    "UZ": `<svg viewBox="0 0 5 2.5" class="svg-flag"><rect width="5" height="0.8" fill="#1EB53A"/><rect y="0.8" width="5" height="0.9" fill="#FFF"/><rect y="1.7" width="5" height="0.8" fill="#0099B5"/><line y1="0.8" x2="5" y2="0.8" stroke="#CE1126" stroke-width="0.05"/><line y1="1.7" x2="5" y2="1.7" stroke="#CE1126" stroke-width="0.05"/></svg>`,
    "KR": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="2" fill="#FFF"/><circle cx="1.5" cy="1" r="0.5" fill="#CD2E3A"/><path d="M1,1 a0.5,0.5 0 0,0 1,0 a0.25,0.25 0 0,0 -0.5,0 a0.25,0.25 0 0,1 -0.5,0" fill="#0047A0"/></svg>`,
    "IN": `<svg viewBox="0 0 3 2" class="svg-flag"><rect width="3" height="0.67" fill="#FF9933"/><rect y="0.67" width="3" height="0.66" fill="#FFF"/><rect y="1.33" width="3" height="0.67" fill="#138808"/><circle cx="1.5" cy="1" r="0.2" fill="#000080"/></svg>`,
    "BR": `<svg viewBox="0 0 20 14" class="svg-flag"><rect width="20" height="14" fill="#009739"/><polygon points="10,1.7 18.3,7 10,12.3 1.7,7" fill="#FEDD00"/><circle cx="10" cy="7" r="3.5" fill="#012169"/></svg>`,
    "AU": `<svg viewBox="0 0 60 30" class="svg-flag"><rect width="60" height="30" fill="#00008B"/><path d="M0,0 L30,15 M30,0 L0,15" stroke="#fff" stroke-width="3"/><path d="M15,0 v15 M0,7.5 h30" stroke="#fff" stroke-width="5"/><path d="M15,0 v15 M0,7.5 h30" stroke="#cf142b" stroke-width="3"/><circle cx="45" cy="21" r="2.5" fill="#FFF"/><circle cx="51" cy="13.5" r="2" fill="#FFF"/><circle cx="39" cy="10" r="2" fill="#FFF"/><circle cx="45" cy="5" r="2" fill="#FFF"/></svg>`,
};

function getCountryFlagHtml(code, fallbackEmoji = "🌐") {
    const upperCode = (code || "").toUpperCase();
    if (SVG_FLAGS[upperCode]) {
        return `<span class="country-flag-wrapper" title="${upperCode}">${SVG_FLAGS[upperCode]}</span>`;
    }
    // Fallback: styled ISO pill or globe
    if (upperCode && upperCode !== "UN" && upperCode.length === 2) {
        return `<span class="country-flag-badge">${upperCode}</span>`;
    }
    return `<span class="country-flag-wrapper"><svg viewBox="0 0 24 24" class="svg-flag-globe" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg></span>`;
}
