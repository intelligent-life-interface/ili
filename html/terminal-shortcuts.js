/* =====================================================================
   Terminal-Shortcuts — EINZIGE Pflege-Datei.
   Genutzt von:  /m/  (Mobil-Dashboard, gleicher Origin)
                 terminals.html  (Caddy, lädt diese Datei cross-origin per <script>)
   ---------------------------------------------------------------------
   Neuen Shortcut = EINE Zeile im Array ergänzen.
     label : Text auf dem Knopf (Emoji erlaubt)
     text  : was ins Terminal geschickt wird
     send  : optional. Fehlt/true → Text wird MIT Enter abgeschickt (Claude legt los).
             false → Text wird nur ins Eingabefeld gelegt / ins Terminal getippt,
                     du kannst noch anpassen und selbst Enter drücken.
   ===================================================================== */
window.TERM_SHORTCUTS = [
  { "label": "▶ Entwicklung",  "text": "Starte die Entwicklung dieses Projekts." },
  { "label": "📋 Kanban",      "text": "Generiere das Kanban für dieses Projekt." },
  { "label": "💡 Idee planen", "text": "Lass uns diese Idee planen." }
];
