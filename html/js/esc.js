// Zentraler HTML-Escape-Helfer (&<>"') — ersetzt ~19 divergierende lokale Kopien,
// von denen die meisten Anführungszeichen NICHT escapten (Attribut-Ausbruch möglich).
// Ohne defer einbinden, VOR allen Scripts, die ihn nutzen (Inline-Scripts laufen zur Parse-Zeit).
window.escHtml = function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
};
