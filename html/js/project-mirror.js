// project-mirror.js — Spiegel-Karten als sichtbaren Verweis auf ihren Master.
//
// Warum es überhaupt Kopien gibt: Boards sind je eine eigene JSON-Datei und Karten
// liegen eingebettet in columns[].cards[] — es gibt keinen zentralen Karten-Index.
// Eine Karte „in mehreren Boards" ist deshalb physisch ein zweites Objekt, das
// auseinanderläuft. Der Spiegel (`mirror::<board>::<card>`) bleibt eine Kopie,
// zeigt aber jetzt offen, wo sein Master liegt, und verlinkt direkt dorthin.
//
// Zwei Teile:
//   1. renderMirrorLink(card, el) — Chip „🔗 Master: <Projekt>" auf der Karte
//      (Hook aus renderCard() in project-board.js)
//   2. focusCardFromUrl() — Ziel des Links: ?card=<id> hebt die Karte hervor und
//      scrollt sie ins Bild (Hook aus loadBoard() in project-core.js)
// Klassik-Script, gemeinsamer globaler Scope mit den uebrigen project-*.js.

const FOCUS_CARD_ID = params.get('card') || '';
let focusDone = false;

// Master = die Original-Karte im Quell-Projekt. Der Projektname steht bereits im
// Spiegel-Text ("🔁 Aus Projekt **X**"), darum ist dafür kein Request nötig;
// Fallback ist der Manifest-Name aus allBoardsCache, sonst die Board-id.
function masterInfo(card) {
    if (!card || !card.mirror_source_board) return null;
    const body = String(card.desc || card.description || '');
    const m = body.match(/^🔁 Aus Projekt \*\*(.+?)\*\*/);
    let name = m ? m[1] : '';
    if (!name && typeof allBoardsCache !== 'undefined' && Array.isArray(allBoardsCache)) {
        const entry = allBoardsCache.find(b => b.id === card.mirror_source_board);
        if (entry) name = entry.name || '';
    }
    return {
        board: card.mirror_source_board,
        cardId: card.mirror_source_card || '',
        name: name || card.mirror_source_board,
    };
}

function renderMirrorLink(card, el) {
    const info = masterInfo(card);
    if (!info) return;
    el.classList.add('mirror-card');
    const a = document.createElement('a');
    a.className = 'card-master-link';
    a.href = '/project.html?id=' + encodeURIComponent(info.board)
           + (info.cardId ? '&card=' + encodeURIComponent(info.cardId) : '');
    a.textContent = '🔗 Master: ' + info.name;
    a.title = 'Original-Karte in „' + info.name + '" öffnen — dort wird sie gepflegt, '
            + 'diese Karte hier ist nur der Spiegel.';
    a.onclick = e => e.stopPropagation();   // Klick öffnet den Master, nicht das Detail-Modal
    el.appendChild(a);
}

// Ziel eines Master-Links: Karte suchen, hervorheben, ins Bild scrollen.
// Läuft nur einmal pro Seitenaufruf (sonst springt die Ansicht bei jedem Autosave).
function focusCardFromUrl() {
    if (!FOCUS_CARD_ID || focusDone) return;
    const el = document.querySelector('.card[data-card-id="' + CSS.escape(FOCUS_CARD_ID) + '"]');
    if (!el) {
        console.warn('[Mirror] Karte', FOCUS_CARD_ID, 'in diesem Board nicht gefunden');
        return;
    }
    focusDone = true;
    el.classList.add('card-focus');
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    console.log('[Mirror] Master-Karte fokussiert:', FOCUS_CARD_ID);
}
