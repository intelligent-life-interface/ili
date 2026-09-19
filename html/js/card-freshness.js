// card-freshness.js — reine Logik für den Karteileichen-Filter (kein DOM-Zugriff).
// Bewusst als eigenes Modul: in Node ohne Browser testbar (tests/test_card_freshness.py
// ruft es per `node` auf), gemeinsamer globaler Scope wie die übrigen project-*.js.
//
// Zeitbasis: card.updated_at, sonst card.created_at (beide vom Server gestempelt,
// app/storage/board_repository.py `_stamp_updated_at`/`_stamp_created_at`). Fehlt
// beides (z.B. alte Seed-Karten vor der Einführung des Feldes), gilt die Karte als
// "unbekannt" — NICHT als Leiche, siehe Kanban-Auftrag vom 18.09.2026.

function daysSinceCardTouch(card, nowMs) {
    var ts = card && (card.updated_at || card.created_at);
    if (!ts) return null;
    var t = Date.parse(ts);
    if (isNaN(t)) return null;
    return (nowMs - t) / 86400000;
}

function isZombieCard(card, thresholdDays, nowMs) {
    var days = daysSinceCardTouch(card, nowMs);
    if (days === null) return false;
    return days >= thresholdDays;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { daysSinceCardTouch: daysSinceCardTouch, isZombieCard: isZombieCard };
}
